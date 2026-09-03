"""HTTP clients for Gemini, Groq, and DeepSeek with provider-neutral contracts."""

import asyncio
import random
from typing import Any

import aiohttp


class HTTPProvider:
    def __init__(self, name: str, endpoint: str, api_key: str, model: str) -> None:
        self.name, self.endpoint, self.api_key, self.model = name, endpoint, api_key, model

    async def extract(self, prompt: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": self.model, "temperature": 0, "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": prompt}]}
        for attempt in range(3):
            async with aiohttp.ClientSession() as session:
                async with session.post(self.endpoint, headers=headers, json=payload, timeout=60) as response:
                    if response.status == 413:
                        raise ValueError(f"{self.name} rejected payload with 413")
                    if response.status == 429 or response.status >= 500:
                        if attempt == 2:
                            response.raise_for_status()
                        await asyncio.sleep(2**attempt + random.uniform(0, 0.5))
                        continue
                    response.raise_for_status()
                    body = await response.json()
                    content = body["choices"][0]["message"]["content"]
                    import json
                    return json.loads(content)
        raise RuntimeError(f"{self.name} request failed")


class GeminiProvider(HTTPProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        super().__init__("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", api_key, model)


def providers_from_environment() -> list[HTTPProvider]:
    import os
    configured: list[HTTPProvider] = []
    if os.getenv("GEMINI_API_KEY"):
        configured.append(GeminiProvider(os.environ["GEMINI_API_KEY"]))
    if os.getenv("GROQ_API_KEY"):
        configured.append(HTTPProvider("groq", "https://api.groq.com/openai/v1/chat/completions", os.environ["GROQ_API_KEY"], "llama-3.1-8b-instant"))
    if os.getenv("DEEPSEEK_API_KEY"):
        configured.append(HTTPProvider("deepseek", "https://api.deepseek.com/chat/completions", os.environ["DEEPSEEK_API_KEY"], "deepseek-chat"))
    return configured