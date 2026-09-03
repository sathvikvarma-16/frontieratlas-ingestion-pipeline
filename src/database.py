"""Small SQLite persistence layer with URL/content idempotency."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


class RecordStore:
    def __init__(self, path: str = "data/frontieratlas.db") -> None:
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS records (record_key TEXT PRIMARY KEY, record_type TEXT NOT NULL, source_url TEXT NOT NULL, payload TEXT NOT NULL, collected_at TEXT NOT NULL)")
        self.connection.commit()

    def add(self, record_type: str, source_url: str, payload: dict[str, Any]) -> bool:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        key = hashlib.sha256(f"{record_type}|{source_url}|{raw}".encode()).hexdigest()
        cursor = self.connection.execute("INSERT OR IGNORE INTO records VALUES (?, ?, ?, ?, ?)", (key, record_type, source_url, raw, datetime.now(timezone.utc).isoformat()))
        self.connection.commit()
        return cursor.rowcount == 1

    def close(self) -> None:
        self.connection.close()