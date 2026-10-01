"""SQLite persistence: events, suggestions, savings and chat (docs/05-savi-ia.md, "Datos")."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    entity_id TEXT NOT NULL,
    old_state TEXT,
    new_state TEXT,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    synthetic INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts);
CREATE INDEX IF NOT EXISTS events_entity_ts ON events (entity_id, ts);

CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY,
    detector TEXT NOT NULL,
    dedup_key TEXT NOT NULL,
    title TEXT NOT NULL,
    entities_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    est_kwh_month REAL,
    est_cop_month REAL,
    confidence TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'nueva',
    automation_id TEXT,
    explanation TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    decided_at REAL,
    decided_via TEXT
);
CREATE INDEX IF NOT EXISTS suggestions_key ON suggestions (dedup_key);

CREATE TABLE IF NOT EXISTS savings (
    id INTEGER PRIMARY KEY,
    suggestion_id INTEGER,
    started_at REAL NOT NULL,
    ended_at REAL,
    devices_json TEXT NOT NULL DEFAULT '[]',
    power_w REAL,
    hours REAL,
    kwh REAL,
    cop REAL,
    status TEXT NOT NULL DEFAULT 'en_curso'
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Event:
    ts: float
    entity_id: str
    old_state: str | None
    new_state: str | None
    attributes: dict[str, Any] | None = None
    synthetic: bool = False


class Store:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- events -------------------------------------------------------

    def add_events(self, events: Iterable[Event]) -> int:
        rows = [
            (
                e.ts,
                e.entity_id,
                e.old_state,
                e.new_state,
                json.dumps(e.attributes or {}, ensure_ascii=False),
                1 if e.synthetic else 0,
            )
            for e in events
        ]
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO events (ts, entity_id, old_state, new_state, attributes_json,"
                " synthetic) VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def events(self, until: float | None = None, entity_id: str | None = None) -> list[Event]:
        sql = "SELECT * FROM events WHERE 1=1"
        args: list[Any] = []
        if until is not None:
            sql += " AND ts <= ?"
            args.append(until)
        if entity_id is not None:
            sql += " AND entity_id = ?"
            args.append(entity_id)
        sql += " ORDER BY ts, id"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [
            Event(
                r["ts"],
                r["entity_id"],
                r["old_state"],
                r["new_state"],
                json.loads(r["attributes_json"]),
                bool(r["synthetic"]),
            )
            for r in rows
        ]

    def last_state(self, entity_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT new_state FROM events WHERE entity_id = ? ORDER BY ts DESC, id DESC"
                " LIMIT 1",
                (entity_id,),
            ).fetchone()
        return row["new_state"] if row else None

    def count_events(self, synthetic: bool | None = None) -> int:
        sql, args = "SELECT COUNT(*) FROM events", ()
        if synthetic is not None:
            sql, args = sql + " WHERE synthetic = ?", (1 if synthetic else 0,)
        with self._lock:
            return int(self._conn.execute(sql, args).fetchone()[0])

    def delete_synthetic_events(self) -> int:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM events WHERE synthetic = 1").rowcount

    # ---- suggestions --------------------------------------------------

    def latest_suggestion(self, dedup_key: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM suggestions WHERE dedup_key = ? ORDER BY id DESC LIMIT 1",
                (dedup_key,),
            ).fetchone()
        return _suggestion(row) if row else None

    def insert_suggestion(self, data: dict, now: float) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO suggestions (detector, dedup_key, title, entities_json,"
                " evidence_json, est_kwh_month, est_cop_month, confidence, status, explanation,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'nueva', ?, ?, ?)",
                (
                    data["detector"],
                    data["dedup_key"],
                    data["title"],
                    json.dumps(data["entities"], ensure_ascii=False),
                    json.dumps(data["evidence"], ensure_ascii=False),
                    data["est_kwh_month"],
                    data["est_cop_month"],
                    data["confidence"],
                    data["explanation"],
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def update_suggestion_findings(self, suggestion_id: int, data: dict, now: float) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE suggestions SET title = ?, evidence_json = ?, est_kwh_month = ?,"
                " est_cop_month = ?, confidence = ?, explanation = ?, updated_at = ?"
                " WHERE id = ?",
                (
                    data["title"],
                    json.dumps(data["evidence"], ensure_ascii=False),
                    data["est_kwh_month"],
                    data["est_cop_month"],
                    data["confidence"],
                    data["explanation"],
                    now,
                    suggestion_id,
                ),
            )

    def set_suggestion_status(
        self, suggestion_id: int, status: str, now: float, via: str | None = None
    ) -> None:
        """Status change that is a human decision: stamps decided_at and decided_via."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE suggestions SET status = ?, decided_at = ?, decided_via = ?,"
                " updated_at = ? WHERE id = ?",
                (status, now, via, now, suggestion_id),
            )

    def get_suggestion(self, suggestion_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
            ).fetchone()
        return _suggestion(row) if row else None

    def suggestions(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM suggestions ORDER BY id").fetchall()
        return [_suggestion(r) for r in rows]

    def delete_suggestions(self) -> int:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM suggestions").rowcount

    def set_status(self, suggestion_id: int, status: str, now: float) -> None:
        """Status change that is not a human decision (e.g. `notificada`)."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE suggestions SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, suggestion_id),
            )

    def set_automation_id(self, suggestion_id: int, entity_id: str | None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE suggestions SET automation_id = ? WHERE id = ?", (entity_id, suggestion_id)
            )

    def suggestion_by_automation(self, entity_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM suggestions WHERE automation_id = ? ORDER BY id DESC LIMIT 1",
                (entity_id,),
            ).fetchone()
        return _suggestion(row) if row else None

    # ---- savings ------------------------------------------------------

    def open_saving(
        self, suggestion_id: int, started_at: float, devices: list[dict], power_w: float
    ) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO savings (suggestion_id, started_at, devices_json, power_w, status)"
                " VALUES (?, ?, ?, ?, 'en_curso')",
                (suggestion_id, started_at, json.dumps(devices, ensure_ascii=False), power_w),
            )
            return int(cur.lastrowid)

    def close_saving(
        self, saving_id: int, ended_at: float, hours: float, kwh: float, cop: float | None
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE savings SET ended_at = ?, hours = ?, kwh = ?, cop = ?, status = 'cerrado'"
                " WHERE id = ?",
                (ended_at, hours, kwh, cop, saving_id),
            )

    def savings(self, status: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM savings", ()
        if status is not None:
            sql, args = sql + " WHERE status = ?", (status,)
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY id", args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["devices"] = json.loads(d.pop("devices_json"))
            out.append(d)
        return out

    def get_saving(self, saving_id: int) -> dict | None:
        return next((s for s in self.savings() if s["id"] == saving_id), None)

    def delete_savings(self) -> int:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM savings").rowcount


def _suggestion(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["entities"] = json.loads(d.pop("entities_json"))
    d["evidence"] = json.loads(d.pop("evidence_json"))
    return d
