"""Gesprächszustand. Alles, was der Zustandsautomat über ein Interview weiß."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Phase(str, Enum):
    CONSENT = "consent"
    INTERVIEW = "interview"
    BLOCK_WARNING = "block_warning"
    WELLBEING = "wellbeing"
    DISTRESS = "distress"
    PAUSED = "paused"
    CRISIS = "crisis"
    ENDED = "ended"
    DECLINED = "declined"


FINAL_PHASES = {Phase.ENDED, Phase.DECLINED}


class Turn(BaseModel):
    role: str  # "user" oder "bot"
    text: str
    block_id: str | None = None
    question_id: str | None = None
    kind: str = "message"


class BotMessage(BaseModel):
    text: str
    kind: str = "message"  # question | followup | info | warning | crisis | boundary | closing
    block_id: str | None = None
    question_id: str | None = None


class SessionState(BaseModel):
    session_code: str
    phase: Phase = Phase.CONSENT
    resume_phase: Phase | None = None
    block_idx: int = 0
    q_idx: int = 0
    followups_used: int = 0
    distress_cooldown: int = 0
    manipulation_strikes: int = 0
    guardrail_hits: int = 0
    acks_given: int = 0
    escalated: bool = False
    consent_given: bool = False
    skipped_blocks: list[str] = Field(default_factory=list)
    # Nur die letzten Turns, als Kontext für das Modell. Das volle Protokoll liegt in der Datenbank.
    recent: list[Turn] = Field(default_factory=list)
