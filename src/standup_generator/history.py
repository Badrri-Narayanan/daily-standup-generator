"""Local SQLite history of generated prompts and the AI's final standups."""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import GenerationResult

SCHEMA_VERSION = 1
PREVIEW_CHARS = 80

_SCHEMA = """
CREATE TABLE IF NOT EXISTS generations (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    plans TEXT NOT NULL DEFAULT '',
    blockers TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL,
    source_errors TEXT NOT NULL DEFAULT '{}',
    collected TEXT NOT NULL DEFAULT '{}',
    final_standup TEXT NULL
)
"""


@dataclass
class HistorySummary:
    id: int
    created_at: str
    window_start: str
    window_end: str
    has_final: bool
    preview: str


@dataclass
class HistoryEntry:
    id: int
    created_at: str
    updated_at: str
    window_start: str
    window_end: str
    plans: str
    blockers: str
    prompt: str
    source_errors: dict[str, list[str]]
    collected: dict[str, Any]
    final_standup: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _first_line(text: str | None) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:PREVIEW_CHARS]
    return ""


class HistoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version < 1:
                conn.execute(_SCHEMA)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def add(self, result: GenerationResult, plans: str, blockers: str) -> int:
        b = result.bundle
        now = _now()
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO generations (created_at, updated_at, window_start, window_end, plans, blockers,"
                " prompt, source_errors, collected) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (now, now, b.window.start.isoformat(), b.window.end.isoformat(), plans or "", blockers or "",
                 result.prompt, json.dumps(b.source_errors),
                 json.dumps(dataclasses.asdict(b), default=str)),
            )
            return int(cur.lastrowid)

    def list(self, limit: int = 50) -> list[HistorySummary]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, created_at, window_start, window_end, plans, final_standup"
                " FROM generations ORDER BY id DESC LIMIT ?", (limit,),
            ).fetchall()
        return [
            HistorySummary(
                id=r["id"], created_at=r["created_at"], window_start=r["window_start"],
                window_end=r["window_end"], has_final=bool(r["final_standup"]),
                preview=_first_line(r["final_standup"]) or _first_line(r["plans"]),
            )
            for r in rows
        ]

    def get(self, id: int) -> HistoryEntry | None:
        with closing(self._connect()) as conn:
            r = conn.execute("SELECT * FROM generations WHERE id = ?", (id,)).fetchone()
        if r is None:
            return None
        data = dict(r)
        data["source_errors"] = json.loads(data["source_errors"])
        data["collected"] = json.loads(data["collected"])
        return HistoryEntry(**data)

    def set_final(self, id: int, text: str) -> bool:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "UPDATE generations SET final_standup = ?, updated_at = ? WHERE id = ?", (text, _now(), id)
            )
            return cur.rowcount > 0

    def delete(self, id: int) -> bool:
        with closing(self._connect()) as conn, conn:
            return conn.execute("DELETE FROM generations WHERE id = ?", (id,)).rowcount > 0
