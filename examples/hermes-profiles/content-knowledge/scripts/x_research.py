"""
x_research.py — collect X intel using the v2 search/recent + users endpoints.

Hard rule: this module reads X. It does NOT post. Posting is content-poster's job.
This module DOES NOT use Grok. Grok is reserved for the X drafter (content-studio).
This module uses NVIDIA Llama 8B (free) for finding extraction.

Inputs:
  - X_BEARER_TOKEN (required for live search)
  - HERMES_MODEL_X_RESEARCH (default: nvidia/meta/llama-3.1-8b-instruct)

Outputs:
  - content-vault/x-vault/raw/<run-id>/search-<keyword>.json
  - content-vault/x-vault/raw/<run-id>/competitors.json
  - content-vault/x-vault/findings.jsonl (append)
  - content-vault/x-vault/sources.jsonl (append)
  - content-vault/x-vault/algo-watch.jsonl (append) — when finding categorized as algo signal

Reads:
  - content-vault/x-vault/x-source-plan.yaml — keywords + competitor handles
    (auto-bootstrapped on first run from interest-profile if missing)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402

# X v2 API
X_API_ROOT = "https://api.twitter.com/2"
SEARCH_RECENT = X_API_ROOT + "/tweets/search/recent"
USER_BY_USERNAME = X_API_ROOT + "/users/by/username"
USER_TWEETS = X_API_ROOT + "/users/{id}/tweets"

# Defaults — can be overridden by x-source-plan.yaml
DEFAULT_KEYWORDS = [
    "AI agents",
    "agent orchestration",
    "LLM engineering",
    "multi-agent",
    "SaaS MVP",
    "developer tooling",
]
DEFAULT_COMPETITORS: list[str] = []  # empty until operator nominates real ones


def _bearer() -> str:
    return (os.environ.get("X_BEARER_TOKEN") or "").strip()


def _have_bearer() -> bool:
    return bool(_bearer())


def _http_get(url: str, *, params: dict | None = None, timeout: int = 30) -> dict:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={
            "Authorization": f"Bearer {_bearer()}",
            "Accept": "application/json",
            "User-Agent": "goku-x-research/0.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return {"_error": f"HTTP {e.code}", "_body": body[:600]}
    except urllib.error.URLError as e:
        return {"_error": f"network: {e}"}


# ---------------------------------------------------------------------------
# Source plan (keywords + competitor handles)
# ---------------------------------------------------------------------------

def _source_plan_path() -> Path:
    return lib.vault_dir("x") / "x-source-plan.yaml"


def _load_source_plan() -> dict:
    path = _source_plan_path()
    if not path.exists():
        return {"keywords": DEFAULT_KEYWORDS, "competitors": DEFAULT_COMPETITORS}
    try:
        import yaml  # type: ignore[import-untyped]
        data = yaml.safe_load(path.read_text()) or {}
        return {
            "keywords": data.get("keywords", DEFAULT_KEYWORDS),
            "competitors": data.get("competitors", DEFAULT_COMPETITORS),
        }
    except Exception:
        return {"keywords": DEFAULT_KEYWORDS, "competitors": DEFAULT_COMPETITORS}


def _ensure_source_plan_seed() -> None:
    path = _source_plan_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    seed = (
        "# x-source-plan.yaml — keywords + competitor handles for x-research.\n"
        "# Edit freely. The collector reads this every run.\n\n"
        "keywords:\n"
        + "\n".join(f"  - \"{k}\"" for k in DEFAULT_KEYWORDS)
        + "\n\n"
        "# Add 3-5 competitor handles to track (without @).\n"
        "competitors: []\n"
        "# Example:\n"
        "# competitors:\n"
        "#   - simonw\n"
        "#   - swyx\n"
        "#   - karpathy\n"
    )
    path.write_text(seed)


# ---------------------------------------------------------------------------
# X v2 search
# ---------------------------------------------------------------------------

def _search_recent(query: str, max_results: int = 25) -> dict:
    """X v2 GET /tweets/search/recent.

    Asks for impressions + public_metrics + author info so we can score.
    """
    params = {
        "query": f"({query}) lang:en -is:retweet",
        "max_results": str(min(max(max_results, 10), 100)),
        "tweet.fields": "created_at,public_metrics,context_annotations,lang,possibly_sensitive,author_id",
        "expansions": "author_id",
        "user.fields": "username,name,public_metrics,verified",
    }
    return _http_get(SEARCH_RECENT, params=params)


def _user_by_username(username: str) -> dict:
    params = {"user.fields": "public_metrics,verified,description,location,created_at"}
    return _http_get(f"{USER_BY_USERNAME}/{username}", params=params)


def _user_tweets(user_id: str, max_results: int = 10) -> dict:
    params = {
        "max_results": str(min(max(max_results, 5), 100)),
        "tweet.fields": "created_at,public_metrics,context_annotations,lang",
        "exclude": "retweets,replies",
    }
    return _http_get(USER_TWEETS.format(id=user_id), params=params)


# ---------------------------------------------------------------------------
# Finding extraction (uses NVIDIA Llama 8B — NOT Grok)
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """You are a research analyst extracting signals from X (Twitter) posts about a content niche.

For each tweet you receive, decide:
- relevant: true/false  (does it teach something useful for someone writing on AI agents / LLM eng / SaaS MVPs / dev tooling?)
- strength: weak | moderate | strong | verified
- topic: one of: ai-agents, llm-engineering, multi-agent, saas-mvp, developer-tooling, algo-signal, _skip
- summary: ONE sentence (max 240 chars) capturing what an operator should remember

Algo-signal: tweets about X's algorithm, creator economy, monetization changes, posting cadence advice.

Output JSON with shape:
{
  "findings": [
    {"tweet_id": "...", "relevant": true, "strength": "moderate", "topic": "ai-agents", "summary": "..."}
  ]
}
Skip irrelevant tweets by setting relevant=false (still include them).
Do not invent facts beyond the tweet text.
"""


def _batch(items: list[dict], n: int = 12):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _extract_findings_from_tweets(tweets: list[dict], users_by_id: dict, model: str) -> list[dict]:
    if not tweets:
        return []
    if not lib.is_provider_configured(model):
        return []
    findings: list[dict] = []
    for batch in _batch(tweets, 12):
        items = []
        for t in batch:
            uid = t.get("author_id")
            handle = (users_by_id.get(uid) or {}).get("username", "unknown")
            items.append({
                "tweet_id": t.get("id"),
                "handle": handle,
                "text": (t.get("text") or "")[:600],
                "metrics": t.get("public_metrics") or {},
                "created_at": t.get("created_at"),
            })
        try:
            resp = lib.call_model(
                model=model,
                messages=[
                    {"role": "system", "content": EXTRACTION_PROMPT},
                    {"role": "user", "content": json.dumps(items, indent=2)[:7000]},
                ],
                temperature=0.1,
                max_tokens=2000,
                json_mode=True,
                timeout=90,
            )
            decisions = json.loads(resp).get("findings", [])
        except (lib.LLMError, json.JSONDecodeError):
            continue

        by_id = {it["tweet_id"]: it for it in items}
        for d in decisions:
            tid = d.get("tweet_id")
            if not tid or tid not in by_id:
                continue
            if not d.get("relevant", False):
                continue
            it = by_id[tid]
            topic = d.get("topic", "_skip")
            if topic == "_skip":
                continue
            findings.append({
                "finding_id": "find-" + hashlib.sha256(f"x-{tid}".encode()).hexdigest()[:16],
                "topic": topic,
                "summary": (d.get("summary") or it["text"])[:1000],
                "strength": d.get("strength", "weak"),
                "source": {
                    "source_id": f"x-{tid}",
                    "source_type": "x",
                    "url": f"https://x.com/{it['handle']}/status/{tid}",
                    "excerpt": it["text"][:1500],
                    "captured_at": it.get("created_at") or lib.now_iso(),
                },
                "metrics": it["metrics"],
                "handle": it["handle"],
            })
    return findings


# ---------------------------------------------------------------------------
# Main entry — refresh-x mode
# ---------------------------------------------------------------------------

def run_refresh_x(profile_root: Path) -> dict:
    """Public entry. Returns a receipt dict."""
    lib.ensure_dirs()
    _ensure_source_plan_seed()

    if not _have_bearer():
        return {
            "mode": "refresh-x",
            "result": "skipped",
            "reason": "X_BEARER_TOKEN not set; cannot reach X v2 API",
        }

    plan = _load_source_plan()
    keywords = plan.get("keywords") or DEFAULT_KEYWORDS
    competitors = plan.get("competitors") or []

    run_id = lib.now_run_id()
    raw_dir = lib.vault_dir("x") / "raw" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)

    all_tweets: list[dict] = []
    users_by_id: dict[str, dict] = {}
    keyword_results: dict[str, dict] = {}
    competitor_results: dict[str, dict] = {}

    # 1. Search recent for each keyword
    for kw in keywords[:8]:
        data = _search_recent(kw, max_results=25)
        keyword_results[kw] = {
            "ok": "_error" not in data,
            "error": data.get("_error"),
            "tweet_count": len(data.get("data") or []),
        }
        if data.get("_error"):
            continue
        # Save raw
        (raw_dir / f"search-{_safe_filename(kw)}.json").write_text(json.dumps(data, indent=2))
        for u in data.get("includes", {}).get("users", []) or []:
            users_by_id[u["id"]] = u
        all_tweets.extend(data.get("data") or [])
        time.sleep(1)  # gentle on rate limit

    # 2. Pull each competitor's recent tweets
    for handle in competitors[:6]:
        u = _user_by_username(handle)
        if "_error" in u or not u.get("data"):
            competitor_results[handle] = {"ok": False, "error": u.get("_error") or "no data"}
            continue
        uid = u["data"]["id"]
        users_by_id[uid] = u["data"]
        tw = _user_tweets(uid, max_results=10)
        if "_error" in tw:
            competitor_results[handle] = {"ok": False, "error": tw["_error"]}
            continue
        competitor_results[handle] = {
            "ok": True, "user_id": uid, "tweet_count": len(tw.get("data") or []),
        }
        (raw_dir / f"competitor-{handle}.json").write_text(json.dumps(tw, indent=2))
        all_tweets.extend(tw.get("data") or [])
        time.sleep(1)

    # 3. De-dup tweets by id
    seen_ids: set[str] = set()
    deduped: list[dict] = []
    for t in all_tweets:
        tid = t.get("id")
        if not tid or tid in seen_ids:
            continue
        seen_ids.add(tid)
        deduped.append(t)

    # 4. Extract findings (NVIDIA Llama, not Grok)
    extractor_model = os.environ.get("HERMES_MODEL_X_RESEARCH",
                                      "nvidia/meta/llama-3.1-8b-instruct")
    findings = _extract_findings_from_tweets(deduped, users_by_id, extractor_model)

    # 5. Append to ledgers
    for f in findings:
        lib.append_jsonl(lib.findings_ledger("x"), f)
        src = f["source"]
        lib.append_jsonl(lib.sources_ledger("x"), {
            "source_id": src["source_id"],
            "source_type": src["source_type"],
            "url": src["url"],
            "captured_at": src["captured_at"],
            "topic": f["topic"],
            "first_seen_run": run_id,
            "handle": f.get("handle"),
            "metrics": f.get("metrics"),
        })
        if f["topic"] == "algo-signal":
            lib.append_jsonl(lib.algo_watch_ledger("x"), {
                "captured_at": src["captured_at"],
                "summary": f["summary"],
                "url": src["url"],
                "handle": f.get("handle"),
                "strength": f["strength"],
            })

    receipt = {
        "mode": "refresh-x",
        "result": "ok",
        "run_id": run_id,
        "tweets_collected": len(deduped),
        "findings_extracted": len(findings),
        "algo_signals": sum(1 for f in findings if f["topic"] == "algo-signal"),
        "keyword_results": keyword_results,
        "competitor_results": competitor_results,
        "extractor_model": extractor_model,
    }
    lib.write_json_atomic(raw_dir / "receipt.json", receipt)
    return receipt


def _safe_filename(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in s)[:60]


# CLI for ad-hoc testing
if __name__ == "__main__":
    print(json.dumps(run_refresh_x(lib.PROFILE_ROOT), indent=2))
