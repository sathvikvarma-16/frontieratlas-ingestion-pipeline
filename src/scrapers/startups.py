"""Configurable startup and product directory collector.

Sources must be explicitly supplied by the operator. Records retain their
source URL and are never synthesized when a directory omits a field.
"""

import argparse
import asyncio
import json
import os
from collections.abc import Iterable
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp

from src.schemas import Product, Source, Startup
from src.storage import append_records
from src.llm.entity_enrichment import enrich_entities

from .base import fetch_many, fetch_text

PRODUCT_TARGET = 1000
PRODUCT_PAGE_SIZE = 100
PRODUCT_PAGE_DELAY_SECONDS = 0.4


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
                common = {
                    "name": entry["name"],
                    "description": entry.get("description") or entry.get("long_description") or entry.get("one_liner") or entry.get("tagline"),
                    "website": entry.get("website") or entry.get("url"),
                }
                source = Source(name=entry.get("source_name", "configured-directory"), url=url)
                try:
                    if entity_type == "startup":
                        location = entry.get("headquarters") or entry.get("all_locations") or entry.get("location")
                        records.append(Startup(source=source, headquarters=location, employee_count=entry.get("employee_count") or entry.get("team_size"), **common))
                    else:
                        records.append(Product(source=source, company=entry.get("company") or entry.get("maker"), pricing_model=entry.get("pricing_model"), **common))
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


def _paginated_url(url: str, *, offset: int, limit: int = PRODUCT_PAGE_SIZE) -> str:
    """Set offset pagination parameters while preserving other source filters."""
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"limit": str(limit), "offset": str(offset)})
    return urlunsplit(parsed._replace(query=urlencode(query)))


async def collect_products(
    urls: Iterable[str],
    *,
    target: int = PRODUCT_TARGET,
    page_size: int = PRODUCT_PAGE_SIZE,
    delay_seconds: float = PRODUCT_PAGE_DELAY_SECONDS,
) -> list[Product]:
    """Fetch product directory APIs page by page until the target is reached."""
    products: list[Product] = []
    seen: set[tuple[str, str]] = set()
    async with aiohttp.ClientSession(headers={"User-Agent": "FrontierAtlas/1.0"}) as session:
        for source_url in urls:
            offset = 0
            page_number = 1
            while len(products) < target:
                page_url = _paginated_url(source_url, offset=offset, limit=page_size)
                print(f"Products page {page_number}: fetching offset {offset}")
                body = await fetch_text(session, page_url)
                page_products = parse_directory_pages({source_url: body}, entity_type="product")
                if not page_products:
                    print(f"Products page {page_number}: empty page; have {len(products)} products")
                    break

                unique_page_products = []
                for product in page_products:
                    key = (product.name.casefold(), str(product.website or ""))
                    if key not in seen:
                        seen.add(key)
                        unique_page_products.append(product)
                if not unique_page_products:
                    print(f"Products page {page_number}: duplicate page; have {len(products)} products")
                    break
                products.extend(unique_page_products)
                print(f"Products page {page_number}: have {len(products)} products so far")
                if len(products) >= target:
                    break

                offset += page_size
                page_number += 1
                await asyncio.sleep(delay_seconds)

    source_texts: dict[str, str] = {}
    if products and os.getenv("LLM_ENRICHMENT_ENABLED", "true").lower() in {"1", "true", "yes"}:
        page_urls = [str(product.website) for product in products if product.website and product.pricing_model is None]
        if page_urls:
            source_texts = await fetch_many(page_urls, concurrency=10)
    await enrich_entities(products, source_texts=source_texts)
    return products[:target]


async def collect(urls: Iterable[str], *, entity_type: str = "startup") -> list[Startup | Product]:
    pages = await fetch_many(urls)
    records = parse_directory_pages(pages, entity_type=entity_type)
    await enrich_entities(records)
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("urls", nargs="+", help="Explicit JSON or HTML directory URLs")
    parser.add_argument("--type", choices=("startup", "product"), default="startup")
    parser.add_argument("--output", default="data/startups.jsonl")
    args = parser.parse_args()
    records = asyncio.run(collect_products(args.urls)) if args.type == "product" else asyncio.run(collect(args.urls, entity_type=args.type))
    append_records(args.output, records)
    print(f"Collected {len(records)} validated {args.type} records into {args.output}")
