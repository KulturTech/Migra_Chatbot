"""Hinweis an das Team bei Krisen. Enthält nur Code, Stufe und Zeit, nie Gesprächsinhalte."""

from __future__ import annotations

import json
import logging
import threading
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def notify_team(webhook_url: str, code: str, level: str) -> None:
    """Immer ins Log, zusätzlich per Webhook, falls konfiguriert (läuft im Hintergrund, schlägt leise fehl)."""
    log.warning("ESKALATION %s für Sitzung %s", level, code)
    if not webhook_url:
        return
    payload = json.dumps({
        "event": "interview_escalation",
        "level": level,
        "session_code": code,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }).encode("utf-8")

    def _send() -> None:
        try:
            req = urllib.request.Request(webhook_url, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).close()  # noqa: S310 (URL kommt aus der Server-Konfiguration)
        except Exception as exc:  # noqa: BLE001
            log.error("Webhook für Eskalation fehlgeschlagen: %s", type(exc).__name__)

    threading.Thread(target=_send, daemon=True).start()
