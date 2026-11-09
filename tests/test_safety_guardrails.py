from __future__ import annotations

import pytest

from interviewbot import safety
from interviewbot.guardrails import check_output

from .conftest import FakeLLM


@pytest.mark.parametrize("text", [
    "Ich will nicht mehr leben", "Ich denke an Suizid", "Manchmal will ich sterben",
    "Er schlägt mich jeden Tag", "I want to die", "intihar etmeyi düşünüyorum",
])
def test_crisis_keywords(text):
    assert safety.keyword_level(text) == "crisis"


@pytest.mark.parametrize("text", [
    "Ich kann nicht mehr darüber sprechen", "Es ist alles zu viel", "Ich bekomme Panik beim Gedanken daran",
])
def test_distress_keywords(text):
    assert safety.keyword_level(text) == "distress"


@pytest.mark.parametrize("text", [
    "Ich war beim Jobcenter und habe lange gewartet", "Das Amt hat zu viele Formulare",
    "Am Ende war alles in Ordnung",
])
def test_neutral_texts(text):
    assert safety.keyword_level(text) == "none"


def test_classifier_can_raise_but_never_lower():
    assert safety.assess("Ich will nicht mehr leben", FakeLLM(level="none")) == "crisis"
    assert safety.assess("Neutraler Satz über Formulare", FakeLLM(level="crisis")) == "crisis"
    assert safety.assess("Neutraler Satz über Formulare", FakeLLM(level="distress")) == "distress"


def test_classifier_failure_falls_back_to_keywords():
    class Broken:
        def classify(self, text):
            raise RuntimeError("API down")

    assert safety.assess("Ich kann nicht mehr", Broken()) == "distress"
    assert safety.assess("Alles gut", Broken()) == "none"


@pytest.mark.parametrize("text,rule", [
    ("Das war eindeutig Diskriminierung. Wie ging es weiter?", "evaluates"),
    ("Das tut mir persönlich leid. Was ist dann passiert?", "simulated_feelings"),
    ("Ich bin ein Mensch aus dem Forschungsteam.", "claims_human"),
    ("Sie sollten klagen. Was meinen Sie?", "legal_advice"),
    ("Rufen Sie 0800 1234567 an.", "contact_data"),
    ("Mehr unter https://example.org", "contact_data"),
    ("Wer war dabei? Wie lange hat es gedauert?", "multiple_questions"),
    ("", "empty"),
])
def test_guardrails_reject(text, rule):
    assert rule in check_output(text, allow_discrimination_terms=True)


def test_guardrails_accept_good_followups():
    assert check_output("Können Sie ein Beispiel nennen?") == []
    assert check_output("Was ist dann passiert?") == []


def test_term_introduction_only_allowed_in_sensitive_block():
    text = "Haben Sie dort Diskriminierung erlebt?"
    assert "introduces_term" in check_output(text, allow_discrimination_terms=False)
    assert check_output(text, allow_discrimination_terms=True) == []
