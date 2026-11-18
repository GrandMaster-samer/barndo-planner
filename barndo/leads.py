"""Lead capture: SQLite storage, CSV export and an optional CRM webhook."""
from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import DATA_DIR, LEAD_WEBHOOK_URL

log = logging.getLogger(__name__)
DB_PATH = DATA_DIR / "leads.db"

FIELDS = ["id", "created_at", "name", "email", "phone", "message", "layout_id", "estimate_total", "requirements"]


def _conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, name TEXT, email TEXT, phone TEXT,
        message TEXT, layout_id TEXT, estimate_total REAL, requirements TEXT)""")
    return c


def save_lead(name: str, email: str, phone: str, message: str, layout_id: str, estimate_total: float | None,
              requirements: dict[str, Any]) -> dict[str, Any]:
    row = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "name": name, "email": email, "phone": phone, "message": message,
        "layout_id": layout_id, "estimate_total": estimate_total, "requirements": json.dumps(requirements),
    }
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO leads (created_at,name,email,phone,message,layout_id,estimate_total,requirements) "
            "VALUES (:created_at,:name,:email,:phone,:message,:layout_id,:estimate_total,:requirements)", row)
        row["id"] = cur.lastrowid
    if LEAD_WEBHOOK_URL:
        try:
            payload = dict(row, requirements=requirements)
            httpx.post(LEAD_WEBHOOK_URL, json=payload, timeout=10)
        except httpx.HTTPError as exc:
            log.warning("Lead webhook failed: %s", exc)
    return row


def list_leads() -> list[dict[str, Any]]:
    with _conn() as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM leads ORDER BY id DESC")]


def leads_csv() -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    w.writeheader()
    for r in list_leads():
        w.writerow({k: r.get(k) for k in FIELDS})
    return buf.getvalue()
