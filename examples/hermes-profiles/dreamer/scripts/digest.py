#!/usr/bin/env python3
"""digest.py — render the dreamer postcard for the operator."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402


def render_postcard(summary: dict) -> str:
    out = ["# Dreamer postcard"]
    out.append(f"_generated: {lib.now_iso()}_")
    out.append("")
    out.append(f"walks scanned: {summary.get('walks_scanned', 0)}")
    out.append(f"events extracted: {summary.get('events_extracted', 0)}")
    out.append("")
    lanes = summary.get("lanes", {})
    for lane in ("ready", "experiment", "watching"):
        items = lanes.get(lane, [])
        out.append(f"## {lane}  ({len(items)})")
        if not items:
            out.append("_empty_")
        else:
            for slug in items[:5]:
                info = summary.get("scored", {}).get(slug, {})
                out.append(f"- **{slug}** — {info.get('description', '')[:120]}")
        out.append("")
    if not lanes.get("ready"):
        out.append("_(nothing ready to promote yet — keep walking)_")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", choices=["postcard", "alert"], default="postcard")
    args = ap.parse_args()

    if not lib.SIGNAL_SUMMARY.exists():
        print("(no signal summary yet — run a walk first)")
        return 1
    summary = json.loads(lib.SIGNAL_SUMMARY.read_text())

    if args.tier == "postcard":
        print(render_postcard(summary))
    else:
        ready = summary.get("lanes", {}).get("ready", [])
        if ready:
            print(f"[dreamer] {len(ready)} card(s) ready: {', '.join(ready[:3])}")
        else:
            print("[dreamer] nothing ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
