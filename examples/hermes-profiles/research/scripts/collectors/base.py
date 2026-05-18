"""Collector base protocol — every collector implements this minimal interface."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class CollectorResult:
    """What a collector returns for one run."""
    collector_name: str
    items: list[dict] = field(default_factory=list)
    success: bool = True
    error: str | None = None
    items_collected: int = 0
    sources_scanned: int = 0
    duration_seconds: float = 0.0


class Collector(Protocol):
    """Anything that can pull external evidence."""

    name: str

    def collect(self, config: dict[str, Any], topics: list[str], max_items: int = 20) -> CollectorResult:
        """Run a collection pass.

        Args:
            config: collector-specific config (URLs, tokens, etc.)
            topics: interest-profile topic slugs (collectors may filter to these)
            max_items: hint at upper bound on items to return

        Returns CollectorResult with items in a normalized shape:
            {
                "source_id": stable id of the item,
                "source_type": "rss" | "github-release" | "blog" | ...,
                "url": canonical URL,
                "title": short title,
                "summary": short text,
                "captured_at": ISO timestamp,
                "topic_hints": [list of topics this might map to],
                "raw": original payload subset for LLM context,
            }
        """
        ...
