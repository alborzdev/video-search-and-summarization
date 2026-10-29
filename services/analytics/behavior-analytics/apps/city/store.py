# SPDX-License-Identifier: Apache-2.0
"""SQLite durability for configuration and transition records, separate from animation."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class CityStore:
    def __init__(self, path: str = ":memory:", max_events: int = 50000, max_history_frames: int = 18000, max_history_bytes: int = 256 * 1024 * 1024):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
              id TEXT PRIMARY KEY, source_time_ns TEXT NOT NULL, updated_at INTEGER NOT NULL,
              value TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_updated ON events(updated_at);
            CREATE INDEX IF NOT EXISTS events_site_updated
              ON events(json_extract(value,'$.siteId'),updated_at DESC);
            CREATE TABLE IF NOT EXISTS history (
              id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
              session TEXT NOT NULL, media_time REAL NOT NULL, bytes INTEGER NOT NULL,
              value TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS history_media ON history(source,session,media_time);
            CREATE INDEX IF NOT EXISTS history_source_id ON history(source,id DESC);
        """)
        self.max_events = max_events
        self.max_history_frames = max_history_frames
        self.max_history_bytes = max_history_bytes
        self._history_writes = 0
        self._history_bytes = self.connection.execute("SELECT COALESCE(SUM(bytes),0) FROM history").fetchone()[0]

    def get(self, key: str, default=None):
        row = self.connection.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key: str, value):
        with self.connection:
            self.connection.execute("INSERT INTO config(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value, allow_nan=False)))

    def save_event(self, event: dict):
        timestamp = int(event.get("updatedAtNs", event["triggeredAtNs"]))
        with self.connection:
            self.connection.execute("INSERT INTO events(id,source_time_ns,updated_at,value) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,value=excluded.value", (event["id"], event["triggeredAtNs"], timestamp, json.dumps(event, allow_nan=False)))
            self.connection.execute("DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY updated_at DESC LIMIT -1 OFFSET ?)", (self.max_events,))

    def events(self, limit: int = 1000, site_id: str | None = None, *, source_id: str | None = None, rule_id: str | None = None, state: str | None = None) -> list[dict]:
        count = min(max(limit, 1), self.max_events)
        conditions = []
        parameters = []
        for field, value in (("siteId", site_id), ("sourceId", source_id), ("ruleId", rule_id), ("state", state)):
            if value is not None:
                conditions.append(f"json_extract(value,'$.{field}')=?")
                parameters.append(value)
        query = "SELECT value FROM events"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        rows = self.connection.execute(query + " ORDER BY updated_at DESC LIMIT ?", [*parameters, count])
        return [json.loads(row[0]) for row in rows]

    def save_history(self, source: str, session: str, sample: dict):
        encoded = json.dumps(sample, allow_nan=False, separators=(",", ":"))
        size = len(encoded.encode())
        with self.connection:
            self.connection.execute("INSERT INTO history(source,session,media_time,bytes,value) VALUES (?,?,?,?,?)", (source, session, sample["mediaTimeSeconds"], size, encoded))
            self._history_bytes += size
            self._history_writes += 1
            # Bound both row count and serialized bytes, including older sessions.
            if self._history_writes % 32 == 0 or self._history_bytes > self.max_history_bytes:
                # Every source must participate even when interleaved arrivals
                # put the same camera on each global maintenance boundary.
                sources = self.connection.execute("SELECT source FROM history GROUP BY source HAVING COUNT(*)>?", (self.max_history_frames,)).fetchall()
                for (retained_source,) in sources:
                    rows = self.connection.execute("SELECT id,bytes FROM history WHERE source=? ORDER BY id DESC LIMIT -1 OFFSET ?", (retained_source, self.max_history_frames)).fetchall()
                    self.connection.executemany("DELETE FROM history WHERE id=?", ((row[0],) for row in rows))
                    self._history_bytes -= sum(row[1] for row in rows)
                while self._history_bytes > self.max_history_bytes:
                    rows = self.connection.execute("SELECT id,bytes FROM history ORDER BY id LIMIT 32").fetchall()
                    if not rows:
                        break
                    self.connection.executemany("DELETE FROM history WHERE id=?", ((row[0],) for row in rows))
                    self._history_bytes -= sum(row[1] for row in rows)

    def nearest_history(self, source: str, media_time: float, session: str | None = None):
        if session is None:
            latest = self.connection.execute("SELECT session FROM history WHERE source=? ORDER BY id DESC LIMIT 1", (source,)).fetchone()
            if latest is None:
                return None
            session = latest[0]
        before = self.connection.execute("SELECT media_time,value FROM history WHERE source=? AND session=? AND media_time<=? ORDER BY media_time DESC LIMIT 1", (source, session, media_time)).fetchone()
        after = self.connection.execute("SELECT media_time,value FROM history WHERE source=? AND session=? AND media_time>=? ORDER BY media_time LIMIT 1", (source, session, media_time)).fetchone()
        candidates = [row for row in (before, after) if row]
        nearest = min(candidates, key=lambda row: abs(row[0] - media_time), default=None)
        return json.loads(nearest[1]) if nearest else None

    def clear_history(self):
        with self.connection:
            self.connection.execute("DELETE FROM history")
        self._history_bytes = 0

    def close(self):
        self.connection.close()
