#!/usr/bin/env python3
"""
process_review.py — main's approval gate.

Workflow:
  1. Find tracks that have idea-contract but no main-review.
  2. For each, ask the LLM to assess risk and propose a product-plan.
  3. Write main-review.json (validated against schema).
  4. If approved, write product-plan.json (validated).
  5. If high/critical risk and not force-approved, mark blocked.

Usage:
    python scripts/process_review.py                       # process all pending
    python scripts/process_review.py --slug demo-foo       # specific slug
    python scripts/process_review.py --dry-run             # don't write
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402


REVIEW_PROMPT_SYSTEM = """You are Goku's Main agent — the approval gate.

Read the idea-contract. Output JSON only with this exact shape:

{
  "decision": "approved_for_coder" | "blocked" | "revisions_requested" | "deferred",
  "risk_band": "low" | "medium" | "high" | "critical",
  "risk_score": <int 0-100>,
  "reasoning": "<concise reasoning, max 500 chars>",
  "block_reason": null | "<why if blocked>",
  "conditions": [<short strings>],
  "protected_surfaces": [<paths the coder MUST NOT touch>],
  "product_plan": {
    "goal": "<what the build must achieve>",
    "allowed_paths": [<paths coder may write to>],
    "planned_files": [{"path": "<>", "action": "create|modify|delete|rename", "purpose": "<>"}],
    "non_goals": [<short strings>],
    "verification_commands": [{"command": "<>", "purpose": "<>"}],
    "acceptance_checks": [<concrete checks>],
    "risk_assessment": {
      "risk_band": "low|medium|high|critical",
      "blast_radius": "isolated|module|service|cross-service|system-wide",
      "rollback_strategy": "<how to undo>"
    }
  }
}

Rules:
- If risk_band is high or critical, decision should be 'blocked' or 'revisions_requested'
  unless the rollback strategy is trivial.
- If decision is not 'approved_for_coder', omit the 'product_plan' field entirely.
- Allowed_paths must be specific filesystem paths, not wildcards beyond a single trailing /.
- Acceptance_checks must be runnable verifications, not vague goals.
"""


def _build_messages(contract: dict, soul: str) -> list[dict]:
    return [
        {"role": "system", "content": REVIEW_PROMPT_SYSTEM + "\n\n" + soul},
        {"role": "user", "content": json.dumps(contract, indent=2)[:6000]},
    ]


def _call_review(contract: dict, model: str, soul: str) -> dict:
    raw = lib.call_model(
        model=model,
        messages=_build_messages(contract, soul),
        temperature=0.1,
        max_tokens=1500,
        json_mode=True,
        timeout=90,
    )
    return json.loads(raw)


def _build_main_review(slug: str, contract: dict, llm_out: dict, config: dict) -> dict:
    decision = llm_out.get("decision", "deferred")
    risk_band = llm_out.get("risk_band", "high")
    risk_score = int(llm_out.get("risk_score", 50))

    # Auto-approval gate
    aa = config.get("auto_approve", {})
    auto_approved = (
        decision == "approved_for_coder"
        and aa.get("enabled", False)
        and risk_band == aa.get("max_risk_band", "low")
        and risk_score <= aa.get("max_risk_score", 15)
        and contract.get("positive_walks", 0) >= aa.get("min_walks_required", 3)
    )

    review: dict = {
        "schema_version": 1,
        "review_id": f"main-{slug}-001",
        "contract_id": slug,
        "reviewed_by": "main",
        "reviewed_at": lib.now_iso(),
        "decision": decision,
        "risk_band": risk_band,
        "risk_score": risk_score,
        "reasoning": llm_out.get("reasoning", "")[:4000],
        "block_reason": llm_out.get("block_reason"),
        "auto_approved": auto_approved,
        "force_approved": False,
        "conditions": llm_out.get("conditions", []),
        "protected_surfaces": llm_out.get("protected_surfaces", []),
    }

    # Always-protected surfaces from policy
    for p in config.get("risk", {}).get("always_protected", []):
        if p not in review["protected_surfaces"]:
            review["protected_surfaces"].append(p)

    return review


def _build_product_plan(slug: str, review_id: str, llm_pp: dict) -> dict:
    """Shape the product-plan from the LLM output."""

    # Normalize acceptance_checks — schema requires array of strings, but LLMs
    # often produce {check, purpose} dicts. Coerce each entry to a string.
    raw_checks = llm_pp.get("acceptance_checks", [])
    acceptance_checks = []
    for c in raw_checks:
        if isinstance(c, str):
            acceptance_checks.append(c)
        elif isinstance(c, dict):
            # Prefer "check" field, fall back to "purpose", or join both
            check = c.get("check") or c.get("description") or c.get("name") or ""
            purpose = c.get("purpose", "")
            text = check
            if purpose and purpose != check:
                text = f"{check} ({purpose})" if check else purpose
            if text:
                acceptance_checks.append(text)

    # Normalize verification_commands — schema requires {command, ...} dicts
    raw_cmds = llm_pp.get("verification_commands", [])
    verification_commands = []
    for c in raw_cmds:
        if isinstance(c, str):
            verification_commands.append({"command": c})
        elif isinstance(c, dict) and c.get("command"):
            verification_commands.append({
                k: v for k, v in c.items()
                if k in {"command", "cwd", "expected_exit_code", "purpose"}
            })

    # Normalize planned_files — schema requires {path, action, ...}
    raw_files = llm_pp.get("planned_files", [])
    planned_files = []
    for f in raw_files:
        if isinstance(f, dict) and f.get("path") and f.get("action"):
            planned_files.append({
                k: v for k, v in f.items()
                if k in {"path", "action", "purpose"}
            })

    return {
        "schema_version": 1,
        "plan_id": f"plan-{slug}-001",
        "contract_id": slug,
        "main_review_id": review_id,
        "produced_by": "main",
        "produced_at": lib.now_iso(),
        "goal": llm_pp.get("goal", "(no goal specified)"),
        "allowed_paths": [str(p) for p in llm_pp.get("allowed_paths", []) if p],
        "planned_files": planned_files,
        "non_goals": [str(n) for n in llm_pp.get("non_goals", []) if n],
        "protected_surfaces": [],
        "verification_commands": verification_commands,
        "acceptance_checks": acceptance_checks,
        "risk_assessment": llm_pp.get("risk_assessment", {}),
    }


def _audit_log(record: dict) -> None:
    """Append to Path(os.environ.get("GOKU_DATA_DIR", "os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")")) / "state"/approval-ledger.jsonl (signed audit)."""
    record = {**record, "logged_at": lib.now_iso()}
    lib.append_jsonl(lib.APPROVAL_LEDGER, record)


def process_one(slug: str, contract: dict, config: dict, dry_run: bool) -> dict:
    soul_path = lib.PROFILE_ROOT / "SOUL.md"
    soul = soul_path.read_text() if soul_path.exists() else ""

    model = config["models"]["review"]
    if not lib.is_provider_configured(model):
        return {"slug": slug, "result": "skipped", "reason": f"provider not configured for {model}"}

    try:
        llm_out = _call_review(contract, model, soul)
    except (lib.LLMError, json.JSONDecodeError) as e:
        return {"slug": slug, "result": "fail", "reason": f"LLM/JSON error: {e}"}

    review = _build_main_review(slug, contract, llm_out, config)
    review_errs = lib.validate(review, "main-review")
    if review_errs:
        return {"slug": slug, "result": "fail", "reason": f"main-review invalid: {review_errs[0]}"}

    if dry_run:
        return {"slug": slug, "result": "dry-run", "decision": review["decision"], "risk_band": review["risk_band"]}

    # Write main-review
    lib.write_json_atomic(lib.artifact_path(slug, "main-review"), review)
    _audit_log({"event": "main-review", "slug": slug, "decision": review["decision"],
                "risk_band": review["risk_band"], "risk_score": review["risk_score"]})

    # If approved, write product-plan
    if review["decision"] == "approved_for_coder":
        pp = _build_product_plan(slug, review["review_id"], llm_out.get("product_plan", {}))
        pp_errs = lib.validate(pp, "product-plan")
        if pp_errs:
            return {"slug": slug, "result": "partial",
                    "reason": "main-review written but product-plan invalid",
                    "product_plan_errors": pp_errs[:3]}
        lib.write_json_atomic(lib.artifact_path(slug, "product-plan"), pp)
        _audit_log({"event": "product-plan", "slug": slug, "plan_id": pp["plan_id"]})

    return {
        "slug": slug,
        "result": "ok",
        "decision": review["decision"],
        "risk_band": review["risk_band"],
        "risk_score": review["risk_score"],
        "auto_approved": review["auto_approved"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", help="process this slug only")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config = lib.load_profile_config(lib.PROFILE_ROOT)

    if args.slug:
        contract = lib.read_artifact(args.slug, "idea-contract")
        if not contract:
            print(f"no idea-contract found for {args.slug}")
            return 1
        if lib.has_artifact(args.slug, "main-review"):
            print(f"{args.slug} already has main-review — skipping (delete it to re-review)")
            return 0
        result = process_one(args.slug, contract, config, args.dry_run)
        print(json.dumps(result, indent=2))
        return 0 if result["result"] in {"ok", "dry-run"} else 1

    # Batch mode: every pending track
    results = []
    for slug, contract in lib.tracks_pending("idea-contract", "main-review"):
        results.append(process_one(slug, contract, config, args.dry_run))

    if not results:
        print("nothing pending review")
        return 0
    print(json.dumps({"processed": len(results), "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
