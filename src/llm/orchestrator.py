"""Provider fallback orchestration for schema extraction."""

from collections.abc import Sequence
from typing import Any

from .chunking import chunk_text
from .providers import LLMProvider


class ExtractionError(RuntimeError):
    """Raised when every configured provider fails."""


class LLMOrchestrator:
    def __init__(self, providers: Sequence[LLMProvider], *, max_chars: int = 12000) -> None:
        self.providers = providers
        self.max_chars = max_chars

    async def extract(self, instruction: str, raw_text: str) -> dict[str, Any]:
        errors: list[str] = []
        for provider in self.providers:
            try:
                chunks = chunk_text(raw_text, self.max_chars)
                extracted = []
                for chunk in chunks:
                    prompt = f"{instruction}\n\nSource text:\n{chunk}"
                    extracted.append(await provider.extract(prompt))
                return extracted[0] if len(extracted) == 1 else {"records": extracted}
            except Exception as error:  # providers are isolated from one another
                errors.append(f"{provider.name}: {error}")
        raise ExtractionError("All LLM providers failed: " + "; ".join(errors))


if __name__ == "__main__":
    print("Configure providers and call LLMOrchestrator.extract()")
