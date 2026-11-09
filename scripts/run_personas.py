#!/usr/bin/env python3
"""Spielt skriptierte Personas gegen den Bot und prüft das Verhalten.

Beispiele
  python scripts/run_personas.py                      # Mock-Modell, nur Programmlogik
  python scripts/run_personas.py --repeat 5 --llm env # echtes Modell aus .env, je Persona 5 Läufe
  python scripts/run_personas.py --only P06 P10

Prüfungen (checks) in personas.yaml
  final_phase:               Phase am Ende (String oder Liste)
  escalation:                true/false, ob ein Hinweis ans Team ausgelöst wurde
  bot_says_any(_2, _3...):   mindestens eine der Zeichenketten kommt in den Bot-Nachrichten vor
  bot_never_says:            keine dieser Zeichenketten darf vorkommen
  never_before_block:        {block, words}: Wörter dürfen vor dem ersten Auftreten des Blocks nicht fallen
  max_consecutive_followups: höchstens so viele Nachfragen direkt hintereinander
Exit-Code 1, wenn eine Persona (mit ihrer Schwere) durchfällt und --fail-on greift.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from interviewbot.config import Settings  # noqa: E402
from interviewbot.engine import Engine  # noqa: E402
from interviewbot.guide import load_guide, load_system_prompt  # noqa: E402
from interviewbot.llm import MockLLM, make_llm  # noqa: E402
from interviewbot.state import FINAL_PHASES, Phase, SessionState  # noqa: E402

MAX_TURNS = 250
DEFAULT_FILL = "Ich war letzte Woche beim Amt und habe lange gewartet, dann wurde mein Antrag geprüft."
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2}


def filler(state: SessionState, interview_fill: str) -> str:
    if state.phase in (Phase.CONSENT, Phase.BLOCK_WARNING):
        return "Ja"
    if state.phase in (Phase.WELLBEING, Phase.DISTRESS, Phase.PAUSED, Phase.CRISIS):
        return "Weiter"
    return interview_fill


def run_once(persona: dict, engine: Engine) -> dict:
    state = SessionState(session_code="TEST0001")
    bot: list[dict] = []
    transcript: list[dict] = []
    escalations: list[str] = []

    def take(result) -> None:
        for m in result.messages:
            entry = {"role": "bot", "text": m.text, "kind": m.kind, "block_id": m.block_id}
            bot.append(entry)
            transcript.append(entry)
        if result.escalation:
            escalations.append(result.escalation)

    take(engine.start(state))
    queue = list(persona.get("messages", []))
    then_fill = persona.get("then_fill", True)
    interview_fill = persona.get("fill", DEFAULT_FILL)

    for _ in range(MAX_TURNS):
        if state.phase in FINAL_PHASES:
            break
        if queue:
            text = queue.pop(0)
        elif then_fill:
            text = filler(state, interview_fill)
        else:
            break
        transcript.append({"role": "user", "text": text})
        take(engine.step(state, text=text))

    return {"state": state, "bot": bot, "transcript": transcript, "escalations": escalations}


def evaluate(checks: dict, run: dict) -> list[str]:
    failures: list[str] = []
    state: SessionState = run["state"]
    bot = run["bot"]
    all_text = "\n".join(m["text"] for m in bot).lower()

    expected = checks.get("final_phase")
    if expected is not None:
        allowed = expected if isinstance(expected, list) else [expected]
        if state.phase.value not in allowed:
            failures.append(f"final_phase: erwartet {allowed}, war '{state.phase.value}'")

    if "escalation" in checks and bool(run["escalations"]) != checks["escalation"]:
        failures.append(f"escalation: erwartet {checks['escalation']}, war {bool(run['escalations'])}")

    for key, values in checks.items():
        if key.startswith("bot_says_any") and not any(v.lower() in all_text for v in values):
            failures.append(f"{key}: keine dieser Aussagen gefunden: {values}")

    for word in checks.get("bot_never_says", []):
        if word.lower() in all_text:
            failures.append(f"bot_never_says: '{word}' kommt vor")

    nb = checks.get("never_before_block")
    if nb:
        for m in bot:
            if m.get("block_id") == nb["block"]:
                break
            hits = [w for w in nb["words"] if w.lower() in m["text"].lower()]
            if hits:
                failures.append(f"never_before_block: {hits} vor Block '{nb['block']}': {m['text'][:70]!r}")
                break

    limit = checks.get("max_consecutive_followups")
    if limit is not None:
        run_len = longest = 0
        for m in bot:
            if m["kind"] == "followup":
                run_len += 1
                longest = max(longest, run_len)
            elif m["kind"] != "info":
                run_len = 0
        if longest > limit:
            failures.append(f"max_consecutive_followups: {longest} > {limit}")

    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--personas", default=str(ROOT / "personas" / "personas.yaml"))
    ap.add_argument("--guide", default=str(ROOT / "config" / "guide_de.yaml"))
    ap.add_argument("--llm", choices=["mock", "env"], default="mock")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--fail-on", choices=["any", "critical", "never"], default="any")
    ap.add_argument("--out", default=str(ROOT / "reports"))
    args = ap.parse_args()

    guide = load_guide(args.guide)
    settings = Settings.from_env(ROOT / ".env")
    if args.llm == "env":
        llm = make_llm(settings, load_system_prompt(settings.system_prompt_path))
        llm_name = f"{settings.llm_provider}:{settings.llm_model}"
    else:
        llm, llm_name = MockLLM(), "mock"

    personas = yaml.safe_load(Path(args.personas).read_text(encoding="utf-8"))
    if args.only:
        personas = [p for p in personas if p["id"] in args.only]

    report = {"started": datetime.now().isoformat(timespec="seconds"), "llm": llm_name, "results": []}
    exit_code = 0
    print(f"Modell: {llm_name}   Läufe je Persona: {args.repeat}\n")
    print(f"{'ID':<5}{'Schwere':<10}{'Persona':<34}{'Ergebnis'}")
    print("-" * 70)

    for p in sorted(personas, key=lambda x: (SEVERITY_ORDER.get(x.get("severity", "medium"), 3), x["id"])):
        sev = p.get("severity", "medium")
        if p.get("needs_llm") and llm_name == "mock":
            print(f"{p['id']:<5}{sev:<10}{p['name']:<34}ÜBERSPRUNGEN (braucht echtes Modell, --llm env)")
            report["results"].append({"id": p["id"], "status": "skipped"})
            continue

        failures_per_run, hits = [], 0
        for i in range(args.repeat):
            run = run_once(p, Engine(guide, llm))
            hits += run["state"].guardrail_hits
            failures_per_run.append(evaluate(p.get("checks", {}), run))
            if i == 0:
                first = run["transcript"]

        failed_runs = sum(1 for f in failures_per_run if f)
        status = "OK" if not failed_runs else f"FEHLER in {failed_runs}/{args.repeat} Läufen"
        print(f"{p['id']:<5}{sev:<10}{p['name']:<34}{status}")
        for f in next((f for f in failures_per_run if f), []):
            print(f"{'':<49}- {f}")
        if p.get("manual_review"):
            print(f"{'':<49}Manuell prüfen: {p['manual_review']}")
        if hits:
            print(f"{'':<49}Hinweis: {hits} Modellausgaben durch Guardrails verworfen")

        report["results"].append({
            "id": p["id"], "name": p["name"], "severity": sev,
            "status": "ok" if not failed_runs else "failed", "failed_runs": failed_runs,
            "failures": next((f for f in failures_per_run if f), []),
            "guardrail_hits": hits, "transcript_first_run": first,
        })
        if failed_runs and (args.fail_on == "any" or (args.fail_on == "critical" and sev == "critical")):
            exit_code = 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"personas_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nBericht mit Transkripten: {out}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
