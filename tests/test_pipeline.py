import unittest
import asyncio
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.database import RecordStore
from src.llm.chunking import chunk_text
from src.resolver import EntityResolver
from src.scrapers.freshness import is_fresh, parse_relative_date
from src.scrapers.news_jobs import _article_text, parse_feed, parse_typed_feed
from src.scrapers.papers import _arxiv_id, _pwc_repository
from src.scrapers.startups import parse_directory_pages
from src.llm.entity_enrichment import enrich_entities
from src.llm.orchestrator import LLMOrchestrator
from src.llm.providers import CallableProvider
from src.schemas import Product, Source, Startup


class PipelineTests(unittest.TestCase):
    def test_fresh_feed_and_relative_date(self) -> None:
        now = datetime(2026, 9, 3, 12, tzinfo=timezone.utc)
        self.assertTrue(is_fresh(parse_relative_date("2 hours ago", now=now), now=now))
        xml = "<rss><channel><item><title>AI update</title><link>https://example.com/a</link><pubDate>Thu, 03 Sep 2026 11:00:00 GMT</pubDate></item></channel></rss>"
        self.assertEqual(len(parse_feed(xml, "https://example.com/feed", now=now)), 1)
        self.assertEqual(parse_typed_feed(xml, "https://example.com/feed", record_type="news", now=now)[0].recordType, "NEWS")
        self.assertEqual(parse_typed_feed(xml, "https://example.com/feed", record_type="job", now=now)[0].recordType, "JOB")

    def test_job_feed_populates_metadata(self) -> None:
        now = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
        xml = """<rss><channel><item>
            <title>Acme AI: Senior Data Engineer</title>
            <link>https://example.com/jobs/data-engineer</link>
            <pubDate>Fri, 04 Sep 2026 11:00:00 GMT</pubDate>
            <description>Work remotely with our data platform team.</description>
        </item></channel></rss>"""
        job = parse_typed_feed(xml, "https://example.com/feed", record_type="job", now=now)[0]
        self.assertEqual(job.company, "Acme AI")
        self.assertEqual(job.location, "Remote")
        self.assertTrue(job.is_remote)
        self.assertEqual(job.role_family, "Data")

        payload = '[{"title":"Product Manager","company_name":"Beta","url":"https://example.com/jobs/product","date":"2026-09-04T10:00:00Z","location":"United States","remote":true}]'
        json_job = parse_typed_feed(payload, "https://example.com/api", record_type="job", now=now)[0]
        self.assertEqual((json_job.company, json_job.location, json_job.role_family), ("Beta", "United States", "Product"))
        self.assertTrue(json_job.is_remote)

        himalayas = """<rss xmlns:job="https://himalayas.app/ns/jobs"><channel><item>
            <title>Senior Engineer</title><link>https://himalayas.app/companies/acme-ai/jobs/senior-engineer</link>
            <pubDate>Fri, 04 Sep 2026 11:00:00 GMT</pubDate><job:location>United States</job:location>
        </item></channel></rss>"""
        himalayas_job = parse_typed_feed(himalayas, "https://himalayas.app/jobs/rss", record_type="job", now=now)[0]
        self.assertEqual((himalayas_job.company, himalayas_job.location), ("acme ai", "United States"))

    def test_news_summary_uses_feed_description_and_article_text_helper(self) -> None:
        now = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
        xml = """<rss><channel><item>
            <title>AI update</title><link>https://example.com/a</link>
            <pubDate>Fri, 04 Sep 2026 11:00:00 GMT</pubDate>
            <description>Feed summary.</description>
        </item></channel></rss>"""
        article = parse_typed_feed(xml, "https://example.com/feed", record_type="news", now=now)[0]
        self.assertEqual(article.summary, "Feed summary.")
        self.assertIn("Main article text", _article_text("<nav>Menu</nav><main><p>Main article text.</p></main>") or "")

    def test_paper_repository_lookup_helpers(self) -> None:
        self.assertEqual(_arxiv_id("https://arxiv.org/abs/1706.03762"), "1706.03762")
        self.assertEqual(_arxiv_id("http://arxiv.org/abs/2609.04198v1"), "2609.04198")
        self.assertEqual(
            _pwc_repository({"results": [{"url": "https://github.com/google-research/bert", "stars": 42000}]}),
            ("https://github.com/google-research/bert", 42000),
        )
        self.assertEqual(
            _pwc_repository({"results": [{"repository": {"repository_url": "https://github.com/org/model"}}]}),
            ("https://github.com/org/model", None),
        )

    def test_optional_llm_enrichment_fills_missing_fields(self) -> None:
        async def extract(_: str) -> dict[str, object]:
            return {"description": "AI company", "employee_count": 12, "headquarters": "London"}

        startup = Startup(name="Acme", description="Existing description", source=Source(name="test", url="https://example.com"))
        orchestrator = LLMOrchestrator([CallableProvider("test", extract)])
        with patch.dict("os.environ", {"LLM_ENRICHMENT_ENABLED": "true"}):
            asyncio.run(enrich_entities([startup], orchestrator=orchestrator, delay_seconds=0))
        self.assertEqual((startup.description, startup.employee_count, startup.headquarters), ("Existing description", 12, "London"))

        async def extract_product(_: str) -> dict[str, object]:
            return {"company": "Acme Corp", "pricing_model": "PAID"}

        product = Product(name="Acme Tool", source=Source(name="test", url="https://example.com"))
        with patch.dict("os.environ", {"LLM_ENRICHMENT_ENABLED": "true"}):
            asyncio.run(enrich_entities([product], orchestrator=LLMOrchestrator([CallableProvider("test", extract_product)]), delay_seconds=0))
        self.assertEqual((product.company, product.pricing_model), ("Acme Corp", "PAID"))

        product.pricing_model = None
        async def extract_unsupported_pricing(_: str) -> dict[str, object]:
            return {"pricing_model": "usage-based"}

        with patch.dict("os.environ", {"LLM_ENRICHMENT_ENABLED": "true"}):
            asyncio.run(enrich_entities([product], orchestrator=LLMOrchestrator([CallableProvider("test", extract_unsupported_pricing)]), delay_seconds=0))
        self.assertIsNone(product.pricing_model)

    def test_resolver_and_chunks(self) -> None:
        self.assertEqual(EntityResolver(["OpenAI"]).resolve("Open AI, Inc.").canonical_name, "OpenAI")
        self.assertIsNone(EntityResolver(["OpenAI", "Midjourney"]).resolve("Open").canonical_name)
        self.assertIsNone(EntityResolver(["OpenAI", "Midjourney"]).resolve("jo").canonical_name)
        self.assertEqual("".join(chunk_text("abcdefghij", 3)), "abcdefghij")

    def test_store_is_idempotent(self) -> None:
        with TemporaryDirectory() as folder:
            store = RecordStore(str(Path(folder) / "records.db"))
            payload = {"title": "paper"}
            self.assertTrue(store.add("RESEARCH_PAPER", "https://example.com/p", payload))
            self.assertFalse(store.add("RESEARCH_PAPER", "https://example.com/p", payload))
            store.close()

    def test_directory_parser_supports_html_and_json(self) -> None:
        pages = {
            "https://example.com/acme": '<html><title>Acme AI</title><meta name="description" content="AI tools"></html>',
            "https://example.com/directory.json": '[{"name":"Beta Labs","description":"Research"}]',
        }
        records = parse_directory_pages(pages, entity_type="startup")
        self.assertEqual([record.name for record in records], ["Acme AI", "Beta Labs"])

    def test_product_pricing_requires_explicit_evidence(self) -> None:
        pages = {"https://example.com/products.json": "[{\"name\":\"Free Tool\",\"description\":\"Use it for free\"},{\"name\":\"Paid Tool\",\"description\":\"Pricing: Freemium (starter $9.99)\"},{\"name\":\"Unknown Tool\",\"description\":\"Built for product teams\"}]"}
        records = parse_directory_pages(pages, entity_type="product")
        self.assertEqual([record.pricing_model for record in records], ["FREE", "FREEMIUM", None])


if __name__ == "__main__":
    unittest.main()