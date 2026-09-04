# FrontierAtlas Ingestion Pipeline

An asynchronous, source-traceable ingestion pipeline for building an intelligence graph across AI startups, products, research papers, jobs, and news.

The project demonstrates the core engineering problems behind a production data-intelligence system: heterogeneous sources, pagination, freshness, schema validation, LLM extraction, provider failure, entity resolution, deduplication, and export.

## What This Demonstrates

- **Bulk acquisition:** Async `aiohttp` collectors for structured APIs and RSS/Atom feeds.
- **Resilient extraction:** A Gemini -> Groq -> DeepSeek fallback chain with JSON output, chunking, retries, and `429`/`413` handling.
- **Data quality:** Pydantic schemas, conservative null handling, source URLs, normalized timestamps, and freshness filters.
- **Entity resolution:** Deterministic normalization plus `rapidfuzz` matching against a canonical AI-company seed list.
- **Operational behavior:** Pagination, bounded concurrency, polite delays, progress logging, and URL deduplication.
- **Reviewable outputs:** JSONL records, local SQLite persistence, CSV tabs, and optional Google Sheets export.

## Architecture

```text
Public APIs / RSS / directories
              |
              v
      src/scrapers/ + base.py
   fetch, paginate, retry, normalize
              |
              v
      src/schemas/models.py
       validate canonical records
              |
              v
       src/llm/entity_enrichment.py
       optional structured enrichment
              |
              v
        src/resolver/
    normalize and resolve names
              |
              v
 src/storage.py + src/database.py
       JSONL + SQLite persistence
              |
              v
       src/export/csv_tabs.py
       CSV tabs / Google Sheets
```

The end-to-end entry point is `src/main.py`. Detailed scale, anti-bot, storage, and production design decisions are documented in [`architecture.md`](./architecture.md).

## Repository Map

```text
src/
├── main.py                         End-to-end pipeline entry point
├── refresh_submission.py           Clean, reproducible submission refresh
├── database.py                     Local SQLite idempotency store
├── storage.py                      Append-only JSONL writer
├── schemas/models.py               Pydantic contracts for all record types
├── scrapers/
│   ├── base.py                     Async HTTP primitives and retries
│   ├── startups.py                 Startup/product directories and pagination
│   ├── papers.py                   arXiv collection and GitHub enrichment
│   ├── news_jobs.py                RSS/Atom/JSON news and job collectors
│   └── freshness.py                Timestamp normalization and freshness rules
├── llm/
│   ├── orchestrator.py             Provider fallback orchestration
│   ├── http_providers.py            Gemini, Groq, and DeepSeek clients
│   ├── entity_enrichment.py        Optional startup/product field enrichment
│   └── chunking.py                 Context-size protection
├── resolver/                       Canonical-name resolution
└── export/
    ├── csv_tabs.py                 Spreadsheet-ready CSV generation
    └── to_sheets.py                Optional Google Sheets exporter

tests/test_pipeline.py              Focused regression tests
```

## Data Flow

### 1. Scrape

Collectors accept explicitly configured source URLs and retain provenance on every record. Product directories use offset pagination and stop at the configured target or an empty or duplicate page. Job collection supports public JSON/RSS sources and pagination where available.

News and jobs are parsed through `src/scrapers/news_jobs.py`. Relative dates and standard ISO/RFC dates are normalized to UTC. Jobs are accepted only within the assignment's 24-hour freshness window.

### 2. Validate and enrich

All records are validated against `src/schemas/models.py` before persistence. Optional LLM enrichment is implemented in `src/llm/entity_enrichment.py` and fills only missing fields:

- Startups: `description`, `employee_count`, `headquarters`
- Products: `company`, `pricing_model`

The instruction requires JSON output and `null` for unsupported or ambiguous facts. Values are validated before assignment; existing source values are never overwritten. If no provider key is configured, enrichment is skipped.

### 3. Resolve

`src/resolver/` removes punctuation and legal suffixes, then applies exact and fuzzy matching against `data/canonical_entities.json`. Only matches above the configured confidence threshold are canonicalized. Uncertain names remain visible in the Entity Mapping Log instead of being silently merged.

### 4. Persist and export

`src/storage.py` writes JSONL records, while `src/database.py` stores local idempotency records in SQLite. `src/export/csv_tabs.py` generates six spreadsheet-ready tabs:

| Tab | Record type | Required role |
| --- | --- | --- |
| Startups | `STARTUP` | Company entities and operating metadata |
| Products | `PRODUCT` | AI tools and products |
| Research Papers | `RESEARCH_PAPER` | arXiv metadata and verified GitHub metrics when available |
| Jobs | `JOB` | Fresh job signals and normalized job metadata |
| News | `NEWS` | Fresh news signals |
| Entity Mapping Log | Startup/product names | Resolution audit trail |

## LLM Reliability

The provider chain is configured in `src/llm/http_providers.py`:

1. Gemini Flash
2. Groq Llama
3. DeepSeek

`src/llm/orchestrator.py` isolates provider failures and tries the next configured provider. Provider clients retry transient `429` and `5xx` responses with exponential backoff and jitter. `src/llm/chunking.py` bounds request size to reduce `413 Payload Too Large` failures.

Fallback improves availability; it is not treated as a source of truth. Source text is always supplied to the model, extraction is constrained to named fields, uncertain values become `null`, and schema validation rejects invalid values.

## Setup

Requires Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Configure `.env` with only the credentials and sources you are authorized to use:

```dotenv
GEMINI_API_KEY=
GROQ_API_KEY=
DEEPSEEK_API_KEY=
GITHUB_TOKEN=
LLM_ENRICHMENT_ENABLED=true
STARTUP_SOURCE_URLS=https://yc-oss.github.io/api/companies/all.json
PRODUCT_SOURCE_URLS=https://vibeking.fun/api/products?limit=100
```

`.env` is local configuration and must never be committed. `.env.example` contains placeholders only.

## Run It

Run the test suite first:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src
```

Run the configured pipeline:

```powershell
python -m src.main --papers 1000 --output data/records.jsonl
```

For a clean submission refresh that does not append duplicate records:

```powershell
$env:LLM_ENRICHMENT_ENABLED='false'
python -m src.refresh_submission --output data/submission_records.jsonl --papers data/papers.jsonl
python -c "from src.export.csv_tabs import export_tabs; print(export_tabs('data/submission_records.jsonl','data/tabs'))"
```

Set `LLM_ENRICHMENT_ENABLED` to `true` when you intentionally want to spend configured provider credits on missing startup/product fields. The deterministic source mappings still run when LLM enrichment is disabled.

Run individual adapters when debugging a source:

```powershell
python -m src.scrapers.papers --max-results 1000 --output data/papers.jsonl
python -m src.scrapers.startups https://approved.example/feed.json --type startup --output data/startups.jsonl
python -m src.scrapers.news_jobs https://approved.example/feed.xml --type job --output data/jobs.jsonl
```

## Validation Snapshot

A validated refresh produced the following output sizes:

```text
Startups:         6,189
Products:         1,000
Research Papers:  1,000
Jobs:               619
News:                22
Mapping Log:      7,189
```

Field population is source-dependent. Unknown values remain empty by design; the pipeline does not manufacture employee counts, locations, pricing models, repository links, or star counts.

## Production Scale

The current repository is a reliable local reference implementation. The path to 500k+ records is described in [`architecture.md`](./architecture.md) and includes:

- Durable queues partitioned by source and crawl date
- Separate scraper, enrichment, resolution, and export worker pools
- Per-domain rate-limit buckets and bounded concurrency
- Response caching, conditional requests, and content-hash extraction caching
- Checkpointed pagination and dead-letter queues
- Provider circuit breakers, metrics, and `Retry-After` support
- Durable uniqueness on normalized source URL and content hash
- Managed proxy rotation only where permitted by source terms and robots policy

The repository currently uses local SQLite, JSONL, and CSV. Distributed queues, production database infrastructure, and proxy services are documented as scale-up architecture rather than claimed as implemented components.

## Known Limitations

- Public sources can change formats or block automated requests with Cloudflare or other anti-bot controls. Collectors report failures and continue where possible.
- Papers with Code may redirect or be unreachable. Papers are still collected, but GitHub fields remain empty when no verified repository is found.
- LLM enrichment requires configured API keys and can be slow because requests are rate-limited. It is optional and can be disabled.
- Not every product source exposes a pricing model, and not every job source exposes remote status or location. These fields remain empty when evidence is absent.
- The default local process is not a distributed 500k-record deployment; the production changes are documented in `architecture.md`.

## Engineering Notes

The design favors traceability over aggressive completion:

- Every record keeps its source URL.
- Empty values mean unknown, not guessed.
- Source-provided values take precedence over LLM output.
- Pagination stops on empty or duplicate pages.
- Freshness and retry behavior are explicit in code.
- Generated CSV cells are normalized for reliable spreadsheet import.

That makes the output inspectable, reproducible, and suitable for review before publication.
