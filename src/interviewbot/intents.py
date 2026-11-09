"""Einfache, nachvollziehbare Erkennung von Steuerbefehlen und Grenzfällen.

Alles hier ist bewusst regelbasiert: Das Verhalten ist reproduzierbar und prüfbar.
Die Muster sind ein Startpunkt und müssen mit Muttersprachler*innen und im Pilot erweitert werden.
"""

from __future__ import annotations

import re

_FLAGS = re.IGNORECASE


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _words(text: str) -> int:
    return len(text.split())


# --- Ja / Nein ---------------------------------------------------------------

_YES = re.compile(r"\b(ja|jap|jo|klar|gerne|gern|einverstanden|okay|ok|yes|sure|evet|tamam)\b", _FLAGS)
_NO = re.compile(r"\b(nein|ne|nee|nö|no|nicht einverstanden|hayır|hayir)\b", _FLAGS)


def parse_yes_no(text: str, max_words: int = 8) -> str | None:
    """'yes', 'no' oder None, wenn unklar oder widersprüchlich."""
    t = _norm(text)
    if not t or _words(t) > max_words:
        return None
    yes, no = bool(_YES.search(t)), bool(_NO.search(t))
    if yes == no:
        return None
    return "yes" if yes else "no"


# --- Steuerbefehle -----------------------------------------------------------

_END = re.compile(r"\b(beenden|abbrechen|aufhören|stopp?|ende|schluss)\b|nicht mehr weiter", _FLAGS)
_PAUSE = re.compile(r"\bpause\b|später (weiter|fortsetzen)|kurz warten", _FLAGS)
_SKIP = re.compile(
    r"überspring|\bskip\b|nächste frage|lieber nicht|themenwechsel|anderes thema|"
    r"(möchte|will|mag) (ich )?(da)?(nicht|nix) (darüber |dazu )?(sprechen|reden|antworten)",
    _FLAGS,
)
_CONTINUE = re.compile(r"\b(weiter|fortfahren|fortsetzen|weitermachen|okay|ok|passt|geht schon|gut)\b", _FLAGS)


def parse_control(text: str, max_words: int = 4) -> str | None:
    """'end' | 'pause' | 'skip' | 'continue' | None.

    Nur kurze Nachrichten gelten als Befehl. So wird "am Ende war es schlimm" nicht als
    "Ende" gelesen. Reihenfolge: end > pause > skip > continue.
    """
    t = _norm(text)
    if not t or _words(t) > max_words:
        return None
    if _END.search(t):
        return "end"
    if _PAUSE.search(t):
        return "pause"
    if _SKIP.search(t):
        return "skip"
    if _CONTINUE.search(t):
        return "continue"
    return None


# --- Nicht-Antworten -----------------------------------------------------------

_NON_ANSWER = re.compile(
    r"^(weiß (ich )?nicht|keine ahnung|nichts|k\.?\s?a\.?|will ich nicht sagen|möchte ich nicht sagen)\W*$",
    _FLAGS,
)


def is_non_answer(text: str) -> bool:
    t = _norm(text)
    return bool(t) and _words(t) <= 5 and bool(_NON_ANSWER.match(t))


# --- Grenzfälle (feste Antworten) ----------------------------------------------

_BOUNDARY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Reihenfolge ist wichtig: spezifische Muster vor allgemeinen.
    # Nur Anfrageformen. Erzählungen wie "die Behörde hat meine Daten gelöscht" sollen nicht auslösen.
    ("ask_delete", re.compile(
        r"\blösch\w*\s+(bitte\s+)?(meine|alle|die|sofort)|"
        r"bitte.{0,15}(daten|antworten).{0,15}lösch|"
        r"(möchte|will|wünsche|verlange).{0,30}(daten|antworten).{0,20}lösch|"
        r"wie (kann|muss) ich.{0,30}(daten|antworten).{0,20}lösch", _FLAGS)),
    # Nur als Frage ("Werden meine Antworten an die Ausländerbehörde weitergegeben?"), nicht als Erzählung.
    ("status_fear", re.compile(
        r"\b(werden|wird|kann|können|könnte|könnten)\b"
        r"(?=[^.?!]*\b(antworten|daten|aussagen|angaben|gespräch)\b)"
        r"(?=[^.?!]*(behörde|polizei|ausländeramt))"
        r"(?=[^.?!]*(weitergegeben|weitergeleitet|gemeldet|erfahren|weitergeben|weiterleiten|melden))"
        r"[^.?!]*\?|"
        r"\b(wird|werden|kann|können)\b[^.?!]{0,40}(ausländerbehörde|ausländeramt|polizei|behörde)"
        r"[^.?!]{0,40}(davon|das|es) (erfahren|wissen|mitbekommen)[^.?!]*\?", _FLAGS)),
    ("ask_data", re.compile(
        r"was (passiert|geschieht|machen sie|machst du|macht ihr).{0,30}(daten|antworten|gespräch)|"
        r"(wer|wohin).{0,30}(daten|antworten)|\bdatenschutz|wer (sieht|liest|bekommt)|wie lange.{0,20}gespeichert|"
        r"werden (meine )?(daten|antworten).{0,20}(gespeichert|verwendet|veröffentlicht)", _FLAGS)),
    ("ask_human", re.compile(
        r"(bist|sind)\s+(du|sie)\s+(denn\s+)?(ein(e)?\s+)?(echte[rn]?\s+)?"
        r"(mensch|roboter|bot|ki|maschine|computer|person|künstliche)|"
        r"mit (einem|einer) (menschen|maschine|roboter|ki)|are you (a )?(human|bot|ai|real|robot)", _FLAGS)),
    ("advice_request", re.compile(
        r"kann ich (dagegen )?(klagen|verklagen|anzeigen|widerspruch)|soll ich (klagen|anzeigen|einen anwalt)|"
        r"was soll ich (jetzt |denn )?(tun|machen)|was (kann|muss) ich (jetzt |denn )?(tun|machen)|"
        r"(brauche|bräuchte|soll|sollte) ich (einen |zum )?anwalt|rechtliche (beratung|schritte)|rechtsberatung|"
        r"ist das (legal|rechtens|erlaubt)|"
        r"was raten sie|haben sie (einen )?(rat|tipp)", _FLAGS)),
    ("ask_judgment", re.compile(
        r"war das (diskriminierung|rassismus|rassistisch|diskriminierend)|"
        r"ist das (diskriminierung|rassismus|rassistisch|diskriminierend)|zu empfindlich|übertreib|"
        r"(habe|hab) ich recht|bilde ich mir.{0,15}ein|was denken sie|was denkst du|wie sehen sie das|"
        r"ihre meinung|deine meinung", _FLAGS)),
    ("manipulation", re.compile(
        r"ignorier\w*\s+(alle |deine |ihre |die |bitte )?(regeln|anweisungen)|"
        r"vergiss\w*\s+(alle |deine |die |ihre )?(anweisungen|regeln)|system.?prompt|"
        r"ignore (all |your |previous )?(rules|instructions)|tu so als|jailbreak|entwickler.?modus|"
        r"du bist jetzt\b|spiel(e)? (die )?rolle", _FLAGS)),
    ("abuse", re.compile(
        r"(du|sie|ihr)\s+(bist|sind)?\s*(dumm|blöd|ein idiot|nutzlos)|"
        r"(dumme|blöde[r]?|scheiß)\s+(maschine|ki|bot|roboter)|halt (die )?(klappe|fresse)", _FLAGS)),
]


def detect_boundary(text: str) -> str | None:
    t = _norm(text)
    if not t:
        return None
    for name, pattern in _BOUNDARY_PATTERNS:
        if pattern.search(t):
            return name
    return None
