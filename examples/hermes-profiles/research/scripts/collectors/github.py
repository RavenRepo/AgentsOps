"""GitHub collector — recent releases + recent activity for tracked orgs/repos."""
from __future__ import annotations

import hashlib
import os
import time
from typing import Any

import urllib.request
import urllib.error
import json

from .base import CollectorResult


GITHUB_API = "https://api.github.com"


def _github_get(path: str, token: str | None = None) -> dict | list | None:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "goku-vps-research-agent/0.1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{GITHUB_API}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        return None


class GithubCollector:
    name = "github"

    def collect(self, config: dict[str, Any], topics: list[str], max_items: int = 20) -> CollectorResult:
        token = os.environ.get("GITHUB_TOKEN")  # higher rate limit if set
        repos: list[dict] = config.get("repos", [])
        orgs: list[dict] = config.get("orgs", [])

        if not repos and not orgs:
            return CollectorResult(collector_name=self.name, success=True, sources_scanned=0)

        # Resolve org -> recent repos (limit 5 per org)
        for org_spec in orgs:
            org = org_spec.get("name")
            topic_hints = org_spec.get("topics", [])
            data = _github_get(f"/orgs/{org}/repos?sort=pushed&per_page=5", token)
            if isinstance(data, list):
                for r in data:
                    repos.append({"full_name": r.get("full_name"), "topics": topic_hints})

        items: list[dict] = []
        sources_scanned = 0
        t0 = time.time()
        for spec in repos[:30]:  # absolute cap
            full = spec.get("full_name")
            if not full:
                continue
            sources_scanned += 1
            topic_hints = spec.get("topics", [])

            # Recent releases (limit 3 per repo to keep volume sane)
            releases = _github_get(f"/repos/{full}/releases?per_page=3", token)
            if isinstance(releases, list):
                for r in releases:
                    rid = r.get("id")
                    if rid is None:
                        continue
                    source_id = f"gh-rel-{full.replace('/', '-')}-{rid}"
                    items.append({
                        "source_id": source_id,
                        "source_type": "github-release",
                        "url": r.get("html_url", ""),
                        "title": f"{full} {r.get('tag_name', '')}: {r.get('name', '')}"[:300],
                        "summary": (r.get("body") or "")[:2000],
                        "captured_at": r.get("published_at") or r.get("created_at") or "",
                        "topic_hints": topic_hints,
                        "raw": {
                            "repo": full,
                            "tag": r.get("tag_name"),
                            "draft": r.get("draft", False),
                            "prerelease": r.get("prerelease", False),
                        },
                    })

            if len(items) >= max_items:
                break

        return CollectorResult(
            collector_name=self.name,
            items=items[:max_items],
            success=True,
            items_collected=min(len(items), max_items),
            sources_scanned=sources_scanned,
            duration_seconds=round(time.time() - t0, 2),
        )
