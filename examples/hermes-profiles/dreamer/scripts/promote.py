#!/usr/bin/env python3
"""
promote.py — promote a card from the dreamer board to an idea-contract.

Reads signal-state/summary.json, picks a slug (top-scored ready, or one given
explicitly), elaborates an idea-contract via LLM, validates against the buildroom
schema, writes to Path(os.environ.get("GOKU_DATA_DIR", "os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")")) / "state"/tracks/<slug>/<slug>.idea-contract.json.

Honors the sprint lock: refuses to promote if a lock file is present.

Usage:
    python scripts/promote.py                  # auto-pick top ready card
    python scripts/promote.py --slug my-thing  # promote a specific card
    python scripts/promote.py --release-lock   # delete a stale lock and exit
    python scripts/promote.py --dry-run        # don't write artifacts
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402


def acquire_lock(slug: str) -> bool:
    """Try to acquire the sprint lock. Returns True on success."""
    if lib.SPRINT_LOCK.exists():
        return False
    lib.write_json_atomic(lib.SPRINT_LOCK, {
        "slug": slug,
        "acquired_at": lib.now_iso(),
        "by": "dreamer.promote",
    })
    return True


def release_lock() -> None:
    if lib.SPRINT_LOCK.exists():
        lib.SPRINT_LOCK.unlink()


def load_board() -> dict:
    if not lib.SIGNAL_SUMMARY.exists():
        return {"lanes": {"ready": [], "experiment": []}, "scored": {}}
    return json.loads(lib.SIGNAL_SUMMARY.read_text())


def pick_card(board: dict, requested: str | None) -> str | None:
    if requested:
        return requested
    ready = board.get("lanes", {}).get("ready", [])
    return ready[0] if ready else None


def _build_elaboration_prompt(slug: str, board_info: dict) -> list[dict]:
    """Ask the LLM to expand the card into a full idea-contract structure."""
    system = (
        "You are Goku's Dreamer agent, elaborating a candidate idea into a structured "
        "idea-contract. Output strict JSON only. Do NOT include any prose outside the JSON. "
        "Keep claims modest — this is a CANDIDATE, not approved work."
    )
    user = (
        f"Slug: {slug}\n"
        f"Score: {board_info.get('score', 0):.1f}\n"
        f"Signal types: {board_info.get('signal_types', [])}\n"
        f"Positive walks: {board_info.get('positive_walks', 0)}\n"
        f"Last seen: {board_info.get('last_seen', '?')}\n"
        f"Description (from build markers): {board_info.get('description', '(none)')}\n\n"
        "Output a JSON object with these fields ONLY (omit empty optional fields):\n"
        "  title              (string, 3-200 chars)\n"
        "  what_should_exist  (string, 20-2000 chars, one paragraph)\n"
        "  who_benefits       (string, optional)\n"
        "  why_now            (string, optional)\n"
        "  out_of_scope       (array of strings, optional)\n"
        "  where_it_might_live: object with optional fields filesystem_path, repository, service, notes\n"
        "  how_verified       (array of strings, optional)\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def assemble_idea_contract(slug: str, board_info: dict, llm_json: dict, walk_mode_hint: str = "drift-from-research") -> dict:
    """Combine the LLM's elaboration with structural fields from the board."""
    contract = {
        "schema_version": 1,
        "contract_id": slug,
        "slug": slug,
        "produced_by": "dreamer",
        "produced_at": lib.now_iso(),
        "walk_mode": walk_mode_hint,
        "title": llm_json.get("title", slug.replace("-", " ").title()),
        "what_should_exist": llm_json.get("what_should_exist", "(no description)"),
        "evidence": [{
            "source_id": f"signal-board:{slug}",
            "source_type": "internal-note",
            "excerpt": board_info.get("description", "")[:500] or f"Score {board_info.get('score', 0):.1f} from dreamer signal filter",
            "captured_at": board_info.get("last_seen", lib.now_iso()),
        }],
        "signal_score": float(board_info.get("score", 0)),
        "signal_types": [t for t in board_info.get("signal_types", []) if t in
                         {"commit", "friction", "excitement", "reuse", "mention", "return", "cooling"}] or ["commit"],
        "positive_walks": int(board_info.get("positive_walks", 0)),
        "returns_count": max(0, int(board_info.get("positive_walks", 0)) - 1),
        "experiment_lane": False,
        "card_state": "ready",
    }

    # Optional fields if LLM provided them
    for key in ("who_benefits", "why_now"):
        if llm_json.get(key):
            contract[key] = llm_json[key]
    if isinstance(llm_json.get("out_of_scope"), list) and llm_json["out_of_scope"]:
        contract["out_of_scope"] = [str(x) for x in llm_json["out_of_scope"]]
    if isinstance(llm_json.get("how_verified"), list) and llm_json["how_verified"]:
        contract["how_verified"] = [str(x) for x in llm_json["how_verified"]]
    if isinstance(llm_json.get("where_it_might_live"), dict):
        contract["where_it_might_live"] = {
            k: v for k, v in llm_json["where_it_might_live"].items()
            if k in {"filesystem_path", "repository", "service", "notes"} and v
        }

    return contract


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", help="explicit slug to promote (default: top ready)")
    ap.add_argument("--release-lock", action="store_true", help="delete stale sprint lock and exit")
    ap.add_argument("--dry-run", action="store_true", help="don't write artifacts")
    args = ap.parse_args()

    if args.release_lock:
        release_lock()
        print("released sprint lock (if present)")
        return 0

    config = lib.load_profile_config(lib.PROFILE_ROOT)
    lib.ensure_dirs()

    board = load_board()
    slug = pick_card(board, args.slug)
    if not slug:
        print("[promote] no card to promote (board ready lane is empty)")
        return 0

    board_info = board.get("scored", {}).get(slug, {})
    if not board_info:
        print(f"[promote] slug {slug!r} not on the board; refusing to promote")
        return 1

    if config.get("sprint_lock", {}).get("enabled", True):
        if not acquire_lock(slug):
            with lib.SPRINT_LOCK.open() as f:
                lock = json.load(f)
            print(f"[promote] sprint lock held by {lock.get('slug')!r} since {lock.get('acquired_at')}")
            return 0

    try:
        model = config["models"]["intent_elaboration"]
        if not lib.is_provider_configured(model):
            print(f"[promote] model {model} not configured; releasing lock")
            release_lock()
            return 2

        if args.dry_run:
            llm_json = {
                "title": slug.replace("-", " ").title(),
                "what_should_exist": "(dry-run stub — LLM not called)",
            }
        else:
            try:
                resp = lib.call_model(
                    model=model,
                    messages=_build_elaboration_prompt(slug, board_info),
                    temperature=0.3,
                    max_tokens=1000,
                    json_mode=True,
                    timeout=90,
                )
                llm_json = json.loads(resp)
            except (lib.LLMError, json.JSONDecodeError) as e:
                print(f"[promote] elaboration failed: {e}; releasing lock")
                release_lock()
                return 1

        contract = assemble_idea_contract(slug, board_info, llm_json)

        errs = lib.validate(contract, "idea-contract")
        if errs:
            print(f"[promote] idea-contract failed validation:")
            for e in errs[:5]:
                print(f"  - {e}")
            release_lock()
            return 1

        if args.dry_run:
            print(json.dumps(contract, indent=2))
            release_lock()  # dry-run shouldn't hold lock
            return 0

        track = lib.track_dir(slug)
        out_path = track / f"{slug}.idea-contract.json"
        lib.write_json_atomic(out_path, contract)

        print(f"[promote] wrote {out_path}")
        print(f"[promote] sprint lock held by {slug} (release after main reviews)")
        return 0
    except Exception:
        # On unexpected error, release the lock so we don't deadlock the room
        release_lock()
        raise


if __name__ == "__main__":
    sys.exit(main())
