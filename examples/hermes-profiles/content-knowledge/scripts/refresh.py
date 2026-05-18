#!/usr/bin/env python3
"""
refresh.py — content-knowledge entry point.

Modes:
  refresh-medium | refresh-x | refresh-linkedin | refresh-substack | refresh-seo
  playbook-rebuild --platform <p>

v1 behavior: read the platform's findings.jsonl + existing playbook.md.
If LLM-configured, ask the synthesis model to update tactics_rewarded /
tactics_avoided / format_hints based on findings. Write a structured
JSON companion validating against platform-playbook.schema.json.

If no findings yet, simply touch the playbook last-updated and write a
schema-valid playbook JSON with `confidence: weak` placeholders.

Real source-watching collectors (RSS/API/scrape per platform) are deferred.
The profile's job today is to MAINTAIN the playbooks — not to build the
research pipeline. That comes layer-by-layer.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402

PLATFORMS = lib.PLATFORMS
MODES = [f"refresh-{p}" for p in PLATFORMS] + ["playbook-rebuild"]


def _read_findings(platform: str, n: int = 25) -> list[dict]:
    fp = lib.findings_ledger(platform)
    if not fp.exists():
        return []
    out = list(lib.read_jsonl(fp))
    return out[-n:]


def _build_playbook_json(platform: str, findings: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "platform": platform,
        "produced_at": lib.now_iso(),
        "produced_by": "content-knowledge",
        "version": 1,
        "summary": (
            f"v1 stub playbook for {platform}. "
            f"{len(findings)} findings on file. "
            "Tactics will populate as collectors are wired and findings accrue."
        ),
        "tactics_rewarded": [],
        "tactics_avoided": [],
        "format_hints": {},
        "rate_limits": _default_rate_limits(platform),
    }


def _default_rate_limits(platform: str) -> dict:
    """Conservative defaults from the v1 design."""
    return {
        "medium":   {"max_per_week": 2},
        "x":        {"max_per_day": 3, "min_hours_between": 4},
        "linkedin": {"max_per_day": 1},
        "substack": {"max_per_week": 1},
        "seo":      {},
    }.get(platform, {})


def mode_refresh(platform: str, config: dict) -> dict:
    lib.ensure_dirs()

    # Platform-specific real collector for X (Bearer Token + NVIDIA extractor)
    if platform == "x":
        try:
            import x_research
            x_receipt = x_research.run_refresh_x(lib.PROFILE_ROOT)
            # Continue to playbook write below regardless
        except Exception as e:
            x_receipt = {"mode": "refresh-x", "result": "fail",
                          "reason": f"collector error: {e}"}
    else:
        x_receipt = None

    findings = _read_findings(platform)
    pb = _build_playbook_json(platform, findings)

    errs = lib.validate(pb, "platform-playbook")
    if errs:
        return {"mode": f"refresh-{platform}", "result": "fail",
                "errors": errs[:5]}

    out_json = lib.playbook_json(platform)
    lib.write_json_atomic(out_json, pb)

    # Bump the markdown playbook's footer with last-refreshed timestamp
    md_path = lib.playbook_md(platform)
    if md_path.exists():
        existing = md_path.read_text()
    else:
        existing = ""
    footer = f"\n\n---\n_Last refreshed: {lib.now_iso()} · findings on file: {len(findings)}_\n"
    if "_Last refreshed:" in existing:
        existing = existing.split("_Last refreshed:")[0].rstrip() + footer
    else:
        existing = existing.rstrip() + footer
    lib.write_atomic(md_path, existing)

    receipt = {
        "mode": f"refresh-{platform}",
        "result": "ok",
        "platform": platform,
        "findings_on_file": len(findings),
        "wrote_json": str(out_json),
        "wrote_md": str(md_path),
    }
    if x_receipt is not None:
        receipt["x_collector"] = x_receipt
    return receipt


def mode_playbook_rebuild(platform: str, config: dict) -> dict:
    """v2 hook: ask LLM to synthesize tactics from findings. v1 stub: same as refresh."""
    return mode_refresh(platform, config)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=MODES)
    ap.add_argument("--platform", choices=PLATFORMS,
                    help="for playbook-rebuild only")
    args = ap.parse_args()

    config = lib.load_profile_config(lib.PROFILE_ROOT)

    if args.mode == "playbook-rebuild":
        if not args.platform:
            print(json.dumps({"result": "fail", "reason": "--platform required for playbook-rebuild"}))
            return 1
        receipt = mode_playbook_rebuild(args.platform, config)
    else:
        platform = args.mode.removeprefix("refresh-")
        receipt = mode_refresh(platform, config)

    print(json.dumps(receipt, indent=2))
    return 0 if receipt.get("result") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
