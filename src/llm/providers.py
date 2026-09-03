"""Provider contract used by the extraction fallback chain."""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol


class LLMProvider(Protocol):
    name: str

    async def extract(self, prompt: str) -> dict[str, Any]: ...


class CallableProvider:
    """Adapt an async extraction function to the provider protocol."""

    def __init__(self, name: str, function: Callable[[str], Awaitable[dict[str, Any]]]) -> None:
        self.name = name
        self._function = function

    async def extract(self, prompt: str) -> dict[str, Any]:
        return await self._function(prompt)
