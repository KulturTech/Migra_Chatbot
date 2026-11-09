"""Speicher (SQLite für das Gerüst).

Datensparsamkeit: keine IP-Adressen, keine Namen. Gespräche hängen nur an einem zufälligen
Pseudonym-Code. Für die Erhebung sollte dieselbe Schnittstelle auf PostgreSQL mit verschlüsseltem
Datenträger umgestellt werden (siehe README).
"""

from __future__ import annotations

import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .state import SessionState

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    code TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL REFERENCES sessions(code) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    role TEXT NOT NULL,
    kind TEXT NOT NULL,
    block_id TEXT,
    question_id TEXT,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_code ON turns(code);
-- Hinweise an das Team: bewusst ohne Inhalte
CREATE TABLE IF NOT EXISTS escalations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    ts TEXT NOT NULL,
    level TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._memory_conn: sqlite3.Connection | None = None
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        if self.path == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_conn.row_factory = sqlite3.Row
                self._memory_conn.execute("PRAGMA foreign_keys = ON")
            conn = self._memory_conn
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # --- Sitzungen ---------------------------------------------------------------

    def new_code(self) -> str:
        with self._conn() as c:
            while True:
                code = secrets.token_hex(4).upper()  # 8 Zeichen, z. B. "9F3A7C21"
                if not c.execute("SELECT 1 FROM sessions WHERE code = ?", (code,)).fetchone():
                    return code

    def create_session(self, state: SessionState) -> None:
        now = _now()
        with self._conn() as c:
            c.execute("INSERT INTO sessions (code, created_at, updated_at, state_json) VALUES (?,?,?,?)",
                      (state.session_code, now, now, state.model_dump_json()))

    def load_state(self, code: str) -> SessionState | None:
        with self._conn() as c:
            row = c.execute("SELECT state_json FROM sessions WHERE code = ?", (code,)).fetchone()
        return SessionState.model_validate_json(row["state_json"]) if row else None

    def save_state(self, state: SessionState) -> None:
        with self._conn() as c:
            c.execute("UPDATE sessions SET state_json = ?, updated_at = ? WHERE code = ?",
                      (state.model_dump_json(), _now(), state.session_code))

    def delete_session(self, code: str) -> bool:
        """Löscht Sitzung und alle Turns. Hinweise an das Team enthalten keine Inhalte und bleiben."""
        with self._conn() as c:
            c.execute("DELETE FROM turns WHERE code = ?", (code,))
            cur = c.execute("DELETE FROM sessions WHERE code = ?", (code,))
            return cur.rowcount > 0

    def purge_older_than(self, days: int) -> int:
        """Aufbewahrungsfrist: löscht Sitzungen, die seit `days` Tagen nicht aktualisiert wurden."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self._conn() as c:
            codes = [r["code"] for r in c.execute("SELECT code FROM sessions WHERE updated_at < ?", (cutoff,))]
            for code in codes:
                c.execute("DELETE FROM turns WHERE code = ?", (code,))
                c.execute("DELETE FROM sessions WHERE code = ?", (code,))
        return len(codes)

    # --- Protokoll ----------------------------------------------------------------

    def add_turn(self, code: str, role: str, text: str, kind: str = "message",
                 block_id: str | None = None, question_id: str | None = None) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO turns (code, ts, role, kind, block_id, question_id, text) VALUES (?,?,?,?,?,?,?)",
                      (code, _now(), role, kind, block_id, question_id, text))

    def turns(self, code: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT ts, role, kind, block_id, question_id, text FROM turns "
                             "WHERE code = ? ORDER BY id", (code,)).fetchall()
        return [dict(r) for r in rows]

    # --- Hinweise an das Team ---------------------------------------------------------

    def log_escalation(self, code: str, level: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO escalations (code, ts, level) VALUES (?,?,?)", (code, _now(), level))

    def escalations(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT code, ts, level FROM escalations ORDER BY id")]
