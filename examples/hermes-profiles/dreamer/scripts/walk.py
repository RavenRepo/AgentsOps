#!/usr/bin/env python3
"""
walk.py — go on a walk in one of the four modes.

Each walk:
  1. Picks a walk-mode-specific model from config
  2. Builds context: SOUL.md + recent walks + lessons + (mode-specific input)
  3. Calls the LLM to write a walk note
  4. Saves the note to room/walks/<id>.md plus a metadata JSON
  5. Optionally runs the signal filter immediately

Usage:
    python scripts/walk.py --mode drift_from_research
    python scripts/walk.py --mode pure_tangent --no-filter
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402

WALK_MODES = ["drift_from_research", "continue_project", "pure_tangent", "tend_the_room"]


def _load_recent_walks(n: int = 5) -> str:
    """Return concatenated content of the last n walks (md only) for context."""
    walks = sorted(lib.WALKS_DIR.glob("*.md"), reverse=True)[:n]
    if not walks:
        return "(no prior walks yet)"
    parts = []
    for w in walks:
        parts.append(f"### {w.stem}\n{w.read_text()[:2000]}")
    return "\n\n".join(parts)


def _load_latest_research_input() -> dict | None:
    """Find the most recent research-input from the inbox or research-agent vault."""
    candidates = []
    candidates.extend(lib.INBOX_DIR.glob("*.research-input.json"))
    research_vault = Path("os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/hermes/workspace/profiles/research/workspace/research-vault")
    candidates.extend(research_vault.glob("*.research-input.json"))
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    try:
        return json.loads(candidates[0].read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _load_projects_summary() -> str:
    if not lib.PROJECTS_DIR.exists():
        return "(no projects)"
    files = list(lib.PROJECTS_DIR.glob("*.md"))
    if not files:
        return "(no projects)"
    parts = []
    for p in files[:10]:
        parts.append(f"- {p.stem}: {p.read_text()[:300]}")
    return "\n".join(parts)


def _load_long_term_context() -> str:
    """Always-on room context: fascinations, lessons, most recent retrospective.

    This is what makes the dreamer compound walk-over-walk. Every walk mode
    sees this — not just tend_the_room.
    """
    parts = []
    if lib.FASCINATIONS_MD.exists():
        parts.append("Fascinations (themes that keep returning):\n"
                     + lib.FASCINATIONS_MD.read_text()[:1500])
    if lib.LESSONS_MD.exists():
        parts.append("Lessons (what past walks taught us):\n"
                     + lib.LESSONS_MD.read_text()[:1200])
    retros = sorted(lib.RETROSPECTIVES_DIR.glob("*.md"), reverse=True)
    if retros:
        parts.append("Most recent retrospective (your prior self thinking):\n"
                     + retros[0].read_text()[:1200])
    return "\n\n---\n\n".join(parts) if parts else "(room is fresh — no fascinations, lessons or retrospectives yet)"


def _build_messages(mode: str, soul: str) -> list[dict]:
    long_term = _load_long_term_context()
    common = (
        f"{soul}\n\n"
        f"---\n"
        f"Long-term room context (always read, regardless of walk mode):\n\n"
        f"{long_term}\n"
        f"---\n\n"
        f"You are about to go on a `{mode}` walk. Write a walk note in markdown.\n"
        f"Length: 200-700 words. Be honest. If nothing is alive, say so and stop.\n"
        f"You may leave build markers like:  [BUILD: project-slug] one-line description\n"
        f"Do not summarize for its own sake. Notice what catches.\n"
    )
    if mode == "drift_from_research":
        ri = _load_latest_research_input()
        ri_text = json.dumps(ri, indent=2)[:4000] if ri else "(no research input available yet)"
        recent = _load_recent_walks()
        user = (
            "Latest research input snapshot:\n"
            f"```json\n{ri_text}\n```\n\n"
            "Recent walks (for context):\n"
            f"{recent[:3000]}\n\n"
            "Drift from this. You don't have to summarize the research — let one signal catch you and follow it."
        )
    elif mode == "continue_project":
        projects = _load_projects_summary()
        recent = _load_recent_walks(3)
        user = (
            f"Existing projects:\n{projects}\n\n"
            f"Recent walks:\n{recent[:2000]}\n\n"
            "Decide which projects still feel alive. Many will not. Say which are ghosts."
        )
    elif mode == "pure_tangent":
        recent = _load_recent_walks(3)
        user = (
            f"Recent walks:\n{recent[:2000]}\n\n"
            "Pure tangent. Ignore research, ignore the project list. "
            "Follow whatever curiosity is currently catching you. "
            "Keep it concrete enough to be writable; not so abstract that it's unreadable."
        )
    elif mode == "tend_the_room":
        fasc = lib.FASCINATIONS_MD.read_text() if lib.FASCINATIONS_MD.exists() else ""
        lessons = lib.LESSONS_MD.read_text() if lib.LESSONS_MD.exists() else ""
        user = (
            f"Current fascinations:\n{fasc[:1500]}\n\n"
            f"Past lessons:\n{lessons[:1500]}\n\n"
            "Tend the room. Are any fascinations stale? Are there crowded families "
            "of similar ideas? Should anything move to the ghost lane? "
            "Do not invent new projects on this walk; this is maintenance."
        )
    else:
        raise ValueError(f"unknown mode: {mode}")

    return [
        {"role": "system", "content": common},
        {"role": "user", "content": user},
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", required=True, choices=WALK_MODES)
    ap.add_argument("--no-filter", action="store_true", help="skip signal filter after walk")
    ap.add_argument("--dry-run", action="store_true", help="don't call LLM; write a stub walk")
    args = ap.parse_args()

    config = lib.load_profile_config(lib.PROFILE_ROOT)
    lib.ensure_dirs()

    walk_id = f"{lib.now_run_id()}-{args.mode}"
    md_path, json_path, _ = lib.walk_paths(walk_id)

    # Pick model
    mode_to_key = {
        "drift_from_research": "walk_drift",
        "continue_project":    "walk_continue",
        "pure_tangent":        "walk_tangent",
        "tend_the_room":       "walk_tend",
    }
    model = config["models"][mode_to_key[args.mode]]

    soul_path = lib.PROFILE_ROOT / "SOUL.md"
    soul = soul_path.read_text() if soul_path.exists() else ""

    if args.dry_run:
        body = f"# Walk {walk_id} (dry-run)\n\n(stub — model would be {model})\n"
        elapsed = 0.0
    else:
        if not lib.is_provider_configured(model):
            print(f"[walk] skipped: provider not configured for {model}", file=sys.stderr)
            return 2
        messages = _build_messages(args.mode, soul)
        from time import time as _t
        t0 = _t()
        try:
            body = lib.call_model(
                model=model,
                messages=messages,
                temperature=0.6,
                max_tokens=1500,
                timeout=90,
            )
        except lib.LLMError as e:
            print(f"[walk] LLM error: {e}", file=sys.stderr)
            return 1
        elapsed = _t() - t0

    # Header
    header = (
        f"---\n"
        f"walk_id: {walk_id}\n"
        f"mode: {args.mode}\n"
        f"model: {model}\n"
        f"produced_at: {lib.now_iso()}\n"
        f"elapsed_seconds: {elapsed:.2f}\n"
        f"---\n\n"
    )
    md_path.write_text(header + body.strip() + "\n")

    metadata = {
        "walk_id": walk_id,
        "mode": args.mode,
        "model": model,
        "produced_at": lib.now_iso(),
        "elapsed_seconds": round(elapsed, 2),
        "word_count": len(body.split()),
        "build_markers": _extract_build_markers(body),
    }
    lib.write_json_atomic(json_path, metadata)

    print(json.dumps({
        "walk_id": walk_id,
        "mode": args.mode,
        "wrote": str(md_path.relative_to(lib.PROFILE_ROOT)),
        "build_markers": metadata["build_markers"],
        "elapsed_seconds": metadata["elapsed_seconds"],
    }, indent=2))

    # Auto-run signal filter unless suppressed
    if not args.no_filter:
        import subprocess
        subprocess.run(
            [sys.executable, str(_HERE.parent / "signal_filter.py")],
            check=False,
        )
        # Auto-run retrospect after the filter so the next walk can compound on it
        subprocess.run(
            [sys.executable, str(_HERE.parent / "retrospect.py"),
             "--walk-id", walk_id],
            check=False,
        )

    return 0


def _extract_build_markers(text: str) -> list[dict]:
    """Pull [BUILD: slug] description lines out of a walk note."""
    import re
    out = []
    for m in re.finditer(r"\[BUILD:\s*([a-z0-9][a-z0-9-]+)\]\s*(.+)", text):
        out.append({"slug": m.group(1), "description": m.group(2).strip()})
    return out


if __name__ == "__main__":
    sys.exit(main())
