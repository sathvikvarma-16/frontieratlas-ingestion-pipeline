"""Export normalized JSONL records into spreadsheet-friendly CSV tabs."""

import csv
import json
from pathlib import Path
from typing import Any


def export_tabs(input_path: str, output_dir: str = "data/tabs") -> int:
    rows: list[dict[str, Any]] = []
    with Path(input_path).open(encoding="utf-8") as source:
        rows = [json.loads(line) for line in source if line.strip()]
    groups = {"STARTUP": "Startups", "PRODUCT": "Products", "RESEARCH_PAPER": "Research Papers", "JOB": "Jobs", "NEWS": "News"}
    count = 0
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    for record_type, filename in groups.items():
        selected = [row for row in rows if row.get("recordType") == record_type]
        if not selected:
            continue
        keys = sorted({key for row in selected for key in row})
        with (destination / f"{filename}.csv").open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=keys)
            writer.writeheader()
            writer.writerows(selected)
        count += len(selected)
    return count