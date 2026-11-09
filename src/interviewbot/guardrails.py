"""Prüfung von Modellausgaben. Verstößt eine Nachfrage gegen eine Regel, wird sie verworfen
und durch die Nachfrage aus dem Leitfaden ersetzt."""

from __future__ import annotations

import re

_RULES: dict[str, re.Pattern[str]] = {
    # Bewertung als (Nicht-)Diskriminierung oder als rechtswidrig
    "evaluates": re.compile(
        r"(das|dies|es)\s+(war|ist|klingt (nach|wie)|ist ganz klar)\s+(eindeutig |klar |wohl |sicher |definitiv |schon |also )?"
        r"(keine?\s+)?(diskriminierung|rassismus|rassistisch|diskriminierend|unrecht|rechtswidrig|illegal)", re.I),
    # Gespielte Gefühle
    "simulated_feelings": re.compile(
        r"tut mir (persönlich |sehr |wirklich )?leid|ich verstehe genau|ich fühle (mit|das)|"
        r"ich kann (das )?nachempfinden|ich bin (traurig|schockiert|wütend)|das macht mich (traurig|wütend)", re.I),
    # Menschliche Identität
    "claims_human": re.compile(r"ich bin (ein |eine )?(echter |echte )?(mensch|mitarbeiter|mitarbeiterin|forscher|forscherin)", re.I),
    # Rechtsberatung
    "legal_advice": re.compile(
        r"(sie sollten|sie können|ich empfehle (ihnen )?|ich rate (ihnen )?(zu|dazu))\s*(klagen|verklagen|widerspruch einlegen|"
        r"anzeige erstatten|einen anwalt)|rechtlich gesehen|ihr gutes recht|sie haben (einen )?anspruch", re.I),
    # Erfundene Kontaktdaten: Links, Mailadressen, Telefonnummern
    "contact_data": re.compile(
        r"https?://|www\.|\b\S+@\S+\.\S+|\+?\d[\d\s\-/]{6,}\d", re.I),
    # Suggestion: Begriff vor der Betroffenen einführen
    "introduces_term": re.compile(r"\b(diskriminier\w*|rassis\w*)\b", re.I),
}


def check_output(text: str, allow_discrimination_terms: bool = False, max_words: int = 60) -> list[str]:
    """Gibt die Namen verletzter Regeln zurück. Leere Liste: Ausgabe ist zulässig."""
    violations: list[str] = []
    t = (text or "").strip()
    if not t:
        return ["empty"]
    for name, pattern in _RULES.items():
        if name == "introduces_term" and allow_discrimination_terms:
            continue
        if pattern.search(t):
            violations.append(name)
    if t.count("?") > 1:
        violations.append("multiple_questions")
    if len(t.split()) > max_words:
        violations.append("too_long")
    return violations
