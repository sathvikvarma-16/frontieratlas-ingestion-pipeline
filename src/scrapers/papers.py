"""Arxiv paper collector with optional GitHub repository enrichment."""

import asyncio
import argparse
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime

import aiohttp

from src.schemas import ResearchPaper
from src.storage import append_records
from .base import fetch_text

ARXIV_API = "https://export.arxiv.org/api/query"
ATOM = "http://www.w3.org/2005/Atom"
GITHUB_PATTERN = re.compile(r"https?://github\.com/[\w.-]+/[\w.-]+", re.I)


def _text(element: ET.Element | None) -> str:
    return " ".join((element.text or "").split()) if element is not None else ""


def parse_arxiv_feed(xml: str) -> list[ResearchPaper]:
    """Convert an Arxiv Atom response into validated paper records."""
    root = ET.fromstring(xml)
    papers: list[ResearchPaper] = []
    for entry in root.findall(f"{{{ATOM}}}entry"):
        paper_url = _text(entry.find(f"{{{ATOM}}}id"))
        published = _text(entry.find(f"{{{ATOM}}}published"))
        if not paper_url or not published:
            continue
        github_match = GITHUB_PATTERN.search(_text(entry.find(f"{{{ATOM}}}summary")))
        papers.append(ResearchPaper(
            title=_text(entry.find(f"{{{ATOM}}}title")),
            authors=[_text(author.find(f"{{{ATOM}}}name")) for author in entry.findall(f"{{{ATOM}}}author")],
            abstract=_text(entry.find(f"{{{ATOM}}}summary")),
            published_at=datetime.fromisoformat(published.replace("Z", "+00:00")),
            paper_url=paper_url,
            github_url=github_match.group(0).rstrip(".,)") if github_match else None,
        ))
    return papers


async def enrich_github_stars(session: aiohttp.ClientSession, papers: list[ResearchPaper]) -> None:
    """Populate current public GitHub star counts when repositories are present."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for paper in papers:
        if not paper.github_url:
            continue
        parts = str(paper.github_url).rstrip("/").split("github.com/")[-1].split("/")
        if len(parts) != 2:
            continue
        try:
            async with session.get(f"https://api.github.com/repos/{parts[0]}/{parts[1]}", headers=headers) as response:
                if response.status == 200:
                    paper.github_stars = (await response.json()).get("stargazers_count")
        except (aiohttp.ClientError, TimeoutError):
            continue


async def collect(query: str = "cat:cs.AI", max_results: int = 100) -> list[ResearchPaper]:
    """Fetch and validate papers from Arxiv, then enrich linked repositories."""
    url = f"{ARXIV_API}?search_query={query}&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
    async with aiohttp.ClientSession(headers={"User-Agent": "FrontierAtlas/1.0"}) as session:
        feed = await fetch_text(session, url)
        papers = parse_arxiv_feed(feed)
        await enrich_github_stars(session, papers)
    return papers

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="cat:cs.AI")
    parser.add_argument("--max-results", type=int, default=100)
    parser.add_argument("--output", default="papers.json")
    arguments = parser.parse_args()
    records = asyncio.run(collect(arguments.query, arguments.max_results))
    append_records(arguments.output, records)
    print(f"Collected {len(records)} papers into {arguments.output}")
