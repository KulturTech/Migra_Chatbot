"""Prüft die Anbindung an OpenAI-kompatible APIs gegen einen lokalen Fake-Server (kein Netzwerk nötig)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("openai")

from interviewbot.engine import Engine  # noqa: E402
from interviewbot.llm import FollowupContext, OpenAICompatLLM  # noqa: E402

from .conftest import LONG, goto_block  # noqa: E402


class _Fake(BaseHTTPRequestHandler):
    config: dict = {}
    seen: list[dict] = []

    def log_message(self, *args):  # still
        pass

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(body)
        cfg = type(self).config
        if cfg.get("reject_response_format") and "response_format" in body:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": {"message": "response_format not supported"}}')
            return
        system = body["messages"][0]["content"]
        content = cfg["classify"] if "Klassifikator" in system else cfg["followup"]
        payload = {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                   "choices": [{"index": 0, "finish_reason": "stop",
                                "message": {"role": "assistant", "content": content}}]}
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    _Fake.config = {"classify": '{"level": "none"}',
                    "followup": '{"message": "Wie war das für Sie?", "covered": false}'}
    _Fake.seen = []
    httpd = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/v1"
    httpd.shutdown()


def _llm(url: str) -> OpenAICompatLLM:
    return OpenAICompatLLM(base_url=url, api_key="test", model="fake-model",
                           system_prompt="Du bist ein Interviewer.", timeout=5)


def _ctx(**kw) -> FollowupContext:
    base = dict(block_title="Bürokratie", question_text="Erzählen Sie von einem Behördengang.",
                answer=LONG, sensitive=False, followups_used=0, max_followups=2, scripted=[], recent=[])
    base.update(kw)
    return FollowupContext(**base)


def test_followup_parses_json(server):
    res = _llm(server).followup(_ctx())
    assert res.message == "Wie war das für Sie?" and res.covered is False
    sent = _Fake.seen[-1]
    assert sent["model"] == "fake-model" and sent["messages"][0]["role"] == "system"
    assert LONG in sent["messages"][-1]["content"]


def test_followup_accepts_json_inside_text(server):
    _Fake.config["followup"] = 'Hier ist meine Antwort: {"message": "Was ist dann passiert?", "covered": false} Danke'
    assert _llm(server).followup(_ctx()).message == "Was ist dann passiert?"


def test_followup_garbage_returns_none(server):
    _Fake.config["followup"] = "Das ist kein JSON"
    assert _llm(server).followup(_ctx()) is None


def test_falls_back_when_response_format_unsupported(server):
    _Fake.config["reject_response_format"] = True
    res = _llm(server).followup(_ctx())
    assert res.message == "Wie war das für Sie?"
    assert sum("response_format" in b for b in _Fake.seen) == 1 and len(_Fake.seen) == 2


def test_classify(server):
    _Fake.config["classify"] = '{"level": "crisis"}'
    assert _llm(server).classify("irgendein Text") == "crisis"
    _Fake.config["classify"] = '{"level": "unsinn"}'
    assert _llm(server).classify("irgendein Text") is None


def test_engine_with_real_client_uses_model_followup_and_guardrails(server, guide, state):
    eng = Engine(guide, _llm(server))
    goto_block(eng, state, "buerokratie", guide)
    res = eng.step(state, text=LONG)
    assert res.messages[-1].text == "Wie war das für Sie?"

    state.guardrail_hits = 0
    _Fake.config["followup"] = '{"message": "Das war klar rechtswidrig. Was nun?", "covered": false}'
    res = eng.step(state, text=LONG)
    assert state.guardrail_hits == 1 and "rechtswidrig" not in res.messages[-1].text


def test_engine_crisis_via_model_classifier(server, guide, state):
    _Fake.config["classify"] = '{"level": "crisis"}'
    eng = Engine(guide, _llm(server))
    eng.start(state)
    eng.step(state, text="Ja")
    res = eng.step(state, text="Artık yaşamak istemiyorum, çok yoruldum")
    assert res.escalation == "crisis"


def test_unreachable_server_falls_back_to_guide(guide, state):
    llm = OpenAICompatLLM(base_url="http://127.0.0.1:9/v1", api_key="x", model="m", system_prompt="s", timeout=1)
    eng = Engine(guide, llm)
    goto_block(eng, state, "buerokratie", guide)
    res = eng.step(state, text=LONG)
    assert res.messages[-1].text == guide.blocks[1].followups[0]
