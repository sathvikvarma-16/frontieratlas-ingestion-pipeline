# Architecture & Scale Strategy

## Pipeline Overview

FrontierAtlas processes source data in four stages:

1. **Scrape:** Adapters under `src/scrapers/` collect permitted API, RSS/Atom, and directory data. `src/scrapers/base.py` provides `aiohttp` fetching, bounded concurrency, retries, and exponential backoff. The main entry point is `src/main.py`.
2. **LLM extract:** `src/llm/entity_enrichment.py` optionally sends raw fields to `src/llm/orchestrator.py`. The response is restricted to missing structured fields and validated against the Pydantic models in `src/schemas/models.py`.
3. **Entity resolve:** `src/resolver/` normalizes names and fuzzy-matches them against a canonical seed list of roughly 50 known AI companies. High-confidence matches are canonicalized; uncertain matches remain visible for review in the Entity Mapping Log.
4. **Store and export:** `src/storage.py` appends traceable JSONL records, `src/database.py` provides local SQLite idempotency, and `src/export/csv_tabs.py` writes spreadsheet-ready CSV tabs. `src/export/to_sheets.py` handles the optional Google Sheets export.

Every normalized record retains its source URL. Pydantic validation in `src/schemas/` prevents malformed extracted fields from entering the output.

## LLM Fallback and Data Fidelity

`src/llm/http_providers.py` builds the configured provider chain in this order:

1. Gemini Flash
2. Groq Llama
3. DeepSeek

`LLMOrchestrator.extract()` tries each configured provider and moves to the next provider when a request, response, or JSON parsing error occurs. Provider clients retry transient `429` and `5xx` responses with exponential backoff. `src/llm/chunking.py` keeps requests below the configured character budget.

The fallback chain improves availability, not factual certainty by itself. Hallucination risk is reduced by sending source text, requesting JSON-only output, asking the model to return `null` when evidence is absent or ambiguous, and validating values before assignment. Enrichment only fills fields that are currently empty; it never replaces source data with an unsupported model guess. With no API keys, enrichment is skipped and scraping continues normally.

## Entity Resolution

`src/resolver/resolve.py` and `src/resolver/__init__.py` normalize punctuation, legal suffixes, and whitespace before matching. Exact matches are preferred, followed by `rapidfuzz` similarity against the canonical seed list of about 50 AI companies. The configured confidence threshold controls automatic canonicalization. Low-confidence names are retained and logged rather than silently merged, preserving an audit trail for review.

## Anti-Bot and 500k+ Scale Strategy

The current adapters follow a polite acquisition policy:

- Use official APIs, public RSS/Atom feeds, and permitted directory endpoints first.
- Add small per-request delays where a source is paginated or enriched, generally `0.3` to `0.5` seconds.
- Keep concurrency bounded through `src/scrapers/base.py`; do not create an unbounded request fan-out.
- Retry transient failures with exponential backoff and jitter. Permanent failures are reported and the rest of the configured sources continue where the adapter supports it.
- Send an identifiable user agent. Production adapters should use a controlled, rotating user-agent pool only where permitted by the source terms and robots policy.

For sources that explicitly permit it, production deployment can use a managed proxy pool with rotating exit IPs, per-domain budgets, and sticky sessions for a crawl batch. Rotation should be used for geographic coverage and capacity management, not to bypass authentication, CAPTCHAs, access controls, or rate limits. Blocked sources should instead move to an approved API, export, or manual-review queue.

At 500k+ records, the single-process flow in `src/main.py` should become a distributed ingestion service:

- Put source/page work on a durable queue partitioned by source and crawl date.
- Run separate scraper, enrichment, resolution, and export worker pools with per-domain rate-limit buckets.
- Cache successful HTTP responses and normalized source pages using URL plus request parameters; use conditional requests when supported.
- Store raw payloads and parser versions for replay, with a durable database enforcing uniqueness on source, normalized URL, and content hash.
- Add dead-letter queues, checkpointed pagination, provider circuit breakers, metrics, and `Retry-After` handling.
- Batch LLM work, cache extraction results by content hash, and reserve model calls for records with missing fields.

The repository currently implements local SQLite persistence and JSONL/CSV export; the queue, proxy pool, distributed workers, and production database are scale-up designs rather than included services.

## Known Limitations

- Some public sources are blocked by Cloudflare or change their feed/API contracts. The jobs collector logs failed sources and continues, but source coverage will vary by network and date.
- Papers with Code endpoints can be unavailable, redirect, or be rate-limited. The collector uses the official repository mapping response first and then verifies current GitHub stars; fields remain null when no reliable link or GitHub response exists.
- LLM enrichment requires at least one configured provider key. Without keys, startup/product records retain only fields obtained from the source.
- Metadata extraction is conservative. Missing or ambiguous company, location, employee, headquarters, or pricing values remain null rather than being inferred.
- Job adapters accept JSON, RSS, and Atom variants from the configured boards and log zero-record sources for review; a source can still change its contract or block automated requests.
- The current local pipeline is not a 500k-record distributed deployment; concurrency, queueing, caching, and durable production storage require the scale-up work described above.

## End-to-End Run

From the repository root:

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Add permitted source URLs and optional LLM/API keys to .env
python -m unittest discover -s tests -v
python -m src.main --papers 1000 --output data/records.jsonl
```

`src.main` loads `.env`, collects papers, configured startup/product directories, default or configured job feeds, and configured news feeds, then appends records to JSONL, writes local SQLite records, and exports CSV tabs. Review `data/tabs/` before using the optional Sheets exporter:

```powershell
python -m src.export.to_sheets data/records.jsonl --output-dir data/tabs
```

Individual adapters can also be run directly. For example:

```powershell
python -m src.scrapers.papers --max-results 1000 --output data/papers.jsonl
python -m src.scrapers.startups https://approved.example/feed.json --type startup --output data/startups.jsonl
python -m src.scrapers.news_jobs https://approved.example/feed.xml --type job --output data/jobs.jsonl
```
# FrontierAtlas Ingestion Architecture

## Flow

Source adapters produce immutable raw records containing the original URL and fetch timestamp. A queue fans records out to extraction workers. Workers validate provider output against the Pydantic schemas, then write both the normalized record and the raw payload for auditability.

## Scale and reliability

Each domain has a rate limiter and bounded `aiohttp` concurrency. A partitioned queue (source and crawl date) allows workers to scale horizontally without code changes. Retries use exponential backoff with jitter for 429, 408, and transient 5xx responses; permanent 4xx responses are dead-lettered with the URL and response metadata.

For LLM calls, the orchestrator sends semantically ordered chunks below the smallest provider limit. A provider circuit breaker routes failures through Gemini Flash, Groq Llama, and DeepSeek. Per-provider token buckets, `Retry-After` support, and idempotency keys prevent retry storms. A 413 causes a smaller chunk retry; it never causes silent truncation.

## Freshness and deduplication

Normalize ISO dates, metadata dates, and relative phrases into UTC. News and jobs are accepted only when their timestamp is between now minus 24 hours and now. Sources without a trustworthy timestamp are held for a last-seen heuristic and flagged for review, never treated as fresh by default.

Store a uniqueness key of `(source, normalized_url, content_hash)` in PostgreSQL with an upsert. A distributed lease keyed by URL prevents two crawler nodes from processing the same item concurrently. The raw URL, fetch time, parser version, and extraction model are retained for replay and audit.

## Entity resolution and storage

Normalize punctuation, legal suffixes, and whitespace before exact matching. Fuzzy matching against a versioned seed list is accepted only above a threshold; uncertain matches go to the Entity Mapping Log rather than being merged. PostgreSQL is the system of record for constraints, timestamps, and idempotent writes. A graph projection such as Neo4j serves relationship traversal, while a vector index is used only for semantic discovery and never as the authority for identity.

## Anti-bot policy

Prefer official APIs, RSS, sitemaps, and permitted exports. For JavaScript-rendered sources, use Playwright with a small, transparent browser pool, realistic pacing, cached sessions, and robots/terms compliance. Do not attempt CAPTCHA bypass or stealth evasion; queue blocked URLs for an approved credentialed integration or manual review. This preserves source access and avoids claiming data that was not legitimately retrieved.