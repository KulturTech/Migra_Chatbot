from __future__ import annotations

from pathlib import Path

import pytest

from interviewbot.engine import Engine
from interviewbot.guide import load_guide
from interviewbot.llm import FollowupContext, FollowupResult
from interviewbot.state import FINAL_PHASES, Phase, SessionState

ROOT = Path(__file__).resolve().parents[1]
LONG = "Ich war letzte Woche beim Amt und habe sehr lange gewartet, dann wurde mein Antrag geprüft."


@pytest.fixture(scope="session")
def guide():
    return load_guide(ROOT / "config" / "guide_de.yaml")


@pytest.fixture
def engine(guide):
    return Engine(guide)


@pytest.fixture
def state():
    return SessionState(session_code="TEST0001")


def texts(result) -> list[str]:
    return [m.text for m in result.messages]


def drive(engine: Engine, state: SessionState, until, fill: str = LONG, max_turns: int = 300) -> list[str]:
    """Antwortet neutral, bis `until(state)` wahr ist. Gibt alle Bot-Texte zurück."""
    seen: list[str] = []
    for _ in range(max_turns):
        if until(state) or state.phase in FINAL_PHASES:
            break
        if state.phase in (Phase.CONSENT, Phase.BLOCK_WARNING):
            text = "Ja"
        elif state.phase in (Phase.WELLBEING, Phase.DISTRESS, Phase.PAUSED, Phase.CRISIS):
            text = "Weiter"
        else:
            text = fill
        seen += texts(engine.step(state, text=text))
    return seen


def start_interview(engine: Engine, state: SessionState) -> None:
    engine.start(state)
    engine.step(state, text="Ja")
    assert state.phase == Phase.INTERVIEW


def goto_block(engine: Engine, state: SessionState, block_id: str, guide) -> None:
    idx = next(i for i, b in enumerate(guide.blocks) if b.id == block_id)
    engine.start(state)
    drive(engine, state, lambda s: s.block_idx == idx and s.phase in (Phase.INTERVIEW, Phase.BLOCK_WARNING))
    assert state.block_idx == idx


class FakeLLM:
    """Steuerbares Modell für Tests."""

    def __init__(self, message: str | None = None, covered: bool = False, level: str | None = None,
                 raises: bool = False):
        self.message, self.covered, self.level, self.raises = message, covered, level, raises
        self.calls: list[FollowupContext] = []

    def followup(self, ctx: FollowupContext):
        self.calls.append(ctx)
        if self.raises:
            raise TimeoutError("simuliert")
        return FollowupResult(message=self.message, covered=self.covered)

    def classify(self, text: str):
        return self.level
