"""Leitfaden: Fragen, Nachfragen, Festtexte und Hilfsangebote, geladen aus YAML."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

# Platzhalter wie [PROJEKTNAME] oder [KONTAKT FORSCHUNGSTEAM EINTRAGEN]
PLACEHOLDER_RE = re.compile(r"\[[A-ZÄÖÜ0-9][A-ZÄÖÜ0-9 _/\-]{2,}\]")

REQUIRED_TEXTS = {
    "consent_intro", "consent_question", "consent_unclear", "consent_declined", "started",
    "pause", "resume", "skipped", "block_declined", "warning_unclear", "distress", "wellbeing",
    "crisis_text", "crisis_unclear", "ended_by_user", "closing", "already_ended",
    "back_to_question", "help_header",
}
REQUIRED_BOUNDARIES = {
    "ask_human", "ask_data", "ask_delete", "status_fear", "advice_request", "ask_judgment",
    "manipulation", "manipulation_second", "abuse",
}


class Question(BaseModel):
    id: str
    text: str
    # None = vom Block erben, [] = bewusst keine Nachfragen
    followups: list[str] | None = None


class Block(BaseModel):
    id: str
    title: str
    sensitive: bool = False
    warning: str | None = None
    intro: str | None = None
    # None = default_followups, [] = bewusst keine Nachfragen
    followups: list[str] | None = None
    questions: list[Question]


class Resource(BaseModel):
    name: str
    contact: str
    note: str = ""
    tags: list[str] = Field(default_factory=list)


class GuideSettings(BaseModel):
    max_followups: int = 2
    min_words: int = 3
    ack_min_words: int = 6
    distress_cooldown: int = 3
    max_message_chars: int = 4000


class Study(BaseModel):
    name: str = ""
    target_minutes: int = 30


class Guide(BaseModel):
    study: Study = Field(default_factory=Study)
    settings: GuideSettings = Field(default_factory=GuideSettings)
    acknowledgments: list[str] = Field(default_factory=lambda: ["Danke."])
    default_followups: list[str] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    texts: dict[str, str]
    boundaries: dict[str, str]
    blocks: list[Block]

    @model_validator(mode="after")
    def _check(self) -> "Guide":
        missing = REQUIRED_TEXTS - self.texts.keys()
        if missing:
            raise ValueError(f"Fehlende Festtexte in 'texts': {sorted(missing)}")
        missing_b = REQUIRED_BOUNDARIES - self.boundaries.keys()
        if missing_b:
            raise ValueError(f"Fehlende Festtexte in 'boundaries': {sorted(missing_b)}")
        if not self.blocks:
            raise ValueError("Der Leitfaden braucht mindestens einen Block.")
        block_ids = [b.id for b in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("Block-IDs müssen eindeutig sein.")
        q_ids = [q.id for b in self.blocks for q in b.questions]
        if len(q_ids) != len(set(q_ids)):
            raise ValueError("Fragen-IDs müssen eindeutig sein.")
        for b in self.blocks:
            if not b.questions:
                raise ValueError(f"Block '{b.id}' hat keine Fragen.")
            if b.sensitive and not b.warning:
                raise ValueError(f"Sensibler Block '{b.id}' braucht eine 'warning' (Vorwarnung).")
        return self

    # --- Textzugriff ---------------------------------------------------------

    def resources_text(self, tag: str | None = None) -> str:
        rows = [r for r in self.resources if tag is None or tag in r.tags]
        lines = []
        for r in rows:
            line = f"- {r.name}: {r.contact}"
            if r.note:
                line += f" ({r.note})"
            lines.append(line)
        return "\n".join(lines)

    def render(self, template: str, session_code: str = "", resources_tag: str | None = None) -> str:
        """Setzt {session_code} und {resources} ein. Andere geschweifte Klammern bleiben unberührt."""
        out = template.replace("{session_code}", session_code)
        out = out.replace("{resources}", self.resources_text(resources_tag))
        return out.strip()

    def text(self, key: str, session_code: str = "", resources_tag: str | None = None) -> str:
        return self.render(self.texts[key], session_code, resources_tag)

    def boundary(self, key: str, session_code: str = "") -> str:
        return self.render(self.boundaries[key], session_code, resources_tag="counseling")

    def all_fixed_text(self) -> str:
        """Alles, was das Programm selbst ausgibt. Wird für den Platzhalter-Check genutzt."""
        parts = list(self.texts.values()) + list(self.boundaries.values())
        parts += [r.contact for r in self.resources]
        for b in self.blocks:
            parts += [b.warning or "", b.intro or ""] + [q.text for q in b.questions]
        return "\n".join(parts)

    def placeholder_warnings(self) -> list[str]:
        found = sorted(set(PLACEHOLDER_RE.findall(self.all_fixed_text())))
        return found


def load_guide(path: str | Path) -> Guide:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Guide.model_validate(data)


def load_system_prompt(path: str | Path) -> str:
    p = Path(path)
    return p.read_text(encoding="utf-8") if p.is_file() else ""
