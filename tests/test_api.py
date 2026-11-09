from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from interviewbot.config import Settings
from interviewbot.main import create_app

from .conftest import ROOT


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        env="dev", llm_provider="mock",
        guide_path=ROOT / "config" / "guide_de.yaml",
        system_prompt_path=ROOT / "prompts" / "system_prompt_de.md",
        db_path=tmp_path / "test.sqlite3", static_dir=ROOT / "static",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        c.app_state = app.state
        yield c


def _start(client):
    r = client.post("/api/sessions")
    assert r.status_code == 200
    return r.json()


def test_health_lists_startup_warnings(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["warnings"]


def test_index_page_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Gespräch" in r.text


def test_session_flow_persists_turns(client):
    data = _start(client)
    code = data["session_code"]
    assert len(code) == 8 and data["phase"] == "consent" and len(data["messages"]) == 2

    r = client.post(f"/api/sessions/{code}/messages", json={"text": "Ja"})
    assert r.status_code == 200 and r.json()["phase"] == "interview"

    turns = client.app_state.store.turns(code)
    roles = [t["role"] for t in turns]
    assert roles.count("user") == 1 and roles.count("bot") >= 4


def test_delete_removes_everything(client):
    code = _start(client)["session_code"]
    client.post(f"/api/sessions/{code}/messages", json={"text": "Ja"})
    assert client.delete(f"/api/sessions/{code}").status_code == 200
    store = client.app_state.store
    assert store.load_state(code) is None and store.turns(code) == []
    assert client.delete(f"/api/sessions/{code}").status_code == 404
    assert client.post(f"/api/sessions/{code}/messages", json={"text": "Hallo"}).status_code == 404


def test_declining_consent_leaves_no_data(client):
    code = _start(client)["session_code"]
    r = client.post(f"/api/sessions/{code}/messages", json={"text": "Nein"}).json()
    assert r["ended"] and r["phase"] == "declined"
    store = client.app_state.store
    assert store.load_state(code) is None and store.turns(code) == []


def test_crisis_logs_escalation_without_content(client):
    code = _start(client)["session_code"]
    client.post(f"/api/sessions/{code}/messages", json={"text": "Ja"})
    r = client.post(f"/api/sessions/{code}/messages", json={"text": "Ich will nicht mehr leben"}).json()
    assert r["phase"] == "crisis" and "112" in r["messages"][0]["text"]
    esc = client.app_state.store.escalations()
    assert esc and set(esc[0]) == {"code", "ts", "level"} and esc[0]["level"] == "crisis"


def test_button_actions(client):
    code = _start(client)["session_code"]
    client.post(f"/api/sessions/{code}/messages", json={"text": "Ja"})
    assert client.post(f"/api/sessions/{code}/messages", json={"action": "pause"}).json()["phase"] == "paused"
    assert client.post(f"/api/sessions/{code}/messages", json={"action": "resume"}).json()["phase"] == "interview"
    r = client.post(f"/api/sessions/{code}/messages", json={"action": "end"}).json()
    assert r["ended"]


def test_input_validation(client):
    code = _start(client)["session_code"]
    assert client.post(f"/api/sessions/{code}/messages", json={"text": "x" * 4001}).status_code == 422
    assert client.post(f"/api/sessions/{code}/messages", json={"action": "hack"}).status_code == 422


def test_help_lists_crisis_and_counseling_contacts(client):
    text = client.get("/api/help").json()["text"]
    assert "112" in text and "Telefonseelsorge" in text and "Antidiskriminierung" in text


def test_production_refuses_to_start_with_placeholders_or_mock(tmp_path):
    settings = Settings(
        env="production", llm_provider="mock",
        guide_path=ROOT / "config" / "guide_de.yaml", db_path=tmp_path / "p.sqlite3",
    )
    with pytest.raises(RuntimeError, match="Platzhalter"):
        create_app(settings)


def test_purge_removes_old_sessions(client):
    store = client.app_state.store
    code = _start(client)["session_code"]
    assert store.purge_older_than(30) == 0
    assert store.purge_older_than(-1) == 1 and store.load_state(code) is None
