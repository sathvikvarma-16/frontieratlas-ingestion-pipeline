"""Pipeline demo entry point with safe, network-free defaults."""

import asyncio
import argparse
import os
from dotenv import load_dotenv

from src.database import RecordStore
from src.export.csv_tabs import export_tabs
from src.resolver import EntityResolver
from src.scrapers.news_jobs import JOB_FEED_URLS, collect_typed as collect_signals
from src.scrapers.papers import collect as collect_papers
from src.scrapers.startups import collect as collect_entities, collect_products
from src.storage import write_records


async def run(limit: int = 0, output: str = "data/papers.jsonl") -> None:
    load_dotenv()
    resolution = EntityResolver(["OpenAI", "Anthropic", "DeepMind"]).resolve("OpenAI, Inc.")
    print(f"FrontierAtlas pipeline ready; resolver demo: {resolution.raw_name} -> {resolution.canonical_name}")
    records = []
    if limit > 0:
        records.extend(await collect_papers(max_results=limit))
    for key, entity_type in (("STARTUP_SOURCE_URLS", "startup"), ("PRODUCT_SOURCE_URLS", "product")):
        urls = [url.strip() for url in os.getenv(key, "").split(",") if url.strip()]
        if urls:
            if entity_type == "product":
                records.extend(await collect_products(urls))
            else:
                records.extend(await collect_entities(urls=urls, entity_type=entity_type))
    for key, record_type in (("NEWS_FEED_URLS", "news"), ("JOB_FEED_URLS", "job")):
        feed_urls = [url.strip() for url in os.getenv(key, "").split(",") if url.strip()]
        if feed_urls or record_type == "job":
            feed_urls = feed_urls or JOB_FEED_URLS
            records.extend(await collect_signals(feed_urls, record_type=record_type))
    if not records:
        print("No sources configured; no records were generated")
        return
    write_records(output, records)
    store = RecordStore()
    for record in records:
        payload = record.model_dump(mode="json") if hasattr(record, "model_dump") else record
        store.add(payload.get("recordType", "SIGNAL"), payload.get("source_url", payload.get("url", "")), payload)
    store.close()
    print(f"Collected {len(records)} traceable records into {output}")
    print(f"Spreadsheet tabs: {export_tabs(output)} records exported")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the FrontierAtlas ingestion pipeline")
    parser.add_argument("--papers", type=int, default=0, help="Fetch up to N Arxiv papers")
    parser.add_argument("--output", default="data/records.jsonl", help="JSONL output path")
    args = parser.parse_args()
    asyncio.run(run(args.papers, args.output))