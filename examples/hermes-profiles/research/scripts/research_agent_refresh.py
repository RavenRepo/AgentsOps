#!/usr/bin/env python3
"""
research_agent_refresh.py — entry point for the research-agent profile.

Modes:  bootstrap | refresh | daily_summary | subc_brief | midday_focus | backup | restore | recover

Phase 8b: refresh now actually collects from RSS + GitHub, runs LLM-backed
finding extraction, updates ledgers, and emits a real research-input.json.

Run from the profile root:
    python scripts/research_agent_refresh.py --mode refresh
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402
from collectors import all_collectors  # noqa: E402
from extractors import extract_findings, extract_claims  # noqa: E402

MODES = [
    "bootstrap", "refresh", "daily_summary", "subc_brief",
    "midday_focus", "backup", "restore", "recover",
]


def _now() -> str:
    return lib.now_iso()


def _run_id() -> str:
    return lib.now_run_id()


# ---------------------------------------------------------------------------
# Source plan loader (parses YAML-ish config from source-plan.md)
# ---------------------------------------------------------------------------

def _load_source_plan() -> dict:
    """Parse the source-plan.yaml side-file (if present) for collector configs."""
    yaml_path = lib.CONTEXT_DIR / "source-plan.yaml"
    if not yaml_path.exists():
        return {"collectors": {}}
    import yaml  # type: ignore[import-untyped]
    with yaml_path.open() as f:
        return yaml.safe_load(f) or {"collectors": {}}


def _topic_slugs() -> list[str]:
    if not lib.INTEREST_PROFILE_JSON.exists():
        return []
    profile = json.loads(lib.INTEREST_PROFILE_JSON.read_text())
    return [t["topic"] for t in profile.get("topics", []) if t.get("topic")]


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def mode_bootstrap(config: dict) -> dict:
    print("[bootstrap] creating vault structure...")
    lib.ensure_dirs()
    if not lib.INTEREST_PROFILE_JSON.exists():
        lib.INTEREST_PROFILE_JSON.write_text(json.dumps({
            "schema_version": 1, "owner": "goku", "topics": [],
            "_note": "Edit topics. Each: {topic, why, weight}",
        }, indent=2))
        print("[bootstrap] wrote stub interest-profile.json")
    if not lib.SOURCE_PLAN_MD.exists():
        lib.SOURCE_PLAN_MD.write_text("# Source plan\n\nSee source-plan.yaml for collector config.\n")
        print("[bootstrap] wrote stub source-plan.md")
    return {"mode": "bootstrap", "result": "ok"}


def mode_refresh(config: dict) -> dict:
    run_id = _run_id()
    print(f"[refresh] run_id={run_id}")
    lib.ensure_dirs()

    # Provider gate — fail loud and early
    extractor_model = config["models"].get("finding_extraction") or config["models"]["default"]
    if not lib.is_provider_configured(extractor_model):
        return {"mode": "refresh", "result": "skipped",
                "reason": f"provider not configured for {extractor_model}",
                "run_id": run_id}

    topics = _topic_slugs()
    if not topics:
        return {"mode": "refresh", "result": "fail",
                "reason": "interest-profile.json has no topics — edit it before refresh",
                "run_id": run_id}

    plan = _load_source_plan()
    collectors_cfg = plan.get("collectors", {})

    # Run each enabled collector
    raw_dir = lib.raw_run_dir(run_id)
    all_items: list[dict] = []
    collector_results: dict[str, dict] = {}
    degraded: list[str] = []
    for name, collector in all_collectors().items():
        cfg = collectors_cfg.get(name, {})
        if cfg.get("enabled") is False:
            continue
        max_items = cfg.get("max_items", 20)
        result = collector.collect(cfg, topics, max_items=max_items)
        collector_results[name] = {
            "items_collected": result.items_collected,
            "sources_scanned": result.sources_scanned,
            "duration_seconds": result.duration_seconds,
            "success": result.success,
            "error": result.error,
        }
        if not result.success:
            degraded.append(name)
            print(f"[refresh] WARN: collector {name} degraded: {result.error}")
            continue
        # Save raw capture
        (raw_dir / f"{name}.json").write_text(json.dumps(
            [r for r in result.items], indent=2
        ))
        all_items.extend(result.items)
        print(f"[refresh] collector={name} items={result.items_collected} "
              f"sources={result.sources_scanned} {result.duration_seconds}s")

    # LLM-backed finding extraction
    print(f"[refresh] extracting findings from {len(all_items)} raw items via {extractor_model}")
    findings = extract_findings(all_items, topics, extractor_model)
    print(f"[refresh] extracted {len(findings)} relevant findings")

    # Append to ledgers (knowledge layer)
    for f in findings:
        lib.append_jsonl(lib.FINDINGS_LEDGER, f)
        # Source ledger entry too
        src = f["source"]
        lib.append_jsonl(lib.SOURCES_LEDGER, {
            "source_id": src["source_id"],
            "source_type": src["source_type"],
            "url": src.get("url", ""),
            "captured_at": src.get("captured_at"),
            "topic": f["topic"],
            "first_seen_run": run_id,
        })

    # Per-topic counts for the artifact
    topic_counts: dict[str, int] = {t: 0 for t in topics}
    for f in findings:
        topic_counts[f["topic"]] = topic_counts.get(f["topic"], 0) + 1

    artifact_topics = [
        {"topic": t, "findings_count": topic_counts.get(t, 0),
         "claims_count": 0, "verification_pending": 0}
        for t in topics
    ]

    # ---- C1: SECOND-PASS — turn findings into claims, write claims.jsonl ----
    claim_model = (
        config["models"].get("claim_synthesis")
        or config["models"].get("claim_extraction")
        or config["models"].get("synthesis")
        or extractor_model
    )
    print(f"[refresh] extracting claims from {len(findings)} findings via {claim_model}")
    claim_pairs, queue_entries = extract_claims(findings, topics, claim_model)
    print(f"[refresh] extracted {len(claim_pairs)} claims; {len(queue_entries)} go to verification queue")

    # Append claim ledger records (full shape with rationale + produced_at)
    for cp in claim_pairs:
        lib.append_jsonl(lib.CLAIMS_LEDGER, cp["_ledger"])

    # Per-topic claim + verification-pending counts
    claims_per_topic: dict[str, int] = {t: 0 for t in topics}
    pending_per_topic: dict[str, int] = {t: 0 for t in topics}
    for cp in claim_pairs:
        sc = cp["_schema"]
        for t in sc["topics"]:
            if t in claims_per_topic:
                claims_per_topic[t] += 1
                if sc["verification_status"] == "unverified":
                    pending_per_topic[t] += 1

    # Update artifact_topics with claim counts
    for at in artifact_topics:
        at["claims_count"] = claims_per_topic.get(at["topic"], 0)
        at["verification_pending"] = pending_per_topic.get(at["topic"], 0)

    schema_claims = [cp["_schema"] for cp in claim_pairs]
    # ---- C2: write verification queue files ----
    leads_path = lib.QUEUE_DIR / "verification-leads.json"
    review_md = lib.QUEUE_DIR / "verification-review.md"
    lib.QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    lib.write_json_atomic(leads_path, {
        "schema_version": 1,
        "produced_at": _now(),
        "run_id": f"research-{run_id}",
        "leads": queue_entries,
    })
    # Human-readable verification queue
    lines = ["# Verification queue", "",
             f"_Generated: {_now()} · run: research-{run_id}_", ""]
    if not queue_entries:
        lines.append("_No claims need verification right now._")
    else:
        # Index claims by id for fast lookup
        cmap = {cp["_schema"]["claim_id"]: cp for cp in claim_pairs}
        by_topic_q: dict[str, list[dict]] = {}
        for q in queue_entries:
            by_topic_q.setdefault(q["topic"], []).append(q)
        for topic, qs in sorted(by_topic_q.items()):
            lines.append(f"## {topic} ({len(qs)})")
            for q in qs:
                cp = cmap.get(q["claim_id"])
                if not cp:
                    continue
                stmt = cp["_schema"]["statement"]
                reason = q["reason"]
                lines.append(f"- **[{reason}]** {stmt}")
                lines.append(f"  - claim_id: `{q['claim_id']}`  · supporting: {len(cp['_schema']['supporting_evidence'])}")
            lines.append("")
    lib.write_atomic(review_md, "\n".join(lines) + "\n")
    print(f"[refresh] wrote {leads_path.relative_to(lib.PROFILE_ROOT)} + {review_md.relative_to(lib.PROFILE_ROOT)}")

    primary = sum(1 for it in all_items if it.get("source_type") in {"github-release", "official-blog"})
    secondary = sum(1 for it in all_items if it.get("source_type") == "rss")
    social = sum(1 for it in all_items if it.get("source_type") in {"x", "twitter"})

    artifact = {
        "schema_version": 1,
        "run_id": f"research-{run_id}",
        "produced_by": "research-agent",
        "produced_at": _now(),
        "run_mode": "refresh",
        "topics": artifact_topics,
        "new_findings": [
            {
                "finding_id": f["finding_id"],
                "topic": f["topic"],
                "summary": f["summary"],
                "source": f["source"],
                "strength": f["strength"],
            }
            for f in findings[:30]  # cap for artifact size
        ],
        "new_claims": schema_claims[:30],  # cap for artifact size
        "verification_queue": [
            {"claim_id": q["claim_id"], "reason": q["reason"]}
            for q in queue_entries[:30]
        ],
        "source_quality": {
            "primary_count": primary,
            "secondary_count": secondary,
            "social_count": social,
            "degraded_collectors": degraded,
        },
        "summary": (
            f"Refreshed {len(all_items)} items from {len(collector_results)} collectors. "
            f"Promoted {len(findings)} relevant findings and {len(claim_pairs)} claims "
            f"across {sum(1 for c in topic_counts.values() if c > 0)} topics. "
            f"{len(queue_entries)} claims need verification."
            + (f" Degraded: {', '.join(degraded)}." if degraded else "")
        ),
    }

    errs = lib.validate(artifact, "research-input")
    if errs:
        print("[refresh] WARN: artifact validation failed:")
        for e in errs[:3]:
            print(f"  - {e}")
        return {"mode": "refresh", "result": "fail", "run_id": run_id, "errors": errs[:5]}

    out = lib.research_input_path(f"research-{run_id}")
    lib.write_json_atomic(out, artifact)

    # Run receipt
    receipt = {
        "run_id": run_id,
        "produced_at": _now(),
        "collectors": collector_results,
        "findings_count": len(findings),
        "claims_count": len(claim_pairs),
        "verification_pending": len(queue_entries),
        "artifact": str(out.relative_to(lib.PROFILE_ROOT)),
    }
    lib.write_json_atomic(lib.run_receipt_path(run_id), receipt)

    print(f"[refresh] wrote {out.name}")
    return {"mode": "refresh", "result": "ok", "run_id": run_id,
            "items_collected": len(all_items),
            "findings_promoted": len(findings),
            "claims_promoted": len(claim_pairs),
            "verification_pending": len(queue_entries),
            "artifact": str(out.relative_to(lib.PROFILE_ROOT))}


def mode_daily_summary(config: dict) -> dict:
    """Render a real LLM-narrative daily digest from the latest research-input.

    Reads the latest research-input.json, asks the synthesis model to write a
    short operator-facing narrative, and saves to notes/daily-summary.md.
    """
    print("[daily_summary] running...")
    lib.ensure_dirs()
    candidates = sorted(lib.VAULT.glob("research-*.research-input.json"), reverse=True)
    if not candidates:
        return {"mode": "daily_summary", "result": "skipped",
                "reason": "no research-input artifacts yet"}

    artifact = json.loads(candidates[0].read_text())
    model = config["models"].get("daily_summary") or config["models"]["default"]
    if not lib.is_provider_configured(model):
        return {"mode": "daily_summary", "result": "skipped",
                "reason": f"provider not configured for {model}"}

    findings = artifact.get("new_findings", [])[:30]
    topics = artifact.get("topics", [])
    summary_input = {
        "topics_active": [t["topic"] for t in topics if t.get("findings_count", 0) > 0],
        "new_findings": findings,
        "summary_blob": artifact.get("summary", ""),
    }

    user_msg = (
        "Write a daily research digest for the operator (Goku).\n"
        "200-400 words. Markdown.\n"
        "Sections:\n"
        "  1. ## What changed today (2-4 bullets - the most actionable signals)\n"
        "  2. ## Notable findings by topic (group findings by topic, max 6 bullets)\n"
        "  3. ## What to watch (1-2 bullets - returns/follow-ups suggested)\n"
        "Be specific, not generic. Quote what matters. Skip topics with no findings.\n\n"
        f"Data:\n```json\n{json.dumps(summary_input, indent=2)[:8000]}\n```"
    )
    try:
        digest_md = lib.call_model(
            model=model,
            messages=[
                {"role": "system", "content": "You are Goku's research-agent writing the daily operator digest. Concise, factual, no fluff."},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=1500,
            timeout=120,
        )
    except lib.LLMError as e:
        return {"mode": "daily_summary", "result": "fail", "reason": f"LLM error: {e}"}

    header = f"# Daily research digest — {lib.now_iso()}\n_Source: {candidates[0].name}_\n\n"
    lib.write_atomic(lib.DAILY_SUMMARY, header + digest_md.strip() + "\n")
    return {"mode": "daily_summary", "result": "ok",
            "wrote": str(lib.DAILY_SUMMARY.relative_to(lib.PROFILE_ROOT)),
            "input_artifact": candidates[0].name,
            "findings_summarized": len(findings)}


def mode_subc_brief(config: dict) -> dict:
    """Pattern-facing brief for the dreamer's inbox.

    Compact summary that goes into dreamer/workspace/room/inbox-from-research/.
    Dreamer's drift_from_research walk reads this on next walk.
    """
    print("[subc_brief] running...")
    lib.ensure_dirs()
    candidates = sorted(lib.VAULT.glob("research-*.research-input.json"), reverse=True)
    if not candidates:
        return {"mode": "subc_brief", "result": "skipped",
                "reason": "no research-input artifacts yet"}
    artifact = json.loads(candidates[0].read_text())

    # Drop a copy of the full research-input directly into dreamer's inbox.
    dreamer_inbox = Path("os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/hermes/workspace/profiles/dreamer/workspace/room/inbox-from-research")
    dreamer_inbox.mkdir(parents=True, exist_ok=True)
    target = dreamer_inbox / candidates[0].name
    target.write_text(json.dumps(artifact, indent=2))

    # Optionally also a short LLM-shaped pattern brief
    model = config["models"].get("subc_brief") or config["models"]["default"]
    if lib.is_provider_configured(model):
        findings = artifact.get("new_findings", [])[:15]
        try:
            brief = lib.call_model(
                model=model,
                messages=[
                    {"role": "system", "content": (
                        "You are writing a pattern-facing brief for the Dreamer agent. "
                        "Dreamer drifts on this — surface what RETURNS, what catches, what hints at "
                        "a build opportunity. NOT a summary. 6-12 short bullets."
                    )},
                    {"role": "user", "content": (
                        f"Recent findings:\n{json.dumps(findings, indent=2)[:6000]}\n\n"
                        "What's worth noticing for the next drift walk?"
                    )},
                ],
                temperature=0.4,
                max_tokens=800,
                timeout=90,
            )
            brief_path = dreamer_inbox / f"brief-{candidates[0].stem}.md"
            brief_path.write_text(f"# Subc brief — {lib.now_iso()}\n\n{brief.strip()}\n")
        except lib.LLMError as e:
            print(f"[subc_brief] WARN: pattern brief failed: {e}")

    return {"mode": "subc_brief", "result": "ok",
            "delivered_to": str(target),
            "from": candidates[0].name}


def mode_midday_focus(config: dict) -> dict:
    """No scrape — rebuild operator surfaces from existing artifacts."""
    print("[midday_focus] rebuilding operator surfaces (no scrape)")
    lib.ensure_dirs()
    # Trigger the cockpit aggregator (regenerates summary + HTML)
    import subprocess
    rc = subprocess.run([
        "os.environ.get("BUILDROOM_PATH", "os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/buildroom")/.venv/bin/python",
        "os.environ.get("BUILDROOM_PATH", "os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/buildroom")/scripts/aggregator.py",
        "--render",
    ])
    return {"mode": "midday_focus", "result": "ok" if rc.returncode == 0 else "fail",
            "exit_code": rc.returncode}


def mode_backup(config: dict) -> dict:
    """Snapshot the vault to os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/backups/ as tar.gz."""
    import tarfile
    backup_dir = Path("os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/backups/research-vault")
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = lib.now_run_id()
    archive = backup_dir / f"research-vault-{ts}.tar.gz"
    print(f"[backup] writing {archive}...")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(lib.VAULT, arcname="research-vault")
    size = archive.stat().st_size
    return {"mode": "backup", "result": "ok",
            "archive": str(archive), "size_bytes": size}


def mode_restore(config: dict, args) -> dict:
    """Restore vault from a backup. Use --latest to pick most recent. Without --force, dry-run only."""
    import tarfile
    backup_dir = Path("os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/backups/research-vault")
    if not backup_dir.exists():
        return {"mode": "restore", "result": "fail", "reason": "no backups dir"}
    archives = sorted(backup_dir.glob("research-vault-*.tar.gz"), reverse=True)
    if not archives:
        return {"mode": "restore", "result": "fail", "reason": "no archives found"}
    target = archives[0] if args.latest else None
    if target is None:
        return {"mode": "restore", "result": "skipped",
                "reason": "specify --latest to pick most recent",
                "available": [a.name for a in archives[:5]]}

    if args.dry_run:
        return {"mode": "restore", "result": "dry-run",
                "would_restore": target.name, "size_bytes": target.stat().st_size}

    if not args.force:
        return {"mode": "restore", "result": "skipped",
                "reason": "pass --force to actually restore (this overwrites the vault!)"}

    # Move existing vault aside first
    bak = lib.VAULT.with_suffix(f".pre-restore-{lib.now_run_id()}")
    if lib.VAULT.exists():
        lib.VAULT.rename(bak)
    with tarfile.open(target, "r:gz") as tar:
        tar.extractall(path=lib.VAULT.parent)
    return {"mode": "restore", "result": "ok",
            "restored_from": target.name,
            "previous_vault_renamed_to": str(bak)}


def mode_recover(config: dict) -> dict:
    """One-command: latest backup restore + refresh."""
    return {"mode": "recover", "result": "deferred",
            "reason": "use just restore --latest --force, then just refresh"}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=MODES)
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    config = lib.load_profile_config(lib.PROFILE_ROOT)
    handlers = {
        "bootstrap":     lambda: mode_bootstrap(config),
        "refresh":       lambda: mode_refresh(config),
        "daily_summary": lambda: mode_daily_summary(config),
        "subc_brief":    lambda: mode_subc_brief(config),
        "midday_focus":  lambda: mode_midday_focus(config),
        "backup":        lambda: mode_backup(config),
        "restore":       lambda: mode_restore(config, args),
        "recover":       lambda: mode_recover(config),
    }
    receipt = handlers[args.mode]()
    print(json.dumps(receipt, indent=2))
    return 0 if receipt.get("result") in {"ok", "deferred", "skipped"} else 1


if __name__ == "__main__":
    sys.exit(main())
