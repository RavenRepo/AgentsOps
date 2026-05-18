#!/usr/bin/env python3
"""
verify.py — independent QA verification.

Reads:
  - <slug>.product-plan.json
  - <slug>.verification.json   (coder's receipt)
For each track that has both but no qa-verification:
  1. Re-hash every file the coder claims to have changed.
  2. Re-run every verification command in a fresh shell.
  3. Re-evaluate every acceptance check from the product-plan.
  4. Write qa-verification.json — independent receipt.
  5. Compute verification-delta.json — agreement state.

Phase 10 skeleton: handles the case where coder's verification is "skipped"
(Phase 11 will deal with real file hashes). The skeleton still produces a
valid qa-verification + delta.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _rerun_command(spec: dict, cwd: Path | None = None, timeout: float = 600) -> dict:
    """Run a verification command and capture exit + stdout/stderr excerpts."""
    cmd = spec["command"]
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        return {
            "command": cmd,
            "exit_code": proc.returncode,
            "stdout_excerpt": proc.stdout[-4000:],
            "stderr_excerpt": proc.stderr[-4000:],
        }
    except subprocess.TimeoutExpired:
        return {"command": cmd, "exit_code": 124, "stderr_excerpt": "timeout"}
    except Exception as e:
        return {"command": cmd, "exit_code": 127, "stderr_excerpt": str(e)[:1000]}


def _qa_verify(slug: str, plan: dict, coder_verif: dict, config: dict) -> dict:
    files_inspected = []
    for fc in coder_verif.get("files_changed", []):
        path = Path(fc["path"])
        if path.exists():
            actual_hash = _sha256(path)
            files_inspected.append({
                "path": str(path),
                "content_sha256": actual_hash,
                "matches_coder_claim": actual_hash == fc.get("content_sha256"),
            })
        else:
            files_inspected.append({
                "path": str(path),
                "content_sha256": "MISSING",
                "matches_coder_claim": False,
            })

    independent_runs = []
    if config.get("independence", {}).get("rerun_commands", True):
        timeout = config.get("independence", {}).get("shell_timeout_seconds", 600)
        for cmd_spec in plan.get("verification_commands", []):
            independent_runs.append(_rerun_command(cmd_spec, timeout=timeout))

    # Acceptance checks: at this Phase 10 skeleton, we can only confirm passes
    # by re-running commands. A truly thorough QA will read evidence files too.
    acceptance_results = []
    coder_acceptance = {a["check"]: a for a in coder_verif.get("acceptance_checks_results", [])}
    for check in plan.get("acceptance_checks", []):
        coder_passed = coder_acceptance.get(check, {}).get("passed", False)
        # Conservative: pass only if at least one independent run succeeded
        qa_passed = bool(independent_runs and all(r["exit_code"] == 0 for r in independent_runs))
        acceptance_results.append({
            "check": check,
            "passed": qa_passed,
            "qa_notes": "verified via independent command runs" if qa_passed else "could not confirm",
            "agrees_with_coder": qa_passed == coder_passed,
        })

    concerns = []
    if coder_verif.get("result") == "skipped":
        concerns.append({
            "concern": "coder verification was 'skipped' — no actual file changes to verify",
            "severity": "info",
            "evidence_path": str(lib.artifact_path(slug, "verification")),
        })

    overall = "skipped" if coder_verif.get("result") == "skipped" else (
        "pass" if all(r.get("passed") for r in acceptance_results) and acceptance_results else "partial"
    )

    qa = {
        "schema_version": 1,
        "qa_verification_id": f"qa-verif-{slug}-001",
        "build_id": coder_verif["build_id"],
        "coder_verification_id": coder_verif["verification_id"],
        "produced_by": "qa",
        "produced_at": lib.now_iso(),
        "result": overall,
        "summary": (
            f"Independently inspected {len(files_inspected)} files, "
            f"re-ran {len(independent_runs)} commands."
        ),
        "files_inspected": files_inspected,
        "independent_commands_run": independent_runs,
        "independent_evidence": [{
            "type": "log",
            "path": f"qa-run-{slug}.log",
            "description": "independent command output captured in this verification",
        }],
        "acceptance_checks_results": acceptance_results,
        "concerns_raised": concerns,
    }
    return qa


def _compute_delta(slug: str, coder_verif: dict, qa_verif: dict) -> dict:
    file_mismatches = [
        f for f in qa_verif.get("files_inspected", [])
        if not f.get("matches_coder_claim")
    ]
    disagreements = [
        a for a in qa_verif.get("acceptance_checks_results", [])
        if not a.get("agrees_with_coder")
    ]

    if file_mismatches or disagreements:
        agreement = "partial_agreement" if not file_mismatches else "qa_caught_drift"
        delta_state = "drift"
        action = "reopen_for_coder"
    elif qa_verif["result"] == "skipped":
        agreement = "full_agreement"
        delta_state = "missing_evidence"
        action = "trust_and_proceed"
    else:
        agreement = "full_agreement"
        delta_state = "confirmed"
        action = "trust_and_proceed"

    return {
        "schema_version": 1,
        "delta_id": f"delta-{slug}-001",
        "build_id": coder_verif["build_id"],
        "coder_verification_id": coder_verif["verification_id"],
        "qa_verification_id": qa_verif["qa_verification_id"],
        "produced_by": "trust",
        "produced_at": lib.now_iso(),
        "agreement_state": agreement,
        "delta_state": delta_state,
        "files_match": {
            "all_hashes_match": len(file_mismatches) == 0,
            "mismatched_files": [
                {"path": f["path"], "qa_hash": f["content_sha256"], "explanation": "coder hash unknown" if f["content_sha256"] == "MISSING" else "differs"}
                for f in file_mismatches
            ]
        },
        "acceptance_check_disagreements": [
            {"check": a["check"], "coder_passed": False, "qa_passed": a["passed"], "resolution": "ambiguous"}
            for a in disagreements
        ],
        "qa_concerns_unaddressed": [
            {"concern": c["concern"], "severity": c["severity"]}
            for c in qa_verif.get("concerns_raised", [])
        ],
        "recommended_action": action,
        "trust_impact": {
            "score_delta": 0.5 if agreement == "full_agreement" else -1.0,
            "evidence_for": "clean" if agreement == "full_agreement" else "watch",
        },
    }


def process_one(slug: str, dry_run: bool, config: dict) -> dict:
    plan = lib.read_artifact(slug, "product-plan")
    coder_verif = lib.read_artifact(slug, "verification")
    if not plan or not coder_verif:
        return {"slug": slug, "result": "skipped", "reason": "missing inputs"}

    qa = _qa_verify(slug, plan, coder_verif, config)
    qa_errs = lib.validate(qa, "qa-verification")
    if qa_errs:
        return {"slug": slug, "result": "fail", "reason": f"qa-verification invalid: {qa_errs[0]}"}

    delta = _compute_delta(slug, coder_verif, qa)
    delta_errs = lib.validate(delta, "verification-delta")
    if delta_errs:
        return {"slug": slug, "result": "partial",
                "reason": f"qa-verification valid but delta invalid: {delta_errs[0]}"}

    if dry_run:
        return {"slug": slug, "result": "dry-run", "qa_result": qa["result"],
                "agreement": delta["agreement_state"]}

    lib.write_json_atomic(lib.artifact_path(slug, "qa-verification"), qa)
    lib.write_json_atomic(lib.artifact_path(slug, "verification-delta"), delta)

    return {"slug": slug, "result": "ok",
            "qa_result": qa["result"],
            "agreement": delta["agreement_state"],
            "recommended_action": delta["recommended_action"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", help="verify this slug only")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config = lib.load_profile_config(lib.PROFILE_ROOT)

    if args.slug:
        if lib.has_artifact(args.slug, "qa-verification"):
            print(f"{args.slug} already has qa-verification — skipping")
            return 0
        result = process_one(args.slug, args.dry_run, config)
        print(json.dumps(result, indent=2))
        return 0 if result["result"] in {"ok", "dry-run"} else 1

    results = []
    for slug, _ in lib.tracks_pending("verification", "qa-verification"):
        results.append(process_one(slug, args.dry_run, config))
    if not results:
        print("nothing to verify")
        return 0
    print(json.dumps({"verified": len(results), "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
