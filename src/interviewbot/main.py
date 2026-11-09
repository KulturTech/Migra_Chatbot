"""FastAPI-App: dünne Schicht um Engine und Store."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .engine import Engine
from .guide import Guide, load_guide, load_system_prompt
from .llm import LLM, make_llm
from .notify import notify_team
from .state import FINAL_PHASES, BotMessage, Phase, SessionState
from .store import Store

log = logging.getLogger("interviewbot")


class MessageIn(BaseModel):
    text: str | None = Field(default=None, max_length=4000)
    action: Literal["end", "pause", "resume", "skip"] | None = None


class StepOut(BaseModel):
    session_code: str
    messages: list[BotMessage]
    phase: Phase
    ended: bool


def check_startup(settings: Settings, guide: Guide) -> list[str]:
    """Gibt Warnungen zurück. Im Modus production sind sie Fehler."""
    problems: list[str] = []
    placeholders = guide.placeholder_warnings()
    if placeholders:
        problems.append(f"Platzhalter im Leitfaden nicht ersetzt: {placeholders}")
    if settings.llm_provider == "mock":
        problems.append("LLM_PROVIDER=mock: kein Sprachmodell angebunden")
    return problems


def create_app(settings: Settings | None = None, llm: LLM | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    guide = load_guide(settings.guide_path)
    system_prompt = load_system_prompt(settings.system_prompt_path)

    problems = check_startup(settings, guide)
    if settings.is_production and problems:
        raise RuntimeError("Start im Modus production abgebrochen:\n- " + "\n- ".join(problems))
    for p in problems:
        log.warning("Startprüfung: %s", p)

    llm = llm or make_llm(settings, system_prompt)
    engine = Engine(guide, llm)
    store = Store(settings.db_path)

    app = FastAPI(title="Interview-Bot", docs_url=None if settings.is_production else "/docs", redoc_url=None)

    def _out(state: SessionState, messages: list[BotMessage]) -> StepOut:
        return StepOut(session_code=state.session_code, messages=messages,
                       phase=state.phase, ended=state.phase in FINAL_PHASES)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "llm": settings.llm_provider, "warnings": check_startup(settings, guide)}

    @app.post("/api/sessions", response_model=StepOut)
    def create_session() -> StepOut:
        state = SessionState(session_code=store.new_code())
        store.create_session(state)
        result = engine.start(state)
        for m in result.messages:
            store.add_turn(state.session_code, "bot", m.text, m.kind, m.block_id, m.question_id)
        store.save_state(state)
        return _out(state, result.messages)

    @app.post("/api/sessions/{code}/messages", response_model=StepOut)
    def send_message(code: str, body: MessageIn) -> StepOut:
        state = store.load_state(code)
        if state is None:
            raise HTTPException(status_code=404, detail="Sitzung nicht gefunden")
        text = (body.text or "").strip() or None

        if text:
            block_id, question_id = engine.current_ids(state)
            store.add_turn(code, "user", text, "answer", block_id, question_id)

        result = engine.step(state, text, body.action)

        # Wer nicht teilnehmen möchte, hinterlässt keine Daten.
        if state.phase == Phase.DECLINED:
            store.delete_session(code)
            return _out(state, result.messages)

        for m in result.messages:
            store.add_turn(code, "bot", m.text, m.kind, m.block_id, m.question_id)
        store.save_state(state)

        if result.escalation:
            store.log_escalation(code, result.escalation)
            notify_team(settings.escalation_webhook_url, code, result.escalation)
        return _out(state, result.messages)

    @app.delete("/api/sessions/{code}")
    def delete_session(code: str) -> dict:
        if not store.delete_session(code):
            raise HTTPException(status_code=404, detail="Sitzung nicht gefunden")
        return {"deleted": True}

    @app.get("/api/help")
    def help_text() -> dict:
        return {"text": f"{guide.text('help_header')}\n{guide.resources_text('counseling')}\n"
                        f"{guide.resources_text('crisis')}"}

    static_dir = settings.static_dir
    if (static_dir / "index.html").is_file():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(static_dir / "index.html")

    app.state.engine, app.state.store, app.state.guide = engine, store, guide
    return app


def app_factory() -> FastAPI:
    """Für uvicorn: uvicorn interviewbot.main:app_factory --factory"""
    logging.basicConfig(level=logging.INFO)
    return create_app()
