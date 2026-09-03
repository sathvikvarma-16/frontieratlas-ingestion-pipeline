"""Deterministic fuzzy matching against a canonical entity seed list."""

import re
from difflib import SequenceMatcher
from dataclasses import dataclass

try:
    from rapidfuzz.fuzz import WRatio
except ImportError:
    def WRatio(left: str, right: str) -> float:
        return SequenceMatcher(None, left, right).ratio() * 100


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
