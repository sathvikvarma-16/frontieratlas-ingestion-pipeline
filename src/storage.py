"""Minimal append-only JSONL storage for reproducible local pipeline runs."""

import json
from pathlib import Path
from typing import Any


def append_records(path: str | Path, records: list[Any]) -> int:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as output:
        for record in records:
            payload = record.model_dump(mode="json") if hasattr(record, "model_dump") else record
            output.write(json.dumps(payload, ensure_ascii=True) + "\n")
    return len(records)