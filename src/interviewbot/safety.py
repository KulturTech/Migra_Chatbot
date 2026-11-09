"""Sicherheitsprüfung jeder Nutzernachricht: Krise, Belastung, sonst nichts.

Zwei Ebenen:
1. Stichwortmuster (immer aktiv, deterministisch, Rückfallebene)
2. Optional ein Modell als Klassifikator (fängt Umschreibungen und andere Sprachen besser)

Das Ergebnis ist immer das Maximum beider Ebenen. Ein Modell kann eine Stichwort-Erkennung
also nie abschwächen. Alle Listen sind Startwerte: mit Fachleuten (Psychologie, Beratung) und
Muttersprachler*innen prüfen und erweitern. Fehlalarme und Lücken sind zu erwarten.
"""

from __future__ import annotations

import re
from typing import Literal, Protocol

Level = Literal["none", "distress", "crisis"]
_RANK = {"none": 0, "distress": 1, "crisis": 2}

_CRISIS = [
    r"suizid", r"selbstmord", r"suicid", r"umbringen", r"nicht mehr leben", r"leben beenden",
    r"(will|möchte|wollte|würde)( ich| nur| einfach| manchmal)* sterben", r"sterben (will|möchte|wollte) ich",
    r"lieber tot", r"mich (töten|ritzen|verletzen)",
    r"mir (etwas |was )?antun", r"kill myself", r"want to die", r"end my life", r"don'?t want to live",
    r"(schlägt|bedroht|misshandelt|vergewaltigt) mich", r"ich werde (bedroht|geschlagen|verfolgt)",
    r"ich bin in gefahr", r"ich fühle mich (nicht )?sicher.{0,10}nicht",
    # Türkisch, Arabisch (Transliteration) und Englisch: Startwerte, bitte prüfen lassen
    r"intihar", r"ölmek istiyorum", r"أريد أن أموت", r"انتحار",
]

_DISTRESS = [
    r"kann nicht mehr", r"hoffnungslos", r"\bpanik", r"todesangst", r"große angst",
    r"(ist|war) (mir )?(alles )?zu viel", r"\bweine\b", r"\bweinen\b", r"zittere",
    r"will nicht (mehr )?darüber (reden|sprechen)", r"überfordert", r"nicht aushalten",
    r"traumatisch", r"albträume", r"schlaflos", r"am ende meiner kräfte",
]

_CRISIS_RE = [re.compile(p, re.IGNORECASE) for p in _CRISIS]
_DISTRESS_RE = [re.compile(p, re.IGNORECASE) for p in _DISTRESS]


class Classifier(Protocol):
    def classify(self, text: str) -> str | None: ...


def keyword_level(text: str) -> Level:
    t = text.strip()
    if any(p.search(t) for p in _CRISIS_RE):
        return "crisis"
    if any(p.search(t) for p in _DISTRESS_RE):
        return "distress"
    return "none"


def assess(text: str, classifier: Classifier | None = None) -> Level:
    level = keyword_level(text)
    if classifier is not None:
        try:
            model_level = classifier.classify(text)
        except Exception:  # Ausfall des Modells darf die Stichwortprüfung nie blockieren
            model_level = None
        if model_level in _RANK and _RANK[model_level] > _RANK[level]:
            level = model_level  # type: ignore[assignment]
    return level
