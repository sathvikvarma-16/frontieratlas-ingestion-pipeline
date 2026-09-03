"""Shared bounded-concurrency HTTP scraper primitives."""

import asyncio
import random
from collections.abc import Iterable

import aiohttp


async def fetch_text(
    session: aiohttp.ClientSession,
    url: str,
    *,
    timeout_seconds: float = 30,
    retries: int = 3,
) -> str:
    """Fetch text with bounded exponential backoff for transient responses."""
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=timeout) as response:
                response.raise_for_status()
                return await response.text()
        except (aiohttp.ClientError, TimeoutError):
            if attempt == retries - 1:
                raise
            await asyncio.sleep((2**attempt) + random.uniform(0, 0.5))
    raise RuntimeError("unreachable")


async def fetch_many(urls: Iterable[str], *, concurrency: int = 10) -> dict[str, str]:
    """Fetch URLs concurrently while limiting in-flight requests."""
    semaphore = asyncio.Semaphore(concurrency)

    async with aiohttp.ClientSession() as session:
        async def fetch_one(url: str) -> tuple[str, str]:
            async with semaphore:
                return url, await fetch_text(session, url)

        results = await asyncio.gather(*(fetch_one(url) for url in urls))
    return dict(results)
