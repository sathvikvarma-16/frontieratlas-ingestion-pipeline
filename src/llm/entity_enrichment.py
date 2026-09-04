"""Optional LLM enrichment for scraped startup and product records."""

import asyncio
from collections.abc import Sequence
from typing import Any

from src.schemas import Product, Startup

from .orchestrator import ExtractionError, LLMOrchestrator
from .http_providers import providers_from_environment

ENRICHMENT_DELAY_SECONDS = 0.4
PRICING_MODELS = {"FREE", "FREEMIUM", "PAID", "ENTERPRISE"}


def _source_text(record: Startup | Product) -> str:
    fields = [f"name: {record.name}", f"website: {record.website or ''}", f"description: {record.description or ''}"]
    if isinstance(record, Startup):
        fields.extend([
            f"employee_count: {record.employee_count if record.employee_count is not None else ''}",
            f"headquarters: {record.headquarters or ''}",
        ])
    else:
        fields.extend([
            f"company: {record.company or ''}",
            f"pricing_model: {record.pricing_model or ''}",
        ])
    return "\n".join(fields)


def _instruction(record: Startup | Product) -> str:
    if isinstance(record, Startup):
        fields = "description (short factual company description), employee_count (non-negative integer), headquarters (city and/or country)"
    else:
        fields = "company (company name), pricing_model (one of FREE, FREEMIUM, PAID, ENTERPRISE)"
    return (
        "Extract only the following missing structured fields from the source text: " + fields + ". "
        "Return a single JSON object with exactly these keys. Use null when a value is absent, ambiguous, or not explicitly supported. "
        "Do not infer, guess, or use outside knowledge. Keep an existing value unchanged."
    )


def _usable_value(record: Startup | Product, field: str, value: Any) -> Any:
    if field == "employee_count":
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    if field == "pricing_model":
        return value if isinstance(value, str) and value.upper() in PRICING_MODELS else None
    if field in {"description", "headquarters", "company"}:
        return value.strip() if isinstance(value, str) and value.strip() else None
    return None


async def enrich_entities(
    records: Sequence[Startup | Product],
    *,
    orchestrator: LLMOrchestrator | None = None,
    delay_seconds: float = ENRICHMENT_DELAY_SECONDS,
) -> list[Startup | Product]:
    """Fill missing entity fields through the configured provider fallback chain."""
    providers = providers_from_environment() if orchestrator is None else orchestrator.providers
    if not providers:
        print("LLM enrichment skipped: no provider API keys configured")
        return list(records)
    extractor = orchestrator or LLMOrchestrator(providers)
    field_names = ("description", "employee_count", "headquarters") if records and isinstance(records[0], Startup) else ("company", "pricing_model")
    filled = {field: 0 for field in field_names}
    enriched = 0
    for record in records:
        missing = [field for field in field_names if getattr(record, field) in (None, "")]
        if missing:
            try:
                extracted = await extractor.extract(_instruction(record), _source_text(record))
                if not isinstance(extracted, dict):
                    extracted = {}
                for field in missing:
                    value = _usable_value(record, field, extracted.get(field))
                    if value is not None:
                        setattr(record, field, value)
                        filled[field] += 1
                enriched += 1
            except ExtractionError as error:
                print(f"LLM enrichment failed for {record.name}: {error}")
        await asyncio.sleep(delay_seconds)
    filled_summary = ", ".join(f"{field}={count}" for field, count in filled.items())
    print(f"LLM enrichment: {enriched}/{len(records)} records processed; {filled_summary}")
    return list(records)
