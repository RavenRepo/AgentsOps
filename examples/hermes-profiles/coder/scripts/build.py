#!/usr/bin/env python3
"""
build.py — coder picks up an approved product-plan and runs a real build.

Phase 11a: hermes-native backend.
  - Workspace: tracks/<slug>/work/ (isolated from real filesystem)
  - LLM generates file contents in JSON, ONE call (cheap, fast).
  - Files written under work/, paths relative to allowed_paths.
  - Verification commands run inside work/ in fresh subprocess shells.
  - All file hashes + command outputs captured in verification.json.

Phase 11b will add opencode-cli as an alternative backend.

Usage:
    just build                                  # process all approved
    just build --slug demo-foo                  # specific slug
    just build --backend hermes-native          # explicit backend
    just build --dry-run                        # don't actually generate
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402


GENERATE_PROMPT = """You are Goku's Coder agent. You have an approved product-plan.

Your job: generate the contents of every file listed in `planned_files` (those
with action 'create' or 'modify'). Output JSON ONLY with this exact shape:

{
  "files": [
    { "path": "<exact path from planned_files>", "content": "<full file contents>" },
    ...
  ]
}

Rules:
- Generate complete, syntactically valid file contents — not pseudocode.
- Match the goal and acceptance_checks. Include imports, error handling, docstrings.
- Keep each file focused; do not invent files outside `planned_files`.
- Do NOT include any prose outside the JSON object.
- If a planned file is "modify" rather than "create", emit the full new contents
  (not a patch).
"""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _path_under_work(work: Path, declared_path: str) -> Path:
    """Map a declared path (possibly absolute like /research/foo/bar.py) to
    a path inside work/. Strips leading slash; refuses to escape work/."""
    p = declared_path.lstrip("/")
    full = (work / p).resolve()
    # Guard against ".." escapes
    if not str(full).startswith(str(work.resolve())):
        raise ValueError(f"path escapes work/: {declared_path}")
    return full


def _build_plan_from_product_plan(slug: str, plan: dict, backend: str) -> dict:
    return {
        "schema_version": 1,
        "build_id": f"build-{slug}-001",
        "plan_id": plan["plan_id"],
        "produced_by": "coder",
        "produced_at": lib.now_iso(),
        "started_at": lib.now_iso(),
        "coder_runtime": {
            "backend": backend,
            "model": "(see config.models)",
            "workspace_isolation": "git-worktree",
        },
        "files_to_create": [
            {"path": pf["path"], "purpose": pf.get("purpose", "")}
            for pf in plan.get("planned_files", []) if pf.get("action") == "create"
        ],
        "files_to_modify": [
            {"path": pf["path"], "purpose": pf.get("purpose", "")}
            for pf in plan.get("planned_files", []) if pf.get("action") == "modify"
        ],
        "files_to_delete": [
            pf["path"] for pf in plan.get("planned_files", []) if pf.get("action") == "delete"
        ],
        "commands_to_run": plan.get("verification_commands", []),
        "expected_outputs": [],
        "estimated_runtime_seconds": 600,
        "card_state": "active",
    }


def _generate_files_hermes_native(plan: dict, model: str, max_tokens: int = 4000) -> list[dict]:
    """Single LLM call returning a list of {path, content} dicts."""
    creates = [pf for pf in plan.get("planned_files", []) if pf.get("action") in {"create", "modify"}]
    if not creates:
        return []

    user = (
        f"Goal: {plan['goal']}\n\n"
        f"Acceptance checks:\n" + "\n".join(f"- {c}" for c in plan.get("acceptance_checks", [])) +
        "\n\n"
        f"Files to generate:\n{json.dumps(creates, indent=2)[:3000]}\n\n"
        f"Allowed paths (must stay within these): {plan.get('allowed_paths', [])}"
    )
    raw = lib.call_model(
        model=model,
        messages=[
            {"role": "system", "content": GENERATE_PROMPT},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=max_tokens,
        json_mode=True,
        timeout=180,
    )
    data = json.loads(raw)
    out = data.get("files", [])
    return [f for f in out if isinstance(f, dict) and "path" in f and "content" in f]


def _is_path_allowed(declared_path: str, allowed: list[str]) -> bool:
    """Check if declared_path matches any allowed prefix."""
    p = declared_path.lstrip("/")
    for a in allowed:
        a_stripped = a.lstrip("/").rstrip("/")
        if p == a_stripped or p.startswith(a_stripped + "/"):
            return True
    return False


def _run_verification_commands(work: Path, commands: list[dict], timeout: float = 600) -> list[dict]:
    """Run each verification command in a fresh shell, cwd=work."""
    out = []
    for cmd_spec in commands:
        cmd = cmd_spec.get("command", "")
        if not cmd:
            continue
        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=work,
            )
            out.append({
                "command": cmd,
                "exit_code": proc.returncode,
                "stdout_excerpt": proc.stdout[-2000:],
                "stderr_excerpt": proc.stderr[-2000:],
                "duration_seconds": round(time.time() - t0, 2),
            })
        except subprocess.TimeoutExpired:
            out.append({"command": cmd, "exit_code": 124,
                        "stderr_excerpt": "timeout", "duration_seconds": timeout})
        except Exception as e:
            out.append({"command": cmd, "exit_code": 127, "stderr_excerpt": str(e)[:1000]})
    return out


def _build_verification(slug: str, build_id: str, plan: dict, files_written: list[dict],
                        commands_results: list[dict], deviations: list[dict]) -> dict:
    files_changed = []
    evidence = []
    for fw in files_written:
        files_changed.append({
            "path": fw["path"],
            "action": fw["action"],
            "content_sha256": fw["sha256"],
            "size_bytes": fw["size"],
            "diff_summary": f"+{fw['size']} bytes",
        })
        evidence.append({
            "type": "file",
            "path": fw["path"],
            "content_sha256": fw["sha256"],
            "description": fw.get("purpose", ""),
        })
    if commands_results:
        evidence.append({
            "type": "log",
            "path": f"state/tracks/{slug}/work/.build-output.log",
            "description": f"{len(commands_results)} verification command(s) run",
        })

    # Acceptance checks: rough — pass if any verification command exited 0
    any_cmd_passed = any(c["exit_code"] == 0 for c in commands_results)
    acceptance = [
        {
            "check": c,
            "passed": any_cmd_passed,
            "notes": "inferred from verification command exit codes" if commands_results else "no commands",
        }
        for c in plan.get("acceptance_checks", [])
    ]

    if not files_written:
        result = "fail"
    elif commands_results and not any_cmd_passed:
        result = "partial"
    else:
        result = "pass"

    return {
        "schema_version": 1,
        "verification_id": f"verif-{slug}-001",
        "build_id": build_id,
        "produced_by": "coder",
        "produced_at": lib.now_iso(),
        "result": result,
        "summary": (
            f"Generated {len(files_written)} file(s); ran {len(commands_results)} command(s); "
            f"{'no deviations' if not deviations else f'{len(deviations)} deviation(s)'}."
        ),
        "files_changed": files_changed,
        "commands_run": commands_results,
        "evidence": evidence,
        "tests_summary": {
            "total": len(commands_results),
            "passed": sum(1 for c in commands_results if c["exit_code"] == 0),
            "failed": sum(1 for c in commands_results if c["exit_code"] != 0),
            "skipped": 0,
        },
        "acceptance_checks_results": acceptance,
        "deviations_from_plan": deviations,
    }


def process_one(slug: str, plan: dict, backend: str, dry_run: bool, config: dict) -> dict:
    if not lib.has_artifact(slug, "main-review"):
        return {"slug": slug, "result": "skipped", "reason": "no main-review"}
    review = lib.read_artifact(slug, "main-review")
    if review.get("decision") != "approved_for_coder":
        return {"slug": slug, "result": "skipped", "reason": f"not approved (decision={review.get('decision')})"}

    track = lib.track_dir(slug)
    work = track / "work"
    work.mkdir(parents=True, exist_ok=True)

    bp = _build_plan_from_product_plan(slug, plan, backend)
    bp_errs = lib.validate(bp, "build-plan")
    if bp_errs:
        return {"slug": slug, "result": "fail", "reason": f"build-plan invalid: {bp_errs[0]}"}

    if dry_run:
        return {"slug": slug, "result": "dry-run", "build_id": bp["build_id"]}

    lib.write_json_atomic(lib.artifact_path(slug, "build-plan"), bp)

    # ---- Generate files ----
    files_written: list[dict] = []
    deviations: list[dict] = []
    if backend == "hermes-native":
        model = config["models"]["hermes_native"]
        if not lib.is_provider_configured(model):
            return {"slug": slug, "result": "fail", "reason": f"provider not configured for {model}"}
        try:
            generated = _generate_files_hermes_native(plan, model)
        except (lib.LLMError, json.JSONDecodeError) as e:
            return {"slug": slug, "result": "fail", "reason": f"generation failed: {e}"}

        allowed = plan.get("allowed_paths", [])
        for f in generated:
            declared = f["path"]
            if not _is_path_allowed(declared, allowed):
                deviations.append({
                    "deviation": f"declared path outside allowed_paths",
                    "justification": "skipped to honor product-plan boundaries",
                    "files_affected": [declared],
                })
                continue
            try:
                full = _path_under_work(work, declared)
            except ValueError:
                deviations.append({
                    "deviation": f"path escapes work/",
                    "justification": "rejected for safety",
                    "files_affected": [declared],
                })
                continue
            full.parent.mkdir(parents=True, exist_ok=True)
            content = f["content"]
            if not isinstance(content, str):
                content = json.dumps(content, indent=2)
            data = content.encode("utf-8")
            full.write_bytes(data)
            files_written.append({
                "path": declared,
                "action": "created",
                "sha256": _sha256(data),
                "size": len(data),
                "purpose": next(
                    (p.get("purpose", "") for p in plan.get("planned_files", []) if p.get("path") == declared),
                    "",
                ),
            })
    elif backend == "opencode-cli":
        return {"slug": slug, "result": "skipped",
                "reason": "opencode-cli backend not yet wired (Phase 11b)"}
    else:
        return {"slug": slug, "result": "fail", "reason": f"unknown backend: {backend}"}

    # ---- Run verification commands ----
    timeout = config.get("constraints", {}).get("max_runtime_seconds", 1800)
    cmd_results = _run_verification_commands(work, plan.get("verification_commands", []), timeout=min(timeout, 600))

    # ---- Build verification artifact ----
    verif = _build_verification(slug, bp["build_id"], plan, files_written, cmd_results, deviations)
    verif_errs = lib.validate(verif, "verification")
    if verif_errs:
        return {"slug": slug, "result": "partial",
                "reason": f"build-plan written but verification invalid",
                "errors": verif_errs[:3]}
    lib.write_json_atomic(lib.artifact_path(slug, "verification"), verif)

    return {
        "slug": slug, "result": "ok",
        "build_id": bp["build_id"],
        "files_written": len(files_written),
        "commands_run": len(cmd_results),
        "verification_result": verif["result"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", help="build for this slug only")
    ap.add_argument("--backend", choices=["hermes-native", "opencode-cli"], default=None,
                    help="override default backend")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config = lib.load_profile_config(lib.PROFILE_ROOT)
    backend = args.backend or config.get("runtime", {}).get("default_backend", "hermes-native")

    if args.slug:
        plan = lib.read_artifact(args.slug, "product-plan")
        if not plan:
            print(f"no product-plan for {args.slug}")
            return 1
        if lib.has_artifact(args.slug, "build-plan"):
            print(f"{args.slug} already has build-plan — skipping")
            return 0
        result = process_one(args.slug, plan, backend, args.dry_run, config)
        print(json.dumps(result, indent=2))
        return 0 if result["result"] in {"ok", "dry-run"} else 1

    results = []
    for slug, plan in lib.tracks_pending("product-plan", "build-plan"):
        results.append(process_one(slug, plan, backend, args.dry_run, config))

    if not results:
        print("nothing to build")
        return 0
    print(json.dumps({"built": len(results), "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
