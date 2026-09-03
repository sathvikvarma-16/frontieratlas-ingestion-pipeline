"""Configurable startup and product directory collector.

Sources must be explicitly supplied by the operator. Records retain their
source URL and are never synthesized when a directory omits a field.
"""

import argparse
import asyncio
import json
from collections.abc import Iterable
from html.parser import HTMLParser
from src.schemas import Product, Source, Startup
from src.storage import append_records

from .base import fetch_many


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title: list[str] = []
        self.description: str | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag == "meta" and attributes.get("name", "").lower() == "description":
            self.description = attributes.get("content")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title.append(data)


def parse_directory_pages(pages: dict[str, str], *, entity_type: str) -> list[Startup | Product]:
    """Create one conservative record per supplied page using public metadata."""
    records: list[Startup | Product] = []
    for url, body in pages.items():
        if body.lstrip().startswith(("{", "[")):
            try:
                entries = json.loads(body)
            except json.JSONDecodeError:
                continue
            if isinstance(entries, dict) and isinstance(entries.get("data"), list):
                entries = entries["data"]
            entries = entries if isinstance(entries, list) else [entries]
            for entry in entries:
                if not isinstance(entry, dict) or not entry.get("name"):
                    continue
                common = {"name": entry["name"], "description": entry.get("description") or entry.get("tagline"), "website": entry.get("website") or entry.get("url")}
                source = Source(name=entry.get("source_name", "configured-directory"), url=url)
                try:
                    records.append(Startup(source=source, **common) if entity_type == "startup" else Product(source=source, company=entry.get("company"), pricing_model=entry.get("pricing_model"), **common))
                except ValueError:
                    continue
            continue
        parser = MetadataParser()
        parser.feed(body)
        name = " ".join("".join(parser.title).split())
        if not name:
            continue
        source = Source(name="configured-directory", url=url)
        try:
            record = Startup(source=source, name=name, description=parser.description) if entity_type == "startup" else Product(source=source, name=name, description=parser.description)
            records.append(record)
        except ValueError:
            continue
    return records


async def collect(urls: Iterable[str], *, entity_type: str = "startup") -> list[Startup | Product]:
    pages = await fetch_many(urls)
    return parse_directory_pages(pages, entity_type=entity_type)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("urls", nargs="+", help="Explicit JSON or HTML directory URLs")
    parser.add_argument("--type", choices=("startup", "product"), default="startup")
    parser.add_argument("--output", default="data/startups.jsonl")
    args = parser.parse_args()
    records = asyncio.run(collect(args.urls, entity_type=args.type))
    append_records(args.output, records)
    print(f"Collected {len(records)} validated {args.type} records into {args.output}")
