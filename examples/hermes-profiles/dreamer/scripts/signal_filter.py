#!/usr/bin/env python3
"""
signal_filter.py — extract events from walks and update the signal board.

Deterministic. Does NOT call the LLM. Reads recent walks, scans for:
  - explicit [BUILD: slug] markers (commit signal)
  - excitement / friction / reuse / mention / return / cooling language
  - repeated mentions across walks (return signal)

Aggregates per-slug scores and writes:
  signal-state/signal-board.md      human-readable
  signal-state/summary.json         machine-readable

The result is read by promote.py to decide whether anything is in the ready lane.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402

# Signal-type weights (rough; tune as the room grows)
WEIGHTS = {
    "commit":      3.0,    # an explicit [BUILD: slug] marker
    "excitement":  1.5,    # excited language about an idea
    "friction":    1.5,    # pain points / desire to fix
    "reuse":       2.0,    # mention of using or reusing something existing
    "mention":     0.5,    # casual mention
    "return":      2.5,    # idea referenced in N+ separate walks
    "cooling":    -2.0,    # explicit "this isn't going anywhere" language
}

EXCITED_RE = re.compile(r"\b(excited|love|alive|brilliant|elegant|kills me)\b", re.I)
FRICTION_RE = re.compile(r"\b(annoy|broken|painful|wrong|frustrat|missing|gap)\b", re.I)
REUSE_RE = re.compile(r"\b(reuse|reused|replaces?|already\s+(have|built|exists?))\b", re.I)
COOLING_RE = re.compile(r"\b(cold|stale|abandon|dead|ghost|not\s+going\s+anywhere)\b", re.I)


def _walk_files() -> list[tuple[Path, Path]]:
    """Return list of (md_path, json_path) for every walk."""
    out = []
    for md in sorted(lib.WALKS_DIR.glob("*.md")):
        json_path = md.with_suffix(".json")
        if json_path.exists():
            out.append((md, json_path))
    return out


def _scan_walk(md_path: Path, json_path: Path) -> list[dict]:
    """Return signal events for one walk."""
    text = md_path.read_text()
    meta = json.loads(json_path.read_text())
    walk_id = meta["walk_id"]
    timestamp = meta.get("produced_at")

    events: list[dict] = []

    # Commit signals (explicit build markers)
    for m in re.finditer(r"\[BUILD:\s*([a-z0-9][a-z0-9-]+)\]\s*(.+)", text):
        events.append({
            "walk_id": walk_id, "at": timestamp,
            "type": "commit", "slug": m.group(1),
            "description": m.group(2).strip(),
        })

    # Mood signals — assigned to nearest build marker if any, else generic
    last_slug = events[-1]["slug"] if events else None
    for line in text.splitlines():
        slug_match = re.search(r"\[BUILD:\s*([a-z0-9-]+)\]", line)
        if slug_match:
            last_slug = slug_match.group(1)
            continue
        for kind, regex in [("excitement", EXCITED_RE), ("friction", FRICTION_RE),
                            ("reuse", REUSE_RE), ("cooling", COOLING_RE)]:
            if regex.search(line):
                events.append({
                    "walk_id": walk_id, "at": timestamp,
                    "type": kind, "slug": last_slug,
                    "evidence": line.strip()[:200],
                })

    return events


def _compute_returns(all_events: list[dict]) -> dict[str, int]:
    """For each slug, how many distinct walks mention it."""
    walks_per_slug: dict[str, set[str]] = defaultdict(set)
    for e in all_events:
        if e.get("slug"):
            walks_per_slug[e["slug"]].add(e["walk_id"])
    return {slug: len(walks) for slug, walks in walks_per_slug.items()}


def _score_per_slug(all_events: list[dict], returns: dict[str, int]) -> dict[str, dict]:
    """Aggregate score per slug along with signal types and walk count."""
    by_slug: dict[str, dict] = defaultdict(lambda: {
        "score": 0.0, "signal_types": set(), "walks": set(),
        "first_seen": None, "last_seen": None, "events": 0, "description": "",
    })

    for e in all_events:
        slug = e.get("slug")
        if not slug:
            continue
        info = by_slug[slug]
        info["score"] += WEIGHTS.get(e["type"], 0.0)
        info["signal_types"].add(e["type"])
        info["walks"].add(e["walk_id"])
        info["events"] += 1
        if e.get("at"):
            if info["first_seen"] is None or e["at"] < info["first_seen"]:
                info["first_seen"] = e["at"]
            if info["last_seen"] is None or e["at"] > info["last_seen"]:
                info["last_seen"] = e["at"]
        if e["type"] == "commit" and e.get("description"):
            info["description"] = e["description"]

    # Add return-signal contribution
    for slug, n_walks in returns.items():
        if n_walks >= 2:
            by_slug[slug]["score"] += WEIGHTS["return"] * (n_walks - 1)
            by_slug[slug]["signal_types"].add("return")

    # Convert sets to lists for JSON serialization
    for slug, info in by_slug.items():
        info["signal_types"] = sorted(info["signal_types"])
        info["positive_walks"] = len(info["walks"])
        info["walks"] = sorted(info["walks"])

    return dict(by_slug)


def _classify_lanes(scored: dict[str, dict], config: dict) -> dict[str, list[str]]:
    """Bucket slugs into watching / ready / experiment lanes based on thresholds."""
    rt = config["ready_thresholds"]
    et = config["experiment_thresholds"]
    lanes: dict[str, list[str]] = {"ready": [], "experiment": [], "watching": [], "ghost": []}

    for slug, info in scored.items():
        if info["score"] < 0:
            lanes["ghost"].append(slug)
            continue
        meets_ready = (
            info["score"] >= rt["min_score"]
            and info["positive_walks"] >= rt["min_positive_walks"]
            and len(info["signal_types"]) >= rt["min_signal_types"]
        )
        meets_experiment = (
            info["score"] >= et["min_score"]
            and info["positive_walks"] >= et["min_positive_walks"]
        )
        if meets_ready:
            lanes["ready"].append(slug)
        elif meets_experiment:
            lanes["experiment"].append(slug)
        else:
            lanes["watching"].append(slug)

    for k in lanes:
        lanes[k].sort(key=lambda s: -scored[s]["score"])
    return lanes


def _render_board(scored: dict[str, dict], lanes: dict[str, list[str]]) -> str:
    out = ["# Signal board", ""]
    out.append(f"_generated: {lib.now_iso()}_")
    out.append("")
    for lane in ("ready", "experiment", "watching", "ghost"):
        items = lanes[lane]
        out.append(f"## {lane}  ({len(items)})")
        if not items:
            out.append("  _empty_")
        else:
            for slug in items:
                info = scored[slug]
                out.append(
                    f"- **{slug}**  score: {info['score']:.1f} · "
                    f"types: {', '.join(info['signal_types'])} · "
                    f"walks: {info['positive_walks']}"
                )
                if info["description"]:
                    out.append(f"  _{info['description']}_")
        out.append("")
    return "\n".join(out)


def main() -> int:
    config = lib.load_profile_config(lib.PROFILE_ROOT)
    lib.ensure_dirs()

    walks = _walk_files()
    if not walks:
        print("[signal-filter] no walks yet")
        return 0

    all_events: list[dict] = []
    for md, jp in walks:
        events = _scan_walk(md, jp)
        all_events.extend(events)
        # Per-walk signal log
        log_path = lib.SIGNAL_LOG_DIR / f"{jp.stem}.json"
        lib.write_json_atomic(log_path, events)

    returns = _compute_returns(all_events)
    scored = _score_per_slug(all_events, returns)
    lanes = _classify_lanes(scored, config)

    summary = {
        "generated_at": lib.now_iso(),
        "walks_scanned": len(walks),
        "events_extracted": len(all_events),
        "lanes": lanes,
        "scored": scored,
    }
    lib.write_json_atomic(lib.SIGNAL_SUMMARY, summary)
    lib.write_atomic(lib.SIGNAL_BOARD_MD, _render_board(scored, lanes))

    print(f"[signal-filter] walks={len(walks)} events={len(all_events)} "
          f"ready={len(lanes['ready'])} experiment={len(lanes['experiment'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
