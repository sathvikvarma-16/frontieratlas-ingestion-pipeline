# FrontierAtlas Ingestion Pipeline

Async, fault-tolerant data pipeline for ingesting startups, products, research papers, jobs, and news for the FrontierAtlas AI Intelligence Graph — built as part of the AI Engineer trial task.

## Overview

This pipeline performs:

1. **Massive bulk extraction** of startup, product, and research paper entities via concurrent async scraping.
2. **High-fidelity signal ingestion** of AI news and job postings, filtered to the last 24 hours.
3. **Multi-tier LLM extraction** (Gemini Flash → Groq Llama 3 → DeepSeek fallback chain) to turn raw scraped text into schema-compliant JSON.
4. **Deterministic entity resolution** to canonicalize messy startup/product names (e.g. "OpenAI, Inc." → "OpenAI").
5. Output to a structured **Google Sheet** (6 tabs) and a local database for querying.

Full architecture rationale — scale strategy to 500K+ records, 413/429 handling, freshness tracking across distributed nodes, and storage justification — is in [`architecture.pdf`](./architecture.pdf).

## Repo Structure

```
.
├── README.md
├── architecture.pdf
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

## Architecture Overview

**Scraping layer:** `aiohttp` for static/directory pages, `Playwright (async)` for JavaScript-rendered or anti-bot-protected sources. Concurrency is capped and rate-limited per domain to avoid tripping protections; retries use exponential backoff with jitter.

**LLM extraction layer:** Each raw record is passed through a fallback chain — Gemini Flash first, then Groq (Llama 3), then DeepSeek — so a 429 or outage on one provider doesn't stall the pipeline. Payloads are chunked/truncated ahead of time to avoid 413 errors while preserving the most semantically dense content (title, key paragraphs, structured fields) over boilerplate.

**Entity resolution:** Incoming startup/product names are fuzzy-matched (`rapidfuzz`) against a seed list of ~50 known canonical entities. Matches above a confidence threshold are auto-canonicalized; everything else is logged to the Entity Mapping Log tab for review, so no entity is silently merged or lost.

**Freshness tracking:** News and job records are filtered to a strict 24-hour publish window at ingestion time. Relative dates ("2 hours ago") are normalized via custom parsing; sources without reliable timestamps fall back to a last-seen heuristic to avoid reprocessing.

**Data fidelity:** Every record retains its original `source.url`. The LLM extraction step is instructed to return null/empty for any field it cannot confidently extract rather than infer or guess — no field is populated without a traceable source.

## Output

Public Google Sheet: `<insert link>`

| Tab | Contents |
|---|---|
| Startups | 1,000+ unique startup records |
| Products | 1,000+ unique product records |
| Research Papers | 1,000+ papers with GitHub star counts |
| Jobs | All jobs found within the last 24 hours |
| News | All news found within the last 24 hours |
| Entity Mapping Log | Raw name → canonical name resolution trail |

## Known Limitations

- <list any sources you couldn't fully bypass anti-bot protections on, and how you'd address it at scale — this is expected and graded as part of "scale thinking," not a weakness to hide>
- <note any entity types where canonicalization confidence was low>

## Next Steps for Production Scale

See `architecture.pdf` for the full write-up on scaling to 500,000+ records, including infrastructure scaling strategy, distributed dedup, and storage architecture.
