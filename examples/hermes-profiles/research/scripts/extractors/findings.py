"""Turn raw collector items into structured findings via LLM.

Strategy:
- Batch items per collector (10-20 per LLM call) to amortize overhead.
- Ask the LLM to score each item: is this a real signal worth tracking?
  Strength: weak | moderate | strong.
- Output is a list of findings ready for the knowledge ledger and a
  research-input artifact section.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# Path bootstrap so we can import the profile lib
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lib  # noqa: E402

EXTRACTION_PROMPT = """You are Goku's research-agent. You receive a batch of raw items (RSS posts,
GitHub releases, etc.) and must judge which ones are genuinely useful signals for the
operator's tracked topics.

For each item, decide:
- relevant: true/false  (is this a real signal for any tracked topic?)
- strength: "weak" | "moderate" | "strong" | "verified"
- topic: pick ONE topic slug from the provided list, or "_skip"
- summary: 1-2 sentences describing what the operator should know

Output JSON ONLY with this exact shape:
{
  "findings": [
    {
      "source_id": "...",                 // copy from input item.source_id
      "relevant": true,
      "strength": "moderate",
      "topic": "ai-agents",
      "summary": "..."
    },
    ...
  ]
}

Skip items that are not relevant by setting relevant=false (still include them).
Keep summaries concise. Do not invent facts beyond what the item says.
"""


def _batch(items: list[dict], size: int = 12):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def extract_findings(
    raw_items: list[dict],
    topics: list[str],
    model: str,
    batch_size: int = 12,
    max_tokens: int = 2000,
) -> list[dict]:
    """Run the LLM extractor over collected items. Returns list of findings ready for ledgers."""
    findings: list[dict] = []
    if not raw_items:
        return findings

    if not lib.is_provider_configured(model):
        # Without keys, fall back to no extraction (raw items still saved separately)
        return []

    for batch in _batch(raw_items, batch_size):
        items_payload = [
            {
                "source_id": it["source_id"],
                "title": it.get("title", "")[:300],
                "summary": it.get("summary", "")[:1000],
                "topic_hints": it.get("topic_hints", []),
            }
            for it in batch
        ]
        user = (
            f"Tracked topics (pick one or '_skip'): {topics}\n\n"
            f"Items:\n{json.dumps(items_payload, indent=2)[:8000]}"
        )
        try:
            resp = lib.call_model(
                model=model,
                messages=[
                    {"role": "system", "content": EXTRACTION_PROMPT},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
                max_tokens=max_tokens,
                json_mode=True,
                timeout=90,
            )
            decisions = json.loads(resp).get("findings", [])
        except (lib.LLMError, json.JSONDecodeError):
            continue

        # Index input items by source_id for lookup
        by_id = {it["source_id"]: it for it in batch}
        for d in decisions:
            sid = d.get("source_id")
            if not sid or not by_id.get(sid):
                continue
            if not d.get("relevant", False):
                continue
            topic = d.get("topic", "_skip")
            if topic == "_skip" or topic not in topics:
                continue
            item = by_id[sid]
            findings.append({
                "finding_id": "find-" + hashlib.sha256(sid.encode()).hexdigest()[:16],
                "topic": topic,
                "summary": (d.get("summary") or item.get("summary", ""))[:1000],
                "source": {
                    "source_id": sid,
                    "source_type": item.get("source_type", "external-url"),
                    "url": item.get("url", ""),
                    "excerpt": item.get("summary", "")[:1500],
                    "captured_at": item.get("captured_at") or lib.now_iso(),
                },
                "strength": d.get("strength", "weak"),
            })

    return findings
