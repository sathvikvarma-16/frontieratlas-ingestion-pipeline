"""Export normalized JSONL records into spreadsheet-friendly CSV tabs."""

import csv
import json
import os
from pathlib import Path
from typing import Any

from src.resolver import EntityResolver


def export_tabs(input_path: str, output_dir: str = "data/tabs") -> int:
    with Path(input_path).open(encoding="utf-8") as source:
        rows = [json.loads(line) for line in source if line.strip()]
    groups = {"STARTUP": "Startups", "PRODUCT": "Products", "RESEARCH_PAPER": "Research Papers", "JOB": "Jobs", "NEWS": "News"}
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
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
    entities = [row for row in rows if row.get("recordType") in {"STARTUP", "PRODUCT"} and row.get("name")]
    if entities:
        seeds = [name.strip() for name in os.getenv("CANONICAL_ENTITIES", "OpenAI,Anthropic,DeepMind").split(",") if name.strip()]
        resolver = EntityResolver(seeds)
        with (destination / "Entity Mapping Log.csv").open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=["record_type", "raw_name", "canonical_name", "score"])
            writer.writeheader()
            for row in entities:
                result = resolver.resolve(row["name"])
                writer.writerow({"record_type": row["recordType"], "raw_name": result.raw_name, "canonical_name": result.canonical_name or "", "score": result.score})
    return count