#!/usr/bin/env python3
"""
sweep.py — read recent tracks, compute room trust state, write trust-report.

Run periodically. Reads:
  state/tracks/<slug>/<slug>.verification.json
  state/tracks/<slug>/<slug>.qa-verification.json
  state/tracks/<slug>/<slug>.verification-delta.json
  state/tracks/<slug>/<slug>.main-review.json
  state/trust-report.json (previous, if any, for state transitions)

Writes:
  state/trust-report.json   (canonical, schema-validated)
  state/trust-report.md     (human-readable, append-only)
  state/events.jsonl        (state-transition entry)

Trust state aggregate rule:
  - investigate if any track in window earns it (regression / disputed / blocking concern)
  - else watch if >= threshold drifts OR any major concern
  - else clean

Usage:
  python scripts/sweep.py            # normal run
  python scripts/sweep.py --dry-run  # compute + print, do not write
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        # Accept both "Z" and "+00:00" suffixes
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _within_window(ts: str | None, window_hours: int) -> bool:
    dt = _parse_iso(ts)
    if dt is None:
        return False
    now = datetime.now(timezone.utc)
    return dt >= now - timedelta(hours=window_hours)


def _load_track_artifacts(slug: str) -> dict[str, Any]:
    """Pull all known artifacts for a single track. Missing ones are None."""
    out: dict[str, Any] = {"slug": slug}
    for kind in ["verification", "qa-verification", "verification-delta", "main-review"]:
        try:
            out[kind] = lib.read_artifact(slug, kind)
        except Exception:
            out[kind] = None
    return out


def _per_track_class(track: dict, blocking_severity: str = "blocking",
                     major_severity: str = "major") -> dict:
    """Classify a single track's contribution to trust.

    Returns dict with: state ("clean"|"watch"|"investigate"), reason, evidence dict.
    """
    delta = track.get("verification-delta") or {}
    qa = track.get("qa-verification") or {}
    review = track.get("main-review") or {}

    delta_state = delta.get("delta_state")
    agreement = delta.get("agreement_state")
    qa_concerns = qa.get("concerns_raised") or []
    delta_concerns = delta.get("qa_concerns_unaddressed") or []
    blocking = [c for c in (qa_concerns + delta_concerns) if c.get("severity") == blocking_severity]
    major = [c for c in (qa_concerns + delta_concerns) if c.get("severity") == major_severity]
    force_approval = bool(review.get("force_approval"))
    risk_score = review.get("risk_score") or 0

    if delta_state in ("regression", "disputed") or blocking:
        state = "investigate"
        reasons = []
        if delta_state == "regression":
            reasons.append(f"delta_state=regression on {track['slug']}")
        if delta_state == "disputed":
            reasons.append(f"delta_state=disputed on {track['slug']}")
        if blocking:
            reasons.append(f"{len(blocking)} blocking concern(s) raised")
    elif delta_state == "drift" or delta_state == "missing_evidence" or major or agreement == "qa_caught_drift":
        state = "watch"
        reasons = []
        if delta_state == "drift":
            reasons.append(f"delta_state=drift on {track['slug']}")
        if delta_state == "missing_evidence":
            reasons.append(f"delta_state=missing_evidence on {track['slug']}")
        if major:
            reasons.append(f"{len(major)} major concern(s) raised")
        if agreement == "qa_caught_drift":
            reasons.append("qa caught drift independently")
    elif delta_state == "confirmed":
        state = "clean"
        reasons = ["delta confirmed"]
    else:
        # No delta yet — track in flight or pre-build. Don't count as clean.
        state = None
        reasons = ["no verification-delta yet"]

    return {
        "slug": track["slug"],
        "state": state,
        "reason": "; ".join(reasons),
        "delta_state": delta_state,
        "agreement_state": agreement,
        "blocking_count": len(blocking),
        "major_count": len(major),
        "force_approval": force_approval,
        "risk_score": risk_score,
        "qa_concerns": qa_concerns + delta_concerns,
    }


def _compute_metrics(track_classes: list[dict]) -> dict:
    builds_total = sum(1 for c in track_classes if c["state"] is not None)
    qa_pass = sum(1 for c in track_classes if c["delta_state"] == "confirmed")
    qa_fail = sum(1 for c in track_classes if c["delta_state"] in ("regression", "disputed"))
    full_agree = sum(1 for c in track_classes if c["agreement_state"] == "full_agreement")
    partial_agree = sum(1 for c in track_classes if c["agreement_state"] == "partial_agreement")
    disagree = sum(1 for c in track_classes if c["agreement_state"] == "disagreement")
    qa_caught = sum(1 for c in track_classes if c["agreement_state"] == "qa_caught_drift")
    regressions = sum(1 for c in track_classes if c["delta_state"] == "regression")
    forced = sum(1 for c in track_classes if c["force_approval"])
    risks = [c["risk_score"] for c in track_classes if c["risk_score"]]
    avg_risk = round(sum(risks) / len(risks), 2) if risks else 0
    return {
        "builds_total": builds_total,
        "builds_passed": qa_pass,
        "builds_failed": qa_fail,
        "deltas_full_agreement": full_agree,
        "deltas_partial_agreement": partial_agree,
        "deltas_disagreement": disagree,
        "qa_caught_drift_count": qa_caught,
        "regressions_detected": regressions,
        "force_approvals_used": forced,
        "average_risk_score": avg_risk,
    }


def _aggregate_state(track_classes: list[dict], thresholds: dict) -> tuple[str, str]:
    """Return (trust_state, reason)."""
    investigate = [c for c in track_classes if c["state"] == "investigate"]
    watch = [c for c in track_classes if c["state"] == "watch"]
    if investigate:
        return "investigate", "; ".join(c["reason"] for c in investigate[:3])
    if len(watch) >= int(thresholds.get("watch_after_drifts", 2)):
        return "watch", f"{len(watch)} tracks in watch state"
    if watch:
        return "watch", "; ".join(c["reason"] for c in watch[:3])
    return "clean", f"{len(track_classes)} tracks evaluated; no concerns"


def _previous_state() -> str | None:
    if not lib.TRUST_REPORT_JSON.exists():
        return None
    try:
        prev = json.loads(lib.TRUST_REPORT_JSON.read_text())
        return prev.get("trust_state")
    except (json.JSONDecodeError, OSError):
        return None


def _build_recent_concerns(track_classes: list[dict]) -> list[dict]:
    out = []
    seen = set()
    for c in track_classes:
        for q in c.get("qa_concerns") or []:
            key = (q.get("concern", "")[:80], q.get("severity"))
            if key in seen:
                continue
            seen.add(key)
            entry = {
                "concern": q.get("concern", "")[:1000],
                "severity": q.get("severity", "info"),
                "build_id": c["slug"],
                "occurrences": 1,
            }
            out.append(entry)
            if len(out) >= 20:
                return out
    return out


def _build_recommendations(track_classes: list[dict], state: str) -> list[dict]:
    recs = []
    if state == "investigate":
        regressions = [c for c in track_classes if c["delta_state"] == "regression"]
        if regressions:
            slugs = ", ".join(c["slug"] for c in regressions[:3])
            recs.append({
                "recommendation": f"Pause new promotions until regressions are reviewed: {slugs}",
                "for_agent": "main",
                "priority": "urgent",
            })
        blocking = [c for c in track_classes if c["blocking_count"] > 0]
        if blocking:
            slugs = ", ".join(c["slug"] for c in blocking[:3])
            recs.append({
                "recommendation": f"Resolve blocking concerns on: {slugs}",
                "for_agent": "qa",
                "priority": "urgent",
            })
    elif state == "watch":
        drifts = [c for c in track_classes if c["delta_state"] == "drift"]
        if drifts:
            slugs = ", ".join(c["slug"] for c in drifts[:3])
            recs.append({
                "recommendation": f"Review drift causes on: {slugs}",
                "for_agent": "qa",
                "priority": "normal",
            })
    return recs[:10]


def _render_md(report: dict) -> str:
    lines = []
    lines.append(f"# Trust report — {report['trust_state'].upper()}")
    lines.append("")
    lines.append(f"_run: {report['report_id']} · produced: {report['produced_at']}_  ")
    if report.get("previous_trust_state") and report["previous_trust_state"] != report["trust_state"]:
        lines.append(f"_state transition: **{report['previous_trust_state']} → {report['trust_state']}**_")
    lines.append("")
    if report.get("state_transition_reason"):
        lines.append(f"**Transition reason:** {report['state_transition_reason']}")
        lines.append("")
    lines.append("## Window")
    lines.append(f"- {report['window_start']} → {report['window_end']}")
    lines.append("")
    m = report["metrics"]
    lines.append("## Metrics")
    lines.append(f"- builds: total={m['builds_total']} · passed={m.get('builds_passed', 0)} · failed={m.get('builds_failed', 0)}")
    lines.append(f"- deltas: full={m.get('deltas_full_agreement', 0)} · partial={m.get('deltas_partial_agreement', 0)} · disagree={m.get('deltas_disagreement', 0)} · qa-caught-drift={m.get('qa_caught_drift_count', 0)}")
    lines.append(f"- regressions: {m.get('regressions_detected', 0)}")
    lines.append(f"- force-approvals used: {m.get('force_approvals_used', 0)}")
    lines.append(f"- avg risk score: {m.get('average_risk_score', 0)}")
    lines.append("")
    if report.get("recent_concerns"):
        lines.append("## Recent concerns")
        for c in report["recent_concerns"][:10]:
            lines.append(f"- **[{c['severity']}]** {c['concern']} _(build: {c.get('build_id', 'n/a')})_")
        lines.append("")
    if report.get("recommendations"):
        lines.append("## Recommendations")
        for r in report["recommendations"]:
            lines.append(f"- _[{r.get('priority', 'normal')}]_ → **{r.get('for_agent', 'operator')}**: {r['recommendation']}")
        lines.append("")
    if report.get("summary"):
        lines.append("## Summary")
        lines.append(report["summary"])
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="compute, print, do not write")
    args = ap.parse_args()

    config = lib.load_profile_config(lib.PROFILE_ROOT)
    lib.ensure_dirs()

    window_hours = int(config.get("window", {}).get("hours", 24))
    max_tracks = int(config.get("window", {}).get("max_tracks", 50))
    thresholds = config.get("thresholds", {})

    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(hours=window_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    window_end = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Enumerate tracks within window.
    all_tracks = lib.list_tracks()
    track_classes: list[dict] = []
    for slug in all_tracks[:max_tracks]:
        t = _load_track_artifacts(slug)
        # Use the verification-delta produced_at, else qa-verification, else verification
        ts = (
            (t.get("verification-delta") or {}).get("produced_at")
            or (t.get("qa-verification") or {}).get("produced_at")
            or (t.get("verification") or {}).get("produced_at")
        )
        if ts and not _within_window(ts, window_hours):
            continue
        track_classes.append(_per_track_class(t))

    metrics = _compute_metrics(track_classes)
    state, agg_reason = _aggregate_state(track_classes, thresholds)
    prev_state = _previous_state()

    report = {
        "schema_version": 1,
        "report_id": f"trust-{lib.now_run_id()}",
        "produced_by": "trust",
        "produced_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_start": window_start,
        "window_end": window_end,
        "trust_state": state,
        "metrics": metrics,
        "summary": (
            f"Evaluated {len(track_classes)} tracks in window. "
            f"State: {state}. {agg_reason}"
        ),
    }
    if prev_state:
        report["previous_trust_state"] = prev_state
        if prev_state != state:
            report["state_transition_reason"] = agg_reason
    rec_concerns = _build_recent_concerns(track_classes)
    if rec_concerns:
        report["recent_concerns"] = rec_concerns
    recs = _build_recommendations(track_classes, state)
    if recs:
        report["recommendations"] = recs

    # Validate
    errs = lib.validate(report, "trust-report")
    if errs:
        print(json.dumps({
            "result": "fail",
            "reason": "schema validation failed",
            "errors": errs[:5],
        }, indent=2))
        return 1

    if args.dry_run:
        print(json.dumps({"result": "dry-run", "report": report}, indent=2))
        return 0

    # Write
    lib.write_json_atomic(lib.TRUST_REPORT_JSON, report)
    # Append md (file is overwritten each run with the latest report;
    # historical reports are preserved via state/events.jsonl + the report_id-stamped JSON archive below)
    lib.write_atomic(lib.TRUST_REPORT_MD, _render_md(report))

    # On state transition, write to the events ledger
    if prev_state and prev_state != state:
        lib.append_jsonl(lib.EVENTS_LEDGER, {
            "event": "trust-state-transition",
            "from": prev_state,
            "to": state,
            "reason": agg_reason,
            "report_id": report["report_id"],
            "logged_at": report["produced_at"],
        })

    # Also archive a copy of every report under state/trust-history/ so we keep the trail
    archive_dir = lib.STATE_DIR / "trust-history"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / f"{report['report_id']}.json"
    lib.write_json_atomic(archive, report)

    print(json.dumps({
        "result": "ok",
        "trust_state": state,
        "previous_trust_state": prev_state,
        "tracks_evaluated": len(track_classes),
        "report_id": report["report_id"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
