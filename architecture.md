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