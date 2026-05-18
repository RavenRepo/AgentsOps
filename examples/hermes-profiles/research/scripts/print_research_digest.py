#!/usr/bin/env python3
"""
print_research_digest.py — render the human-facing research digest.

Reads the most recent research-input artifact + operator-brief, formats it for
the requested tier, and prints to stdout. Designed for cron delivery.

  --tier operator  : full daily digest for the human (default)
  --tier subc      : compact pattern-facing brief for the dreamer
  --tier brief     : one-paragraph summary for an alerts channel
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make `lib.*` importable
_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402


def find_latest_research_input() -> Path | None:
    candidates = sorted(lib.VAULT.glob("*.research-input.json"), reverse=True)
    return candidates[0] if candidates else None


def render_operator(artifact: dict) -> str:
    lines = []
    lines.append(f"# Research digest — {artifact.get('produced_at', 'unknown')}")
    lines.append("")
    lines.append(artifact.get("summary", "(no summary)"))
    lines.append("")
    topics = artifact.get("topics", [])
    if topics:
        lines.append("## Topics")
        for t in topics:
            lines.append(f"- **{t['topic']}** — {t.get('findings_count', 0)} findings, "
                         f"{t.get('claims_count', 0)} claims, "
                         f"{t.get('verification_pending', 0)} pending")
    new_findings = artifact.get("new_findings", [])
    if new_findings:
        lines.append("")
        lines.append("## New findings")
        for f in new_findings[:10]:
            strength = f.get("strength", "?")
            lines.append(f"- [{strength}] {f.get('summary', '')[:200]}")
    handoffs = artifact.get("handoffs", {})
    if any(handoffs.values()):
        lines.append("")
        lines.append("## Routing")
        for lane, items in handoffs.items():
            for it in items:
                lines.append(f"- → **{lane}**: {it}")
    sq = artifact.get("source_quality", {})
    if sq.get("degraded_collectors"):
        lines.append("")
        lines.append("## Degraded collectors")
        for c in sq["degraded_collectors"]:
            lines.append(f"- {c}")
    return "\n".join(lines)


def render_subc(artifact: dict) -> str:
    """Compact, pattern-oriented version for the dreamer."""
    lines = []
    lines.append(f"# subc brief — {artifact.get('produced_at', 'unknown')}")
    lines.append("")
    lines.append(artifact.get("summary", ""))
    lines.append("")
    handoffs = artifact.get("handoffs", {})
    to_dreamer = handoffs.get("to_dreamer", [])
    if to_dreamer:
        lines.append("## Worth noticing")
        for item in to_dreamer:
            lines.append(f"- {item}")
    return "\n".join(lines)


def render_brief(artifact: dict) -> str:
    """One paragraph for an alerts channel."""
    summary = artifact.get("summary", "")
    deg = artifact.get("source_quality", {}).get("degraded_collectors", [])
    parts = [summary]
    if deg:
        parts.append(f"Degraded: {', '.join(deg)}.")
    return " ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tier", choices=["operator", "subc", "brief"], default="operator")
    ap.add_argument("--input", type=Path, help="explicit research-input.json path")
    args = ap.parse_args()

    path = args.input or find_latest_research_input()
    if path is None:
        print("(no research-input artifacts found yet)", file=sys.stderr)
        return 1
    with path.open() as f:
        artifact = json.load(f)

    renderers = {
        "operator": render_operator,
        "subc":     render_subc,
        "brief":    render_brief,
    }
    print(renderers[args.tier](artifact))
    return 0


if __name__ == "__main__":
    sys.exit(main())
