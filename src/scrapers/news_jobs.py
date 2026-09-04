"""Configurable RSS/Atom collectors for fresh news and job signals."""

import asyncio
import argparse
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp

from src.schemas import Job, NewsArticle
from src.storage import append_records

from .base import fetch_text
from .freshness import is_fresh, parse_relative_date

ATOM = "http://www.w3.org/2005/Atom"
RSS = "http://purl.org/rss/1.0/modules/content/"
JOB_FEED_URLS = [
    "https://remoteok.com/api",
    "https://weworkremotely.com/remote-jobs.rss",
    "https://remotive.com/api/remote-jobs",
    "https://jobicy.com/?feed=job_feed",
    "https://himalayas.app/jobs/rss",
    "https://www.arbeitnow.com/api/job-board-api",
]
JOB_PAGE_SIZE = 100
JOB_PAGE_DELAY_SECONDS = 0.4
JOB_FRESHNESS_HOURS = 24


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
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except ValueError:
            try:
                return parsedate_to_datetime(value).astimezone(timezone.utc)
            except (TypeError, ValueError):
                return None


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = re.sub(r"<[^>]+>", " ", unescape(str(value)))
    text = " ".join(text.split())
    return text or None


def _role_family(title: str) -> str:
    lowered = title.lower()
    families = (
        ("Data", ("data", "machine learning", " ml ", "ai ", "analytics", "research scientist")),
        ("Engineering", ("engineer", "developer", "software", "devops", "architect", "sre", "qa")),
        ("Product", ("product manager", "product owner", "product lead")),
        ("Design", ("design", "creative", "ux", "ui ")),
        ("Sales", ("sales", "account executive", "business development", " sdr", " bdr")),
        ("Marketing", ("marketing", "content", "seo", "growth", "communications")),
        ("Customer Success", ("customer success", "support", "customer experience")),
        ("Operations", ("operations", "project manager", "program manager", "recruiter", "human resources")),
    )
    for family, keywords in families:
        if any(keyword in f" {lowered} " for keyword in keywords):
            return family
    return "Other"


def _remote_value(value: object, text: str) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = f"{value or ''} {text}".lower()
    if any(token in normalized for token in ("remote", "work from home", "distributed")):
        return True
    if any(token in normalized for token in ("on-site", "onsite", "in office", "hybrid")):
        return False
    return None


def _json_items(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("jobs", "data", "results"):
            if isinstance(payload.get(key), list):
                return [item for item in payload[key] if isinstance(item, dict)]
    return []


def _json_job(item: dict[str, object], source_url: str, *, now: datetime) -> dict[str, object] | None:
    title = _clean(item.get("title") or item.get("position"))
    link = _clean(item.get("url") or item.get("link") or item.get("apply_url"))
    if not title or not link:
        return None
    date_value = _clean(item.get("date") or item.get("publication_date") or item.get("created_at") or item.get("posted_at"))
    published = _date(date_value, now)
    if not is_fresh(published, now=now, hours=JOB_FRESHNESS_HOURS):
        return None
    company_value = item.get("company") or item.get("company_name") or item.get("organization")
    location_value = item.get("location") or item.get("job_geo") or item.get("candidate_required_location")
    description = _clean(item.get("description") or item.get("content")) or ""
    location = _clean(location_value) or ("Remote" if _remote_value(item.get("remote"), description) else None)
    return {"title": title, "url": link, "published_at": published.isoformat(), "source_url": source_url,
            "company": _clean(company_value), "location": location,
            "is_remote": _remote_value(item.get("remote") or item.get("remote_ok"), f"{location or ''} {description}"),
            "role_family": _role_family(title)}


def _job_page_urls(url: str, *, max_pages: int = 10) -> list[str]:
    """Return additional pages only for feeds with documented page parameters."""
    if not any(host in url for host in ("arbeitnow.com/api/job-board-api", "remotive.com/api/remote-jobs", "jobicy.com/")):
        return [url]
    parsed = urlsplit(url)
    page_urls = [url]
    for page in range(2, max_pages + 1):
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["page"] = str(page)
        page_urls.append(urlunsplit(parsed._replace(query=urlencode(query))))
    return page_urls


def parse_feed(xml: str, source_url: str, *, now: datetime | None = None, freshness_hours: int = 24) -> list[dict[str, object]]:
    """Parse RSS, Atom, or supported public job JSON feeds."""
    current = now or datetime.now(timezone.utc)
    try:
        payload = json.loads(xml)
    except json.JSONDecodeError:
        payload = None
    if payload is not None:
        records = []
        for item in _json_items(payload):
            record = _json_job(item, source_url, now=current)
            if record:
                records.append(record)
        return records
    root = ET.fromstring(xml)
    records: list[dict[str, object]] = []
    entries = root.findall(f"{{{ATOM}}}entry") or root.findall(".//item")
    for entry in entries:
        title = _clean(entry.findtext(f"{{{ATOM}}}title") or entry.findtext("title"))
        link = entry.findtext(f"{{{ATOM}}}link") or entry.findtext("link")
        if not link:
            link_node = entry.find(f"{{{ATOM}}}link")
            link = link_node.get("href") if link_node is not None else None
        link = _clean(link)
        date_value = next((value for tag in (f"{{{ATOM}}}published", f"{{{ATOM}}}updated", "pubDate", "published") if (value := entry.findtext(tag))), None)
        published = _date(date_value, current)
        description = _clean(entry.findtext(f"{{{RSS}}}encoded") or entry.findtext("description") or entry.findtext(f"{{{ATOM}}}summary")) or ""
        company = _clean(entry.findtext("{https://jobicy.com}company") or entry.findtext("{https://himalayas.app/ns/jobs}company") or entry.findtext("{http://purl.org/dc/elements/1.1/}creator"))
        location = _clean(entry.findtext("{https://jobicy.com}job_listing_location") or entry.findtext("{https://himalayas.app/ns/jobs}location"))
        if title and link and is_fresh(published, now=current, hours=freshness_hours):
            if not company and ":" in title:
                company, title = (part.strip() for part in title.split(":", 1))
            detail = f"{title} {description} {location or ''}"
            records.append({"title": title, "url": link, "published_at": published.isoformat(), "source_url": source_url,
                            "company": company, "location": location or ("Remote" if _remote_value(None, detail) else None),
                            "is_remote": _remote_value(None, detail), "role_family": _role_family(title)})
    return records


def parse_typed_feed(xml: str, source_url: str, *, record_type: str, now: datetime | None = None, freshness_hours: int = 24) -> list[NewsArticle | Job]:
    """Parse fresh items and validate them as the requested assignment entity."""
    records: list[NewsArticle | Job] = []
    for item in parse_feed(xml, source_url, now=now, freshness_hours=freshness_hours):
        if record_type == "news":
            records.append(NewsArticle(title=item["title"], published_at=item["published_at"], article_url=item["url"], source_url=source_url))
        else:
            records.append(Job(title=item["title"], company=item.get("company"), location=item.get("location"), posted_at=item["published_at"], application_url=item["url"], source_url=source_url, is_remote=item.get("is_remote"), role_family=item.get("role_family")))
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
    if record_type == "job" and not feed_urls:
        feed_urls = JOB_FEED_URLS
    async with aiohttp.ClientSession(headers={"User-Agent": "FrontierAtlas/0.1"}) as session:
        records: list[NewsArticle | Job] = []
        seen_urls: set[str] = set()
        for source_url in feed_urls:
            source_total = 0
            for page_number, page_url in enumerate(_job_page_urls(source_url), start=1):
                try:
                    result = await fetch_text(session, page_url)
                except (aiohttp.ClientError, TimeoutError) as error:
                    print(f"Jobs source failed: {page_url} ({error})")
                    break
                try:
                    source_records = parse_typed_feed(result, source_url, record_type=record_type, now=now, freshness_hours=JOB_FRESHNESS_HOURS if record_type == "job" else 24)
                except (ET.ParseError, json.JSONDecodeError) as error:
                    print(f"Jobs source skipped: {page_url} ({error})")
                    break
                unique_records = []
                for record in source_records:
                    record_url = str(record.application_url if isinstance(record, Job) else record.article_url)
                    if record_url not in seen_urls:
                        seen_urls.add(record_url)
                        unique_records.append(record)
                records.extend(unique_records)
                source_total += len(unique_records)
                print(f"{record_type.title()} source {source_url} page {page_number}: {len(unique_records)} records; running total {len(records)}")
                if not source_records or not unique_records:
                    break
                await asyncio.sleep(JOB_PAGE_DELAY_SECONDS)
            print(f"{record_type.title()} source {source_url}: {source_total} unique records")
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
