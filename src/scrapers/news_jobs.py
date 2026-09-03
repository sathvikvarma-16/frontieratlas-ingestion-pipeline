"""Configurable RSS/Atom collectors for fresh news and job signals."""

import asyncio
import argparse
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import aiohttp

from src.schemas import Job, NewsArticle
from src.storage import append_records

from .base import fetch_text
from .freshness import is_fresh, parse_relative_date

ATOM = "http://www.w3.org/2005/Atom"
RSS = "http://purl.org/rss/1.0/modules/content/"


def _date(value: str | None, now: datetime) -> datetime | None:
    if not value:
        return None
    relative = parse_relative_date(value, now=now)
    if relative:
        return relative
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        try:
            return parsedate_to_datetime(value).astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None


def parse_feed(xml: str, source_url: str, *, now: datetime | None = None) -> list[dict[str, str]]:
    """Parse RSS or Atom and retain only records with trustworthy fresh dates."""
    current = now or datetime.now(timezone.utc)
    root = ET.fromstring(xml)
    records: list[dict[str, str]] = []
    entries = root.findall(f"{{{ATOM}}}entry") or root.findall(".//item")
    for entry in entries:
        title = entry.findtext(f"{{{ATOM}}}title") or entry.findtext("title")
        link = entry.findtext(f"{{{ATOM}}}link") or entry.findtext("link")
        if not link:
            link_node = entry.find(f"{{{ATOM}}}link")
            link = link_node.get("href") if link_node is not None else None
        date_value = next((value for tag in (f"{{{ATOM}}}published", f"{{{ATOM}}}updated", "pubDate", "published") if (value := entry.findtext(tag))), None)
        published = _date(date_value, current)
        if title and link and is_fresh(published, now=current):
            records.append({"title": " ".join(title.split()), "url": link.strip(), "published_at": published.isoformat(), "source_url": source_url})
    return records


def parse_typed_feed(xml: str, source_url: str, *, record_type: str, now: datetime | None = None) -> list[NewsArticle | Job]:
    """Parse fresh items and validate them as the requested assignment entity."""
    records: list[NewsArticle | Job] = []
    for item in parse_feed(xml, source_url, now=now):
        if record_type == "news":
            records.append(NewsArticle(title=item["title"], published_at=item["published_at"], article_url=item["url"], source_url=source_url))
        else:
            records.append(Job(title=item["title"], posted_at=item["published_at"], application_url=item["url"], source_url=source_url))
    return records


async def collect(feed_urls: list[str], *, now: datetime | None = None) -> list[dict[str, str]]:
    async with aiohttp.ClientSession(headers={"User-Agent": "FrontierAtlas/0.1"}) as session:
        results = await asyncio.gather(*(fetch_text(session, url) for url in feed_urls), return_exceptions=True)
    records: list[dict[str, str]] = []
    for url, result in zip(feed_urls, results):
        if isinstance(result, str):
            try:
                records.extend(parse_feed(result, url, now=now))
            except ET.ParseError:
                continue
    return records


async def collect_typed(feed_urls: list[str], *, record_type: str, now: datetime | None = None) -> list[NewsArticle | Job]:
    async with aiohttp.ClientSession(headers={"User-Agent": "FrontierAtlas/0.1"}) as session:
        results = await asyncio.gather(*(fetch_text(session, url) for url in feed_urls), return_exceptions=True)
    records: list[NewsArticle | Job] = []
    for url, result in zip(feed_urls, results):
        if isinstance(result, str):
            try:
                records.extend(parse_typed_feed(result, url, record_type=record_type, now=now))
            except ET.ParseError:
                continue
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("urls", nargs="+", help="RSS or Atom feed URLs")
    parser.add_argument("--type", choices=("news", "job"), default="news")
    parser.add_argument("--output", default="data/signals.jsonl")
    args = parser.parse_args()
    records = asyncio.run(collect_typed(args.urls, record_type=args.type))
    append_records(args.output, records)
    print(f"Collected {len(records)} fresh signals into {args.output}")
