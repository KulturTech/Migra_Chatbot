"""Austauschbare Sprachmodell-Anbindung.

Das Modell hat im Programm genau zwei Aufgaben:
1. followup(): eine kurze Nachfrage formulieren (oder melden, dass das Thema erzählt ist)
2. classify(): eine Nachricht auf Belastung oder Krise einschätzen

Alles andere (Ablauf, Einwilligung, Krisentexte, Hilfsangebote) passiert im Programm.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

from .config import Settings
from .state import Turn

log = logging.getLogger(__name__)


@dataclass
class FollowupContext:
    block_title: str
    question_text: str
    answer: str
    sensitive: bool
    followups_used: int
    max_followups: int
    scripted: list[str] = field(default_factory=list)
    recent: list[Turn] = field(default_factory=list)


@dataclass
class FollowupResult:
    message: str | None = None
    covered: bool = False


class LLM(Protocol):
    def followup(self, ctx: FollowupContext) -> FollowupResult | None: ...
    def classify(self, text: str) -> str | None: ...


class MockLLM:
    """Kein Modellaufruf. Der Zustandsautomat nutzt dann die Nachfragen aus dem Leitfaden."""

    def followup(self, ctx: FollowupContext) -> FollowupResult | None:
        return None

    def classify(self, text: str) -> str | None:
        return None


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json(raw: str) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = _JSON_RE.search(raw)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


class OpenAICompatLLM:
    """Jede API mit OpenAI-kompatibler Chat-Schnittstelle (KISSKI/GWDG, Mistral, OpenAI EU, vLLM, ...)."""

    def __init__(self, base_url: str, api_key: str, model: str, system_prompt: str, timeout: float = 30.0):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Für LLM_PROVIDER=openai_compat: pip install '.[llm]'") from exc
        if not (base_url and model):
            raise RuntimeError("LLM_BASE_URL und LLM_MODEL müssen gesetzt sein.")
        # Wenige Wiederholungen: Fällt das Modell aus, soll der Leitfaden schnell übernehmen.
        self._client = OpenAI(base_url=base_url, api_key=api_key or "none", timeout=timeout, max_retries=1)
        self._model = model
        self._system_prompt = system_prompt

    def _chat(self, messages: list[dict], max_tokens: int = 200) -> str:
        kwargs = dict(model=self._model, messages=messages, temperature=0.3, max_tokens=max_tokens)
        try:
            resp = self._client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
        except Exception as exc:
            # Nicht jede API kennt response_format (HTTP 400/422). Nur dann ohne erneut versuchen,
            # bei Ausfall oder Zeitüberschreitung übernimmt direkt der Leitfaden.
            if getattr(exc, "status_code", None) not in (400, 422):
                raise
            log.info("response_format nicht unterstützt, neuer Versuch ohne")
            resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def followup(self, ctx: FollowupContext) -> FollowupResult | None:
        history = [
            {"role": "user" if t.role == "user" else "assistant", "content": t.text}
            for t in ctx.recent[-6:]
        ]
        task = (
            f"Aktueller Block: {ctx.block_title}\n"
            f"Gestellte Frage: {ctx.question_text}\n"
            f"Letzte Antwort der Person: {ctx.answer}\n"
            f"Bisherige Nachfragen zu dieser Frage: {ctx.followups_used} von höchstens {ctx.max_followups}\n"
            f"Sensibler Block: {'ja' if ctx.sensitive else 'nein'}\n"
            f"Mögliche Nachfragen aus dem Leitfaden (Orientierung, nicht wörtlich nötig): {ctx.scripted}\n\n"
            'Gib NUR JSON zurück: {"message": "...", "covered": true|false}'
        )
        messages = [{"role": "system", "content": self._system_prompt}, *history,
                    {"role": "user", "content": task}]
        data = _parse_json(self._chat(messages))
        if not isinstance(data, dict):
            return None
        return FollowupResult(
            message=(data.get("message") or "").strip() or None,
            covered=bool(data.get("covered", False)),
        )

    def classify(self, text: str) -> str | None:
        system = (
            "Du bist ein vorsichtiger Klassifikator für ein Forschungsinterview. Stufe die folgende "
            "Nachricht ein: 'crisis' bei Hinweisen auf Suizid, Selbstverletzung, akute Gewalt oder "
            "unmittelbare Gefahr; 'distress' bei starker emotionaler Belastung; sonst 'none'. "
            "Die Nachricht kann in jeder Sprache stehen. Im Zweifel die höhere Stufe. "
            'Antworte NUR mit JSON: {"level": "none|distress|crisis"}'
        )
        data = _parse_json(self._chat(
            [{"role": "system", "content": system}, {"role": "user", "content": text}], max_tokens=30))
        level = (data or {}).get("level") if isinstance(data, dict) else None
        return level if level in {"none", "distress", "crisis"} else None


def make_llm(settings: Settings, system_prompt: str) -> LLM:
    if settings.llm_provider == "mock":
        return MockLLM()
    if settings.llm_provider == "openai_compat":
        return OpenAICompatLLM(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            system_prompt=system_prompt,
            timeout=settings.llm_timeout_seconds,
        )
    raise ValueError(f"Unbekannter LLM_PROVIDER: {settings.llm_provider}")
