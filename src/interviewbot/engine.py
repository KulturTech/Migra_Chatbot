"""Zustandsautomat des Interviews.

Das Programm steuert Ablauf, Einwilligung, Blockwechsel, Pausen, Krisen und Grenzfälle.
Das Sprachmodell darf nur eine kurze Nachfrage formulieren, und diese wird geprüft
(guardrails.check_output). Fällt das Modell aus oder verstößt es gegen eine Regel,
kommt die Nachfrage aus dem Leitfaden.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from . import safety
from .guardrails import check_output
from .guide import Block, Guide, Question
from .intents import detect_boundary, is_non_answer, parse_control, parse_yes_no
from .llm import LLM, FollowupContext, MockLLM
from .state import FINAL_PHASES, BotMessage, Phase, SessionState, Turn

log = logging.getLogger(__name__)

# Nach diesen festen Antworten wird die aktuelle Frage noch einmal gestellt.
_REPROMPT_AFTER = {"ask_human", "ask_data", "ask_delete", "status_fear", "advice_request", "manipulation"}


class StepResult(BaseModel):
    messages: list[BotMessage] = Field(default_factory=list)
    escalation: str | None = None  # z. B. "crisis": das Team soll einen Hinweis erhalten (ohne Inhalte)


class Engine:
    def __init__(self, guide: Guide, llm: LLM | None = None):
        self.guide = guide
        self.llm: LLM = llm or MockLLM()

    # ------------------------------------------------------------------ öffentlich

    def start(self, state: SessionState) -> StepResult:
        state.phase = Phase.CONSENT
        msgs = [self._info("consent_intro", state), self._info("consent_question", state)]
        self._remember_bot(state, msgs)
        return StepResult(messages=msgs)

    def step(self, state: SessionState, text: str | None = None, action: str | None = None) -> StepResult:
        result = self._step(state, text, action)
        self._remember_bot(state, result.messages)
        return result

    def current_ids(self, state: SessionState) -> tuple[str | None, str | None]:
        """(block_id, question_id), solange gerade eine Frage offen ist."""
        if state.phase == Phase.INTERVIEW and state.block_idx < len(self.guide.blocks):
            block = self.guide.blocks[state.block_idx]
            return block.id, block.questions[state.q_idx].id
        return None, None

    # ------------------------------------------------------------------ Kern

    def _step(self, state: SessionState, text: str | None, action: str | None) -> StepResult:
        text = (text or "").strip()
        if state.phase in FINAL_PHASES:
            return self._r([self._info("already_ended", state)])

        if text:
            block_id, question_id = self.current_ids(state)
            self._remember(state, Turn(role="user", text=text, block_id=block_id, question_id=question_id))

        # Schaltflächen
        if action == "end":
            return self._finish(state, "ended_by_user")
        if action == "pause":
            return self._pause(state)
        if action == "resume":
            return self._resume(state)
        if action == "skip":
            return self._skip(state)

        if not text:
            return self._r([self._prompt(state)])

        if state.phase == Phase.PAUSED:
            if parse_control(text, 8) == "end":
                return self._finish(state, "ended_by_user")
            return self._resume(state)

        # Sicherheitsprüfung jeder Nachricht (Stichwörter immer, Modell nur bei längeren Texten)
        classifier = self.llm if len(text.split()) >= 3 else None
        level = safety.assess(text, classifier)
        if level == "crisis":
            return self._crisis(state)
        if state.phase == Phase.CRISIS:
            return self._crisis_followup(state, text)
        if (level == "distress" and state.distress_cooldown == 0
                and state.phase in (Phase.INTERVIEW, Phase.WELLBEING, Phase.BLOCK_WARNING)):
            return self._distress(state)

        # Grenzfälle mit festen Antworten
        boundary = detect_boundary(text)
        if boundary:
            return self._boundary(state, boundary)

        handler = {
            Phase.CONSENT: self._on_consent,
            Phase.BLOCK_WARNING: self._on_warning,
            Phase.INTERVIEW: self._on_answer,
            Phase.WELLBEING: self._on_wellbeing,
            Phase.DISTRESS: self._on_distress,
        }.get(state.phase)
        if handler is None:  # sollte nicht vorkommen
            return self._r([self._prompt(state)])
        return handler(state, text)

    # ------------------------------------------------------------------ Phasen

    def _on_consent(self, state: SessionState, text: str) -> StepResult:
        yn = parse_yes_no(text)
        if yn == "yes":
            state.consent_given = True
            state.phase = Phase.INTERVIEW
            return self._r([self._info("started", state)] + self._enter_block(state, 0))
        if yn == "no":
            state.phase = Phase.DECLINED
            return self._r([self._info("consent_declined", state)])
        return self._r([self._info("consent_unclear", state)])

    def _on_warning(self, state: SessionState, text: str) -> StepResult:
        control = parse_control(text, 4)
        if control == "end":
            return self._finish(state, "ended_by_user")
        if control == "pause":
            return self._pause(state)
        yn = parse_yes_no(text)
        if yn == "yes":
            return self._r(self._begin_questions(state))
        if yn == "no" or control == "skip":
            return self._r(self._decline_block(state))
        return self._r([self._info("warning_unclear", state)])

    def _on_wellbeing(self, state: SessionState, text: str) -> StepResult:
        control = parse_control(text, 8)
        if control == "end":
            return self._finish(state, "ended_by_user")
        if control == "pause":
            return self._pause(state)
        return self._r(self._enter_block(state, state.block_idx + 1))

    def _on_distress(self, state: SessionState, text: str) -> StepResult:
        control = parse_control(text, 8)
        if control == "end":
            return self._finish(state, "ended_by_user")
        if control == "pause":
            return self._pause(state)
        if control == "skip":
            self._restore(state)
            return self._skip(state)
        if control == "continue":
            self._restore(state)
            return self._r([self._info("resume", state), self._prompt(state)])
        return self._r([self._info("distress", state)])

    def _on_answer(self, state: SessionState, text: str) -> StepResult:
        if state.distress_cooldown > 0:
            state.distress_cooldown -= 1
        control = parse_control(text, 4)
        if control == "end":
            return self._finish(state, "ended_by_user")
        if control == "pause":
            return self._pause(state)
        if control == "skip":
            return self._skip(state)

        s = self.guide.settings
        block, question = self._current(state)
        n_words = len(text.split())

        if is_non_answer(text):
            return self._r(self._advance(state, []))

        short = n_words < s.min_words
        may_follow_up = state.followups_used < s.max_followups and not (short and state.followups_used >= 1)
        if may_follow_up:
            follow_up = self._next_followup(state, block, question, text)
            if follow_up:
                state.followups_used += 1
                return self._r([BotMessage(text=follow_up, kind="followup",
                                           block_id=block.id, question_id=question.id)])
        return self._r(self._advance(state, self._ack(state, n_words)))

    # ------------------------------------------------------------------ Übergänge

    def _enter_block(self, state: SessionState, idx: int) -> list[BotMessage]:
        state.block_idx, state.q_idx, state.followups_used = idx, 0, 0
        if idx >= len(self.guide.blocks):
            return self._finish(state, "closing").messages
        block = self.guide.blocks[idx]
        if block.warning:
            state.phase = Phase.BLOCK_WARNING
            return [BotMessage(text=block.warning, kind="warning", block_id=block.id)]
        return self._begin_questions(state)

    def _begin_questions(self, state: SessionState) -> list[BotMessage]:
        state.phase = Phase.INTERVIEW
        block = self.guide.blocks[state.block_idx]
        msgs: list[BotMessage] = []
        if block.intro:
            msgs.append(BotMessage(text=block.intro, kind="info", block_id=block.id))
        msgs.append(self._question_msg(state))
        return msgs

    def _decline_block(self, state: SessionState) -> list[BotMessage]:
        state.skipped_blocks.append(self.guide.blocks[state.block_idx].id)
        return [self._info("block_declined", state)] + self._enter_block(state, state.block_idx + 1)

    def _advance(self, state: SessionState, lead: list[BotMessage]) -> list[BotMessage]:
        block = self.guide.blocks[state.block_idx]
        state.q_idx += 1
        state.followups_used = 0
        if state.q_idx < len(block.questions):
            return lead + [self._question_msg(state)]
        if block.sensitive:
            state.phase = Phase.WELLBEING
            return lead + [self._info("wellbeing", state)]
        return lead + self._enter_block(state, state.block_idx + 1)

    def _skip(self, state: SessionState) -> StepResult:
        if state.phase == Phase.DISTRESS:
            self._restore(state)
        if state.phase == Phase.INTERVIEW:
            return self._r(self._advance(state, [self._info("skipped", state)]))
        if state.phase == Phase.BLOCK_WARNING:
            return self._r(self._decline_block(state))
        if state.phase == Phase.WELLBEING:
            return self._r(self._enter_block(state, state.block_idx + 1))
        return self._r([self._prompt(state)])

    def _pause(self, state: SessionState) -> StepResult:
        if state.phase in FINAL_PHASES:
            return self._r([self._info("already_ended", state)])
        if state.phase not in (Phase.PAUSED, Phase.CRISIS, Phase.DISTRESS):
            state.resume_phase = state.phase
        state.phase = Phase.PAUSED
        return self._r([self._info("pause", state)])

    def _resume(self, state: SessionState) -> StepResult:
        if state.phase != Phase.PAUSED:
            return self._r([self._prompt(state)])
        self._restore(state)
        return self._r([self._info("resume", state), self._prompt(state)])

    def _restore(self, state: SessionState) -> None:
        state.phase = state.resume_phase or Phase.INTERVIEW
        state.resume_phase = None
        state.distress_cooldown = self.guide.settings.distress_cooldown

    def _finish(self, state: SessionState, key: str) -> StepResult:
        state.phase = Phase.ENDED
        text = self.guide.text(key, state.session_code, resources_tag="counseling")
        return self._r([BotMessage(text=text, kind="closing")])

    # ------------------------------------------------------------------ Sonderfälle

    def _crisis(self, state: SessionState) -> StepResult:
        if state.phase not in (Phase.CRISIS, Phase.PAUSED):
            state.resume_phase = state.phase
        state.phase = Phase.CRISIS
        state.escalated = True
        msg = BotMessage(text=self.guide.text("crisis_text", state.session_code, "crisis"), kind="crisis")
        return StepResult(messages=[msg], escalation="crisis")

    def _crisis_followup(self, state: SessionState, text: str) -> StepResult:
        control = parse_control(text, 8)
        if control == "end":
            return self._finish(state, "ended_by_user")
        if control == "pause":
            return self._pause(state)
        if control == "continue":
            self._restore(state)
            return self._r([self._info("resume", state), self._prompt(state)])
        return self._r([BotMessage(text=self.guide.text("crisis_unclear", state.session_code, "crisis"),
                                   kind="crisis")])

    def _distress(self, state: SessionState) -> StepResult:
        state.resume_phase = state.phase
        state.phase = Phase.DISTRESS
        return self._r([self._info("distress", state)])

    def _boundary(self, state: SessionState, name: str) -> StepResult:
        key = name
        if name == "manipulation":
            state.manipulation_strikes += 1
            if state.manipulation_strikes >= 2:
                key = "manipulation_second"
        msgs = [BotMessage(text=self.guide.boundary(key, state.session_code), kind="boundary")]
        if name in _REPROMPT_AFTER and key != "manipulation_second":
            msgs.append(self._prompt(state, back=True))
        return self._r(msgs)

    # ------------------------------------------------------------------ Nachfragen

    def _current(self, state: SessionState) -> tuple[Block, Question]:
        block = self.guide.blocks[state.block_idx]
        return block, block.questions[state.q_idx]

    def _next_followup(self, state: SessionState, block: Block, question: Question, answer: str) -> str | None:
        scripted_pool = self._scripted_pool(block, question)
        ctx = FollowupContext(
            block_title=block.title, question_text=question.text, answer=answer,
            sensitive=block.sensitive, followups_used=state.followups_used,
            max_followups=self.guide.settings.max_followups, scripted=scripted_pool,
            recent=list(state.recent),
        )
        try:
            res = self.llm.followup(ctx)
        except Exception as exc:  # Ausfall oder Zeitüberschreitung: Leitfaden übernimmt
            log.warning("Modell-Nachfrage fehlgeschlagen (%s), nutze Leitfaden", type(exc).__name__)
            res = None
        if res is not None:
            if res.covered:
                return None
            if res.message:
                violations = check_output(res.message, allow_discrimination_terms=block.sensitive)
                if not violations:
                    return res.message
                state.guardrail_hits += 1
                log.warning("Modellausgabe verworfen: %s", violations)
        idx = state.followups_used
        return scripted_pool[idx] if idx < len(scripted_pool) else None

    def _scripted_pool(self, block: Block, question: Question) -> list[str]:
        if question.followups is not None:
            return question.followups
        if block.followups is not None:
            return block.followups
        return self.guide.default_followups

    def _ack(self, state: SessionState, n_words: int) -> list[BotMessage]:
        acks = self.guide.acknowledgments
        if n_words < self.guide.settings.ack_min_words or not acks:
            return []
        text = acks[state.acks_given % len(acks)]
        state.acks_given += 1
        return [BotMessage(text=text, kind="info")]

    # ------------------------------------------------------------------ Hilfsfunktionen

    def _question_msg(self, state: SessionState) -> BotMessage:
        block, question = self._current(state)
        return BotMessage(text=question.text, kind="question", block_id=block.id, question_id=question.id)

    def _info(self, key: str, state: SessionState, kind: str = "info") -> BotMessage:
        return BotMessage(text=self.guide.text(key, state.session_code, "counseling"), kind=kind)

    def _prompt(self, state: SessionState, back: bool = False) -> BotMessage:
        """Die zur aktuellen Phase passende Aufforderung."""
        phase = state.phase
        if phase == Phase.CONSENT:
            return self._info("consent_question", state)
        if phase == Phase.INTERVIEW:
            msg = self._question_msg(state)
            if back:
                msg.text = f"{self.guide.text('back_to_question')} {msg.text}"
            return msg
        if phase == Phase.BLOCK_WARNING:
            block = self.guide.blocks[state.block_idx]
            return BotMessage(text=block.warning or "", kind="warning", block_id=block.id)
        if phase == Phase.WELLBEING:
            return self._info("wellbeing", state)
        if phase == Phase.DISTRESS:
            return self._info("distress", state)
        if phase == Phase.PAUSED:
            return self._info("pause", state)
        if phase == Phase.CRISIS:
            return BotMessage(text=self.guide.text("crisis_unclear", state.session_code, "crisis"), kind="crisis")
        return self._info("already_ended", state)

    @staticmethod
    def _r(messages: list[BotMessage]) -> StepResult:
        return StepResult(messages=messages)

    @staticmethod
    def _remember(state: SessionState, turn: Turn) -> None:
        state.recent.append(turn)
        del state.recent[:-10]

    def _remember_bot(self, state: SessionState, messages: list[BotMessage]) -> None:
        for m in messages:
            self._remember(state, Turn(role="bot", text=m.text, block_id=m.block_id,
                                       question_id=m.question_id, kind=m.kind))
