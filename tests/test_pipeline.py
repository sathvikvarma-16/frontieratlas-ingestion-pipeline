import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.database import RecordStore
from src.llm.chunking import chunk_text
from src.resolver import EntityResolver
from src.scrapers.freshness import is_fresh, parse_relative_date
from src.scrapers.news_jobs import parse_feed, parse_typed_feed
from src.scrapers.startups import parse_directory_pages


class PipelineTests(unittest.TestCase):
    def test_fresh_feed_and_relative_date(self) -> None:
        now = datetime(2026, 9, 3, 12, tzinfo=timezone.utc)
        self.assertTrue(is_fresh(parse_relative_date("2 hours ago", now=now), now=now))
        xml = "<rss><channel><item><title>AI update</title><link>https://example.com/a</link><pubDate>Thu, 03 Sep 2026 11:00:00 GMT</pubDate></item></channel></rss>"
        self.assertEqual(len(parse_feed(xml, "https://example.com/feed", now=now)), 1)
        self.assertEqual(parse_typed_feed(xml, "https://example.com/feed", record_type="news", now=now)[0].recordType, "NEWS")
        self.assertEqual(parse_typed_feed(xml, "https://example.com/feed", record_type="job", now=now)[0].recordType, "JOB")

    def test_resolver_and_chunks(self) -> None:
        self.assertEqual(EntityResolver(["OpenAI"]).resolve("Open AI, Inc.").canonical_name, "OpenAI")
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


if __name__ == "__main__":
    unittest.main()