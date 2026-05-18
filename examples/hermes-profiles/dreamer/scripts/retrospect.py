#!/usr/bin/env python3
"""
retrospect.py — write a per-walk retrospective and tend the room's
long-lived files (fascinations.md, lessons.md).

This is what makes the dreamer compound walk-over-walk. Without it, every
walk starts cold. With it, the next walk reads:
- the most recent retrospectives (what was just noticed)
- fascinations.md (themes that keep returning)
- lessons.md (things we learned from past builds + post-mortems)

Run this AFTER a walk + signal_filter completes. It will:
  1. Read the latest walk note + signal-state/summary.json
  2. Read the last few retrospectives + fascinations + lessons (priors)
  3. Ask the LLM to produce JSON with three sections:
        retrospective  — short reflection on this walk
        fascinations   — top 5-10 themes that keep returning
        lesson         — at most one new dated lesson, or null
  4. Write retrospectives/<walk_id>.md (one file per walk)
     Overwrite fascinations.md (kept tidy by always limiting top-N)
     Append a new dated entry to lessons.md if a lesson emerged

Usage:
    python scripts/retrospect.py                  # auto: pick latest walk
    python scripts/retrospect.py --walk-id <id>   # specific walk
    python scripts/retrospect.py --dry-run        # don't call LLM, no writes
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402

MAX_FASCINATIONS = 10
MAX_PRIOR_RETROS = 4


def _latest_walk_id() -> str | None:
    walks = sorted(lib.WALKS_DIR.glob("*.json"), reverse=True)
    if not walks:
        return None
    return walks[0].stem


def _read_walk(walk_id: str) -> tuple[str, dict] | None:
    md_path, json_path, _ = lib.walk_paths(walk_id)
    if not md_path.exists():
        return None
    body = md_path.read_text()
    meta = {}
    if json_path.exists():
        try:
            meta = json.loads(json_path.read_text())
        except json.JSONDecodeError:
            meta = {}
    return body, meta


def _prior_retrospectives(n: int = MAX_PRIOR_RETROS, exclude_walk_id: str | None = None) -> str:
    files = sorted(lib.RETROSPECTIVES_DIR.glob("*.md"), reverse=True)
    items: list[str] = []
    for f in files:
        if exclude_walk_id and f.stem == exclude_walk_id:
            continue
        items.append(f"### {f.stem}\n{f.read_text()[:1000]}")
        if len(items) >= n:
            break
    return "\n\n".join(items) if items else "(no prior retrospectives yet)"


def _read_signal_summary() -> dict:
    if not lib.SIGNAL_SUMMARY.exists():
        return {}
    try:
        return json.loads(lib.SIGNAL_SUMMARY.read_text())
    except json.JSONDecodeError:
        return {}


def _build_messages(walk_body: str, walk_meta: dict, summary: dict, soul: str) -> list[dict]:
    fasc = lib.FASCINATIONS_MD.read_text() if lib.FASCINATIONS_MD.exists() else ""
    lessons = lib.LESSONS_MD.read_text() if lib.LESSONS_MD.exists() else ""
    priors = _prior_retrospectives(exclude_walk_id=walk_meta.get("walk_id"))
    walk_id = walk_meta.get("walk_id", "<unknown>")
    mode = walk_meta.get("mode", "<unknown>")
    build_markers = walk_meta.get("build_markers", [])

    system = (
        f"{soul}\n\n"
        "You are now writing a RETROSPECTIVE for a walk you just took. This is "
        "internal to your room — not a postcard, not a summary for the operator. "
        "You are talking to your future self.\n\n"
        "Goals:\n"
        " - Note what CAUGHT (what you returned to or noticed harder than expected)\n"
        " - Note what feels REPEATED versus what feels FRESH\n"
        " - Note what's getting STALE — fascinations to abandon, projects to ghost\n"
        " - Decide if this walk yielded an actual LESSON (rare). Most walks don't.\n\n"
        "Output JSON ONLY with this exact shape:\n"
        "{\n"
        "  \"retrospective\": \"<150-400 word markdown reflection>\",\n"
        "  \"fascinations\": [\n"
        "    {\"theme\": \"short title\", \"why\": \"why it keeps catching\", \"first_noticed\": \"YYYY-MM-DD\", \"last_seen\": \"YYYY-MM-DD\"}\n"
        "  ],\n"
        "  \"lesson\": \"<single sentence lesson, OR null if this walk did not yield a real lesson>\",\n"
        "  \"abandon\": [\"theme-name-or-slug\"]   // optional: themes/slugs that have gone stale\n"
        "}\n"
        f"Limit fascinations to top {MAX_FASCINATIONS}. PRESERVE existing fascinations from below "
        "if they are still alive — bump their last_seen to today only if this walk touched them. "
        "Do not invent fake first_noticed dates."
    )

    walk_packet = {
        "walk_id": walk_id,
        "mode": mode,
        "build_markers": build_markers,
        "elapsed_seconds": walk_meta.get("elapsed_seconds"),
        "word_count": walk_meta.get("word_count"),
    }
    summary_compact = {
        "lanes": {k: v for k, v in (summary.get("lanes") or {}).items() if v},
        "scored_top": dict(list((summary.get("scored") or {}).items())[:8]),
    }

    user = (
        f"Walk just taken (`{walk_id}`):\n\n"
        f"```md\n{walk_body[:4000]}\n```\n\n"
        f"Walk metadata:\n```json\n{json.dumps(walk_packet, indent=2)}\n```\n\n"
        f"Signal summary after this walk:\n```json\n{json.dumps(summary_compact, indent=2)[:2000]}\n```\n\n"
        f"Existing fascinations (current top-N):\n{fasc[:1500]}\n\n"
        f"Past lessons (most recent at bottom):\n{lessons[:1500]}\n\n"
        f"Recent retrospectives:\n{priors[:2500]}\n\n"
        "Now write the retrospective. Be honest. If the walk was thin, say so."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _render_fascinations(fascinations: list[dict]) -> str:
    fascinations = fascinations[:MAX_FASCINATIONS]
    out = ["# Fascinations", "",
           f"_Updated: {lib.now_iso()}_", ""]
    if not fascinations:
        out.append("_(empty)_")
        return "\n".join(out) + "\n"
    for f in fascinations:
        theme = (f.get("theme") or "").strip()
        why = (f.get("why") or "").strip()
        first = (f.get("first_noticed") or "").strip()
        last = (f.get("last_seen") or "").strip()
        if not theme:
            continue
        out.append(f"## {theme}")
        if why:
            out.append(f"- {why}")
        if first or last:
            out.append(f"- _first noticed_: `{first or '?'}` · _last seen_: `{last or '?'}`")
        out.append("")
    return "\n".join(out) + "\n"


def _append_lesson(lesson: str | None, walk_id: str) -> bool:
    """Append a new dated lesson if one emerged. Returns True if appended."""
    if not lesson or not lesson.strip() or lesson.strip().lower() == "null":
        return False
    line = f"- {_today()}: {lesson.strip()}  _(from walk {walk_id})_\n"
    # Append in place. The file already has a header.
    with lib.LESSONS_MD.open("a") as f:
        f.write(line)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--walk-id", help="walk id to retrospect on (default: latest)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config = lib.load_profile_config(lib.PROFILE_ROOT)
    lib.ensure_dirs()

    walk_id = args.walk_id or _latest_walk_id()
    if not walk_id:
        print(json.dumps({"result": "skipped", "reason": "no walks yet"}))
        return 0

    walk = _read_walk(walk_id)
    if walk is None:
        print(json.dumps({"result": "fail", "reason": f"walk {walk_id} not found"}))
        return 1
    walk_body, walk_meta = walk

    # Resolve model: prefer retrospect-specific, then synthesis, then any walk model
    model = (
        config["models"].get("retrospect")
        or config["models"].get("synthesis")
        or config["models"].get("walk_drift")
        or config["models"].get("default")
    )
    if not model:
        print(json.dumps({"result": "fail", "reason": "no model configured"}))
        return 1

    soul_path = lib.PROFILE_ROOT / "SOUL.md"
    soul = soul_path.read_text() if soul_path.exists() else ""

    summary = _read_signal_summary()
    messages = _build_messages(walk_body, walk_meta, summary, soul)

    if args.dry_run:
        out_path = lib.retrospective_path(walk_id)
        print(json.dumps({"result": "dry-run", "walk_id": walk_id,
                          "would_call": model,
                          "would_write": str(out_path.relative_to(lib.PROFILE_ROOT))}))
        return 0

    if not lib.is_provider_configured(model):
        print(json.dumps({"result": "skipped",
                          "reason": f"provider not configured for {model}",
                          "walk_id": walk_id}))
        return 0

    try:
        resp = lib.call_model(
            model=model,
            messages=messages,
            temperature=0.4,
            max_tokens=2000,
            json_mode=True,
            timeout=120,
        )
    except lib.LLMError as e:
        print(json.dumps({"result": "fail", "reason": f"LLM error: {e}",
                          "walk_id": walk_id}))
        return 1

    try:
        data = json.loads(resp)
    except json.JSONDecodeError:
        # Salvage: put the raw response in the retrospective body
        data = {"retrospective": resp[:4000], "fascinations": [], "lesson": None, "abandon": []}

    retrospective_md = (data.get("retrospective") or "").strip() or "_(empty retrospective)_"
    fascinations = data.get("fascinations") or []
    lesson = data.get("lesson")
    abandoned = data.get("abandon") or []

    # Write the per-walk retrospective
    out = lib.retrospective_path(walk_id)
    header = (
        f"---\n"
        f"walk_id: {walk_id}\n"
        f"produced_at: {lib.now_iso()}\n"
        f"model: {model}\n"
        f"---\n\n"
    )
    lib.write_atomic(out, header + retrospective_md + "\n")

    # Update fascinations.md (overwrite — agent maintains the canonical list)
    lib.write_atomic(lib.FASCINATIONS_MD, _render_fascinations(fascinations))

    # Append a lesson if any
    appended_lesson = _append_lesson(lesson, walk_id)

    print(json.dumps({
        "result": "ok",
        "walk_id": walk_id,
        "wrote": str(out.relative_to(lib.PROFILE_ROOT)),
        "fascinations_count": min(len(fascinations), MAX_FASCINATIONS),
        "lesson_appended": appended_lesson,
        "abandoned": abandoned,
        "model": model,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
