#!/usr/bin/env python3
"""
sweep.py — retention sweep across built tracks.

For each track that has a verification-delta (i.e., went through the chain)
and no retention-review yet:
  1. Look up evidence: last_modified, mention_count (in dreamer walks), age.
  2. Apply heuristics from config (windows: keep / consider_park / consider_prune).
  3. Write retention-review.json.

Operator must explicitly approve any prune action via the cockpit (NOT this script).

Usage:
    python scripts/sweep.py                     # process all tracks
    python scripts/sweep.py --slug demo-foo     # one slug
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402


def _age_days(iso_ts: str | None) -> int | None:
    if not iso_ts:
        return None
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - ts).days


def _count_mentions(slug: str, mention_sources: list[str]) -> tuple[int, str | None]:
    """Count how many times the slug appears in walk/dossier/event sources.
    Returns (count, latest_mention_iso)."""
    count = 0
    latest_ts = None
    pattern = re.compile(r"\b" + re.escape(slug) + r"\b")
    for src in mention_sources:
        p = Path(src)
        if not p.exists():
            continue
        if p.is_file():
            text = p.read_text(errors="ignore")
            count += len(pattern.findall(text))
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and f.suffix in {".md", ".json", ".jsonl"}:
                    try:
                        text = f.read_text(errors="ignore")
                        n = len(pattern.findall(text))
                        if n:
                            count += n
                            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat()
                            if not latest_ts or mtime > latest_ts:
                                latest_ts = mtime
                    except (OSError, UnicodeDecodeError):
                        continue
    return count, latest_ts


def _decide(slug: str, config: dict) -> dict:
    delta = lib.read_artifact(slug, "verification-delta")
    qa = lib.read_artifact(slug, "qa-verification")

    track_path = lib.track_dir(slug)
    last_modified = max(
        (datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
         for f in track_path.iterdir() if f.is_file()),
        default=datetime.fromtimestamp(0, tz=timezone.utc),
    )
    last_modified_iso = last_modified.isoformat()

    mention_count, latest_mention = _count_mentions(slug, config.get("mention_sources", []))

    age = _age_days(last_modified_iso) or 0
    windows = config.get("windows", {})
    keep_recent = windows.get("keep_if_recent_days", 30)
    park_threshold = windows.get("consider_park_days", 60)
    prune_threshold = windows.get("consider_prune_days", 90)

    has_concerns = bool(qa and qa.get("concerns_raised"))
    verification_passed = delta and delta.get("agreement_state") == "full_agreement"

    # Decision tree
    if age <= keep_recent:
        recommendation = "keep"
        reasoning = f"Recently built ({age}d) — keep automatically."
        action = "no_action_needed"
    elif mention_count >= 3:
        recommendation = "keep"
        reasoning = f"{mention_count} mentions in subsequent activity — actively useful."
        action = "no_action_needed"
    elif has_concerns and not verification_passed:
        recommendation = "improve"
        reasoning = "Unresolved concerns from QA; recommend follow-up build."
        action = "create_improvement_idea"
    elif age >= prune_threshold and mention_count == 0:
        recommendation = "prune"
        reasoning = f"No mentions in {age}d, no downstream deps detected."
        action = "delete_files"
    elif age >= park_threshold and mention_count == 0:
        recommendation = "park"
        reasoning = f"Stale ({age}d, 0 mentions). Archive but keep available."
        action = "move_to_archive"
    else:
        recommendation = "keep"
        reasoning = f"In transition ({age}d, {mention_count} mentions) — defer."
        action = "no_action_needed"

    return {
        "schema_version": 1,
        "review_id": f"ret-{slug}-{lib.now_run_id()}",
        "artifact_id": f"build-{slug}-001",  # convention from coder build_id
        "artifact_type": "build",
        "produced_by": "retention",
        "produced_at": lib.now_iso(),
        "recommendation": recommendation,
        "reasoning": reasoning,
        "evidence": {
            "last_referenced_at": latest_mention,
            "last_modified_at": last_modified_iso,
            "mention_count": mention_count,
            "downstream_dependencies": 0,
            "trust_state_at_build": "clean" if verification_passed else "watch",
            "verification_passed": bool(verification_passed),
        },
        "follow_up_action": {"action": action},
        "operator_decision_required": recommendation == "prune",
    }


def process_one(slug: str, dry_run: bool, config: dict) -> dict:
    if not lib.has_artifact(slug, "verification-delta"):
        return {"slug": slug, "result": "skipped", "reason": "no verification-delta yet"}

    review = _decide(slug, config)
    errs = lib.validate(review, "retention-review")
    if errs:
        return {"slug": slug, "result": "fail", "reason": f"retention-review invalid: {errs[0]}"}

    if dry_run:
        return {"slug": slug, "result": "dry-run", "recommendation": review["recommendation"]}

    lib.write_json_atomic(lib.artifact_path(slug, "retention-review"), review)
    return {"slug": slug, "result": "ok",
            "recommendation": review["recommendation"],
            "operator_required": review["operator_decision_required"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", help="sweep this slug only")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config = lib.load_profile_config(lib.PROFILE_ROOT)

    if args.slug:
        result = process_one(args.slug, args.dry_run, config)
        print(json.dumps(result, indent=2))
        return 0 if result["result"] in {"ok", "dry-run", "skipped"} else 1

    results = []
    for slug in lib.list_tracks():
        if lib.has_artifact(slug, "verification-delta") and not lib.has_artifact(slug, "retention-review"):
            results.append(process_one(slug, args.dry_run, config))

    if not results:
        print("nothing to sweep")
        return 0
    print(json.dumps({"reviewed": len(results), "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
