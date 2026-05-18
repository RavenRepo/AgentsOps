"""RSS feed collector using feedparser."""
from __future__ import annotations

import hashlib
import time
from typing import Any

from .base import CollectorResult


class RssCollector:
    name = "rss"

    def collect(self, config: dict[str, Any], topics: list[str], max_items: int = 20) -> CollectorResult:
        try:
            import feedparser  # type: ignore[import-untyped]
        except ImportError:
            return CollectorResult(
                collector_name=self.name, success=False,
                error="feedparser not installed (uv pip install feedparser)",
            )

        feeds: list[dict] = config.get("feeds", [])
        if not feeds:
            return CollectorResult(collector_name=self.name, success=True, sources_scanned=0)

        items: list[dict] = []
        sources_scanned = 0
        t0 = time.time()
        for feed_spec in feeds:
            url = feed_spec.get("url")
            if not url:
                continue
            sources_scanned += 1
            topic_hints = feed_spec.get("topics", [])
            try:
                parsed = feedparser.parse(url)
            except Exception:
                continue

            entries = list(getattr(parsed, "entries", []))[:max_items]
            for entry in entries:
                eid = entry.get("id") or entry.get("link") or entry.get("title", "")
                if not eid:
                    continue
                source_id = "rss-" + hashlib.sha256(eid.encode("utf-8")).hexdigest()[:16]
                summary = (entry.get("summary") or entry.get("description") or "")[:1500]
                published = entry.get("published") or entry.get("updated") or ""
                items.append({
                    "source_id": source_id,
                    "source_type": "rss",
                    "url": entry.get("link", ""),
                    "title": entry.get("title", "")[:300],
                    "summary": summary,
                    "captured_at": published,
                    "topic_hints": topic_hints,
                    "raw": {
                        "feed_url": url,
                        "feed_title": getattr(parsed.feed, "title", "") if hasattr(parsed, "feed") else "",
                        "author": entry.get("author", ""),
                    },
                })

        return CollectorResult(
            collector_name=self.name,
            items=items,
            success=True,
            items_collected=len(items),
            sources_scanned=sources_scanned,
            duration_seconds=round(time.time() - t0, 2),
        )
