"""Collector registry — name -> collector instance."""
from .base import CollectorResult, Collector
from .rss import RssCollector
from .github import GithubCollector


def all_collectors() -> dict[str, Collector]:
    return {
        "rss": RssCollector(),
        "github": GithubCollector(),
    }


__all__ = ["CollectorResult", "Collector", "all_collectors"]
