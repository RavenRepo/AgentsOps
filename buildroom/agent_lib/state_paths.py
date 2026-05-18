"""Shared state filesystem layout — used by main / coder / qa / retention.

Every track is a folder under STATE_DIR/tracks/<slug>/ containing the chain
of artifacts produced by the contract pipeline:

    state/tracks/<slug>/
      <slug>.idea-contract.json       (dreamer)
      <slug>.intent-review.json       (main, optional auto-filter)
      <slug>.main-review.json         (main)
      <slug>.product-plan.json        (main)
      <slug>.build-plan.json          (coder)
      <slug>.verification.json        (coder)
      <slug>.qa-verification.json     (qa)
      <slug>.verification-delta.json  (trust/qa)
      <slug>.retention-review.json    (retention)
      work/                           (coder workspace, optional)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator, Optional

# Use environment variables for deployment flexibility
_GOKU_DATA_DIR = os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")
STATE_DIR = Path(_GOKU_DATA_DIR) / "state"
TRACKS_DIR = STATE_DIR / "tracks"
EVENTS_LEDGER = STATE_DIR / "events.jsonl"
APPROVAL_LEDGER = STATE_DIR / "approval-ledger.jsonl"

# Map of artifact-kind -> filename suffix
ARTIFACT_KINDS = (
    "idea-contract",
    "intent-review",
    "main-review",
    "product-plan",
    "build-plan",
    "verification",
    "qa-verification",
    "verification-delta",
    "retention-review",
)


def track_dir(slug: str) -> Path:
    p = TRACKS_DIR / slug
    p.mkdir(parents=True, exist_ok=True)
    return p


def artifact_path(slug: str, kind: str) -> Path:
    """Return state/tracks/<slug>/<slug>.<kind>.json"""
    if kind not in ARTIFACT_KINDS:
        raise ValueError(f"unknown artifact kind: {kind}")
    return track_dir(slug) / f"{slug}.{kind}.json"


def list_tracks() -> list[str]:
    """Return slugs of all tracks present."""
    if not TRACKS_DIR.exists():
        return []
    return sorted(p.name for p in TRACKS_DIR.iterdir() if p.is_dir())


def has_artifact(slug: str, kind: str) -> bool:
    return artifact_path(slug, kind).exists()


def read_artifact(slug: str, kind: str) -> Optional[dict]:
    p = artifact_path(slug, kind)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def tracks_pending(needs_kind: str, has_kind: str) -> Iterator[tuple[str, dict]]:
    """Yield (slug, artifact) for every track that has `needs_kind` but not `has_kind`.

    Example: tracks_pending("idea-contract", "main-review") yields tracks
    waiting on main review.
    """
    for slug in list_tracks():
        if has_artifact(slug, needs_kind) and not has_artifact(slug, has_kind):
            doc = read_artifact(slug, needs_kind)
            if doc is not None:
                yield slug, doc
