"""Build a clean, reproducible submission JSONL from configured sources."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.scrapers.news_jobs import collect_typed
from src.scrapers.startups import collect, collect_products


def _urls(name: str) -> list[str]:
    return [value.strip() for value in os.getenv(name, "").split(",") if value.strip()]


def _payload(record: Any) -> dict[str, Any]:
    return record.model_dump(mode="json") if hasattr(record, "model_dump") else record


async def refresh(output: str, papers_path: str | None = None) -> int:
    startup_records = await collect(_urls("STARTUP_SOURCE_URLS"), entity_type="startup")
    product_records = await collect_products(_urls("PRODUCT_SOURCE_URLS"))
    job_records = await collect_typed(_urls("JOB_FEED_URLS"), record_type="job")
    news_records = await collect_typed(_urls("NEWS_FEED_URLS"), record_type="news")
    records = [_payload(record) for record in startup_records + product_records + job_records + news_records]

    if papers_path:
        with Path(papers_path).open(encoding="utf-8") as source:
            records.extend(json.loads(line) for line in source if line.strip())

    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as target:
        for record in records:
            target.write(json.dumps(record, ensure_ascii=True) + "\n")
    print(f"Wrote {len(records)} records to {destination}")
    return len(records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh clean submission data from configured sources")
    parser.add_argument("--output", default="data/submission_records.jsonl")
    parser.add_argument("--papers", default="data/papers.jsonl", help="Existing paper JSONL to include; use an empty value to omit")
    arguments = parser.parse_args()
    load_dotenv()
    asyncio.run(refresh(arguments.output, arguments.papers or None))
