"""Einstellungen aus Umgebungsvariablen (optional aus einer .env-Datei)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimaler .env-Leser, damit keine zusätzliche Abhängigkeit nötig ist."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    env: str = "dev"
    llm_provider: str = "openai_compat"
    llm_base_url: str = "http://localhost:11434/v1/"
    llm_api_key: str = "ollama"
    llm_model: str = "llama3.1:8b"
    llm_timeout_seconds: float = 30.0
    guide_path: Path = Path("config/guide_de.yaml")
    system_prompt_path: Path = Path("prompts/system_prompt_de.md")
    db_path: Path = Path("data/interviews.sqlite3")
    static_dir: Path = Path("static")
    escalation_webhook_url: str = ""

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @classmethod
    def from_env(cls, dotenv: str | Path | None = ".env") -> "Settings":
        if dotenv:
            _load_dotenv(Path(dotenv))
        g = os.environ.get
        return cls(
            env=g("ENV", "dev"),
            llm_provider=g("LLM_PROVIDER", "openai_compat"),
            llm_base_url=g("LLM_BASE_URL", "http://localhost:11434/v1/"),
            llm_api_key=g("LLM_API_KEY", "ollama"),
            llm_model=g("LLM_MODEL", "llama3.1:8b"),
            llm_timeout_seconds=float(g("LLM_TIMEOUT_SECONDS", "30") or 30),
            guide_path=Path(g("GUIDE_PATH", "config/guide_de.yaml")),
            system_prompt_path=Path(g("SYSTEM_PROMPT_PATH", "prompts/system_prompt_de.md")),
            db_path=Path(g("DB_PATH", "data/interviews.sqlite3")),
            static_dir=Path(g("STATIC_DIR", "static")),
            escalation_webhook_url=g("ESCALATION_WEBHOOK_URL", ""),
        )
