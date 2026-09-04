# FrontierAtlas Ingestion Pipeline

Async, fault-tolerant data pipeline for ingesting startups, products, research papers, jobs, and news for the FrontierAtlas AI Intelligence Graph — built as part of the AI Engineer trial task.

## Overview

This pipeline performs:

1. **Massive bulk extraction** of startup, product, and research paper entities via concurrent async scraping.
2. **High-fidelity signal ingestion** of AI news and job postings, filtered to the last 24 hours.
3. **Multi-tier LLM extraction** (Gemini Flash → Groq Llama 3 → DeepSeek fallback chain) to turn raw scraped text into schema-compliant JSON.
4. **Deterministic entity resolution** to canonicalize messy startup/product names (e.g. "OpenAI, Inc." → "OpenAI").
5. Output to a structured **Google Sheet** (6 tabs) and a local database for querying.

The architecture and scale strategy, including the production path to 500K+ records, is documented in [`architecture.md`](./architecture.md).

## Repo Structure

```
.
├── README.md
├── architecture.md
├── requirements.txt
├── .env.example
└── src/
    ├── scrapers/       # Async scrapers: startups, products, papers, news, jobs
    ├── llm/            # LLM orchestration: fallback chain, chunking, retry logic
    ├── resolver/        # Entity resolution / canonicalization engine
    └── schemas/         # Pydantic/JSON schema definitions for each entity type
```

## Setup

### Prerequisites

- Python 3.11+
- A Google Cloud service account with Sheets API access (for pushing output)
- API keys for: Gemini Flash, Groq, DeepSeek, GitHub (for star counts)

### Installation

```bash
git clone <this-repo-url>
cd frontieratlas-ingestion-pipeline
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Fill in .env with your API keys and Google service account credentials
```

### Running the pipeline

```bash
# Run the full pipeline end to end
python -m src.main

# Or run individual stages
python -m src.scrapers.papers        # Arxiv + Papers with Code
python -m src.scrapers.startups      # Startup/product directories
python -m src.scrapers.news_jobs     # News + jobs (24h freshness filter)
python -m src.llm.orchestrator       # Run raw records through LLM extraction
python -m src.resolver.resolve       # Entity resolution pass
python -m src.export.to_sheets       # Push final data to Google Sheet
```

The source adapters intentionally return no records until a source is configured; this prevents fabricated output. Use `src.scrapers.base.fetch_many` for bounded async acquisition, validate extracted records with `src.schemas`, pass raw text through `src.llm.LLMOrchestrator`, and resolve names with `src.resolver.EntityResolver`.

## Architecture & Scale Strategy

See [`architecture.md`](./architecture.md) for the pipeline flow, LLM fallback chain, entity resolution, anti-bot policy, 500K+ scale plan, known limitations, and end-to-end run instructions.

## Output

Google Sheets output: generated through the optional `src/export/to_sheets.py` exporter after local CSV review.

| Tab | Contents |
|---|---|
| Startups | 1,000+ unique startup records |
| Products | 1,000+ unique product records |
| Research Papers | 1,000+ papers with GitHub star counts |
| Jobs | All jobs found within the last 24 hours |
| News | All news found within the last 24 hours |
| Entity Mapping Log | Raw name → canonical name resolution trail |

## Known Limitations

See the limitations section in [`architecture.md`](./architecture.md). In brief, source availability varies, Papers with Code can be unreachable, and LLM enrichment is skipped unless provider keys are configured.

### Working commands

On Windows PowerShell, run these from the repository root:

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m unittest discover -s tests -v
python -m src.main
$env:LLM_ENRICHMENT_ENABLED='false'; python -m src.refresh_submission --output data/submission_records.jsonl --papers data/papers.jsonl
python -c "from src.export.csv_tabs import export_tabs; print(export_tabs('data/submission_records.jsonl'))"
python -m src.main --papers 100 --output data/papers.jsonl
python -m src.export.to_sheets data/papers.jsonl --output-dir data/tabs
python -m src.scrapers.startups https://your-approved-directory.example/feed.json --type startup --output data/startups.jsonl
python -m src.scrapers.news_jobs https://your-approved-news-source.example/feed.xml --output data/signals.jsonl
```

The paper command uses the public Arxiv API and writes only validated, source-linked records. RSS/Atom collection accepts explicit feed URLs, for example:

```powershell
python -m src.scrapers.news_jobs https://example.com/feed.xml --output data/signals.jsonl
```

The three LLM clients are activated only for keys present in `.env`; no key is printed or required for local tests. Google Sheets publication requires a separate authenticated exporter and should be run only after reviewing the generated CSV tabs.
