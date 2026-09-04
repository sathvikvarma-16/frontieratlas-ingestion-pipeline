"""Deterministic fuzzy matching against a canonical entity seed list."""

import json
import os
import re
from difflib import SequenceMatcher
from dataclasses import dataclass
from pathlib import Path

try:
    from rapidfuzz.fuzz import WRatio
except ImportError:
    def WRatio(left: str, right: str) -> float:
        return SequenceMatcher(None, left, right).ratio() * 100


# Repo-root-relative default seed file: data/canonical_entities.json
_DEFAULT_SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "canonical_entities.json"


def load_canonical_seeds(path: str | Path | None = None) -> list[str]:
    """Load the canonical entity seed list.

    Resolution order:
        1. ``CANONICAL_ENTITIES`` env var, comma-separated (explicit override)
        2. The JSON seed file at ``path`` (defaults to data/canonical_entities.json)
        3. A tiny 3-name fallback, so the resolver never silently gets an
           empty list if both of the above are unavailable.
    """
    env_value = os.getenv("CANONICAL_ENTITIES", "").strip()
    if env_value:
        return [name.strip() for name in env_value.split(",") if name.strip()]

    seed_path = Path(path) if path else _DEFAULT_SEED_PATH
    if seed_path.exists():
        try:
            with seed_path.open(encoding="utf-8") as handle:
                names = json.load(handle)
            if isinstance(names, list) and names:
                return [str(name).strip() for name in names if str(name).strip()]
        except (json.JSONDecodeError, OSError):
            pass

    return ["OpenAI", "Anthropic", "DeepMind"]


@dataclass(frozen=True)
class Resolution:
    raw_name: str
    canonical_name: str | None
    score: float


class EntityResolver:
    def __init__(self, canonical_names: list[str], *, threshold: float = 90) -> None:
        self.canonical_names = canonical_names
        self.threshold = threshold

    @staticmethod
    def normalize(name: str) -> str:
        name = re.sub(r"\b(incorporated|corporation|limited|inc|ltd|llc)\b", "", name, flags=re.I)
        return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()

    def resolve(self, raw_name: str) -> Resolution:
        if not raw_name.strip() or not self.canonical_names:
            return Resolution(raw_name, None, 0)
        normalized = self.normalize(raw_name)
        best_name, best_score = max(
            ((name, WRatio(normalized, self.normalize(name))) for name in self.canonical_names),
            key=lambda item: item[1],
        )
        canonical = best_name if best_score >= self.threshold else None
        return Resolution(raw_name, canonical, best_score)


if __name__ == "__main__":
    print("Configure a canonical seed list and call EntityResolver.resolve()")