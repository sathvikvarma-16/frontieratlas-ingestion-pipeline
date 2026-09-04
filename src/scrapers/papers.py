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
PAPERS_WITH_CODE_REPOSITORIES = "https://paperswithcode.com/api/v1/papers/{arxiv_id}/repositories/"
ATOM = "http://www.w3.org/2005/Atom"
GITHUB_PATTERN = re.compile(r"https?://github\.com/[\w.-]+/[\w.-]+", re.I)


def _text(element: ET.Element | None) -> str:
    return " ".join((element.text or "").split()) if element is not None else ""


def _arxiv_id(paper_url: str) -> str | None:
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([\w.-]+)", paper_url, re.I)
    return match.group(1).removesuffix(".pdf") if match else None


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


def _github_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = GITHUB_PATTERN.search(value)
    return match.group(0).rstrip(".,)/") if match else None


def _pwc_repository(payload: object) -> tuple[str, int | None] | None:
    if not isinstance(payload, dict):
        return None
    repositories = payload.get("results") if isinstance(payload.get("results"), list) else payload.get("repositories")
    if not isinstance(repositories, list):
        return None
    for repository in repositories:
        if not isinstance(repository, dict):
            continue
        url = _github_url(repository.get("url") or repository.get("repository_url") or repository.get("github_url"))
        if url:
            stars = repository.get("stars") or repository.get("stargazers_count")
            return url, stars if isinstance(stars, int) else None
    return None


async def enrich_github_data(
    session: aiohttp.ClientSession,
    papers: list[ResearchPaper],
    *,
    delay_seconds: float = 0.4,
) -> None:
    """Use Papers with Code to find repositories, then GitHub for current stars."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    matched = 0
    for paper in papers:
        repository_stars: int | None = None
        identifier = _arxiv_id(str(paper.paper_url))
        try:
            if identifier and not paper.github_url:
                async with session.get(PAPERS_WITH_CODE_REPOSITORIES.format(arxiv_id=identifier)) as response:
                    if response.status == 200:
                        repository = _pwc_repository(await response.json())
                        if repository:
                            paper.github_url, repository_stars = repository
            github_url = _github_url(str(paper.github_url)) if paper.github_url else None
            if github_url:
                paper.github_url = github_url
                parts = github_url.rstrip("/").split("github.com/")[-1].split("/")
                if len(parts) == 2:
                    async with session.get(f"https://api.github.com/repos/{parts[0]}/{parts[1]}", headers=headers) as response:
                        if response.status == 200:
                            repository_stars = (await response.json()).get("stargazers_count")
            if paper.github_url:
                matched += 1
                paper.github_stars = repository_stars
        except (aiohttp.ClientError, TimeoutError):
            pass
        await asyncio.sleep(delay_seconds)
    print(f"GitHub enrichment: {matched}/{len(papers)} papers matched to a repository")


async def collect(query: str = "cat:cs.AI", max_results: int = 100) -> list[ResearchPaper]:
    """Fetch and validate papers from Arxiv, then enrich linked repositories."""
    url = f"{ARXIV_API}?search_query={query}&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
    async with aiohttp.ClientSession(headers={"User-Agent": "FrontierAtlas/1.0"}) as session:
        feed = await fetch_text(session, url)
        papers = parse_arxiv_feed(feed)
        await enrich_github_data(session, papers)
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
