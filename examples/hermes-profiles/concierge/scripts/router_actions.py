"""
router_actions.py — concierge's tools for reading + acting on the agency.

All read functions return structured dicts (safe to JSON-encode for prompt context).
All write functions append a `concierge-*` event to events.jsonl.

Read primitives (Slice 1 — safe, no mutations):
  read_trust_state()
  read_kanban()
  read_events_tail(n=20)
  read_content_tracks()
  read_content_vault_status()
  read_voice_status()
  read_agent_runtime_status()
  read_research_summary()
  read_dreamer_room()
  read_active_regressions()
  read_qa_rerun_queue()

Write primitives (Slice 2 — mutate state, log every action):
  seed_content_track(topic, intent, platforms, slug=None)
  draft_content(slug, platform=None)
  humanize_content(slug, platform=None)
  editor_review_content(slug)
  capture_post_receipt(slug, platform, post_url, post_id=None)
  promote_idea(slug)
  create_kanban_task(profile, title, body)
  request_trust_sweep()
  request_research_refresh()

Every write returns a dict shaped like {"result": "ok"|"fail"|"skipped", ...}
and writes a structured event to state/events.jsonl.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402

VALID_PLATFORMS = {"medium", "x", "linkedin", "substack"}
VALID_PROFILES = {
    "research", "dreamer", "main", "coder", "qa", "trust", "retention",
    "content-knowledge", "content-studio", "concierge",
}


def _emit_event(kind: str, payload: dict) -> None:
    event = {"event": f"concierge-{kind}", "logged_at": lib.now_iso(), **payload}
    lib.append_jsonl(lib.EVENTS_LEDGER, event)


def _slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:max_len] or "untitled"


# ---------------------------------------------------------------------------
# READ primitives (Slice 1)
# ---------------------------------------------------------------------------

def _safe_load_json(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


def _safe_load_jsonl(p: Path, n: int | None = None) -> list[dict]:
    if not p.exists():
        return []
    try:
        lines = p.read_text().splitlines()
    except OSError:
        return []
    if n is not None:
        lines = lines[-n:]
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def read_trust_state() -> dict:
    report = _safe_load_json(lib.STATE_DIR / "trust-report.json", {})
    if not report:
        return {"available": False, "reason": "no trust-report yet"}
    return {
        "available": True,
        "trust_state": report.get("trust_state"),
        "previous_trust_state": report.get("previous_trust_state"),
        "summary": report.get("summary"),
        "produced_at": report.get("produced_at"),
        "metrics": report.get("metrics", {}),
        "recent_concerns": report.get("recent_concerns", [])[:8],
        "recommendations": report.get("recommendations", [])[:6],
        "transition_reason": report.get("state_transition_reason"),
    }


def read_kanban() -> dict:
    summary = _safe_load_json(lib.STATE_DIR / "operator-summary.json", {})
    lanes = summary.get("lanes", {}) or {}

    def lane_items(lane: str) -> list:
        v = lanes.get(lane)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            return v.get("items") or []
        return []

    def to_slug(it):
        if isinstance(it, str):
            return it
        if isinstance(it, dict):
            return it.get("slug") or it.get("id") or it.get("name") or "?"
        return str(it)

    return {
        "produced_at": summary.get("produced_at"),
        "lanes": {
            lane: [to_slug(i) for i in lane_items(lane)]
            for lane in ("watching", "ready", "queued", "active", "built", "ghost", "broken")
        },
    }


def read_events_tail(n: int = 20) -> dict:
    events = _safe_load_jsonl(lib.EVENTS_LEDGER, n=n)
    return {"count": len(events), "events": events}


def read_content_tracks() -> dict:
    tracks_dir = lib.CONTENT_VAULT / "tracks"
    out = {"tracks": [], "by_status": {}, "total": 0}
    if not tracks_dir.exists():
        return out
    for slug_dir in sorted(tracks_dir.iterdir()):
        if not slug_dir.is_dir():
            continue
        manifest = slug_dir / f"{slug_dir.name}.content-track.json"
        if not manifest.exists():
            continue
        m = _safe_load_json(manifest, {})
        if not m:
            continue
        # Editor verdict if present
        editor = _safe_load_json(slug_dir / f"{slug_dir.name}.editor-review.json", {})
        out["tracks"].append({
            "slug": slug_dir.name,
            "topic": m.get("topic"),
            "platforms": m.get("platforms", []),
            "status": m.get("status"),
            "produced_at": m.get("produced_at"),
            "editor_verdict": editor.get("verdict"),
            "selected_draft_id": editor.get("selected_draft_id"),
        })
        s = m.get("status", "unknown")
        out["by_status"][s] = out["by_status"].get(s, 0) + 1
        out["total"] += 1
    return out


def read_content_vault_status() -> dict:
    out = {"platforms": [], "performance_ledger_lines": 0}
    for plat in ("medium", "x", "linkedin", "substack", "seo"):
        vd = lib.CONTENT_VAULT / f"{plat}-vault"
        if not vd.exists():
            continue
        f = vd / "findings.jsonl"
        a = vd / "algo-watch.jsonl"
        f_n = sum(1 for _ in f.read_text().splitlines() if _.strip()) if f.exists() else 0
        a_n = sum(1 for _ in a.read_text().splitlines() if _.strip()) if a.exists() else 0
        pb_json = lib.CONTENT_VAULT / "playbooks" / f"{plat}-playbook.json"
        last_refresh = None
        if pb_json.exists():
            j = _safe_load_json(pb_json, {})
            last_refresh = j.get("produced_at")
        out["platforms"].append({
            "platform": plat,
            "findings": f_n,
            "algo_watch": a_n,
            "playbook_present": pb_json.exists(),
            "last_refresh": last_refresh,
        })
    perf = lib.CONTENT_VAULT / "performance-ledger.jsonl"
    if perf.exists():
        out["performance_ledger_lines"] = sum(1 for _ in perf.read_text().splitlines() if _.strip())
    return out


def read_voice_status() -> dict:
    voice_md = lib.CONTENT_VAULT / "humanizer" / "voice.md"
    if not voice_md.exists():
        return {"present": False, "samples_populated": 0, "ready": False}
    try:
        content = voice_md.read_text()
    except OSError:
        return {"present": False, "samples_populated": 0, "ready": False}
    populated = 0
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("### Sample") and "(paste here)" not in line:
            populated += 1
    return {
        "present": True,
        "samples_populated": populated,
        "ready": populated >= 3,
        "path": str(voice_md),
    }


def read_agent_runtime_status() -> dict:
    out = {"profiles": []}
    if not lib.HERMES_PROFILES_ROOT.exists():
        return out
    for p in sorted(lib.HERMES_PROFILES_ROOT.iterdir()):
        if not p.is_dir():
            continue
        last_activity = None
        ws = p / "workspace"
        if ws.exists():
            try:
                latest = max(
                    (f.stat().st_mtime for f in ws.rglob("*") if f.is_file()),
                    default=None,
                )
                if latest:
                    last_activity = datetime.fromtimestamp(latest, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except (OSError, ValueError):
                pass
        out["profiles"].append({
            "profile": p.name,
            "last_activity": last_activity,
            "has_soul": (p / "SOUL.md").exists(),
        })
    return out


def read_research_summary() -> dict:
    """Latest research-input artifact + ledger sizes."""
    vault = Path("os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/hermes/workspace/profiles/research/workspace/research-vault")
    if not vault.exists():
        return {"available": False}

    artifacts = sorted(vault.glob("research-*.research-input.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    latest = _safe_load_json(artifacts[0], {}) if artifacts else {}
    knowledge = vault / "knowledge"

    def count_lines(p: Path) -> int:
        return sum(1 for _ in p.read_text().splitlines() if _.strip()) if p.exists() else 0

    return {
        "available": True,
        "latest_artifact": artifacts[0].name if artifacts else None,
        "produced_at": latest.get("produced_at"),
        "summary": (latest.get("summary") or "")[:600],
        "topics": latest.get("topics", []),
        "ledgers": {
            "findings": count_lines(knowledge / "findings.jsonl"),
            "claims":   count_lines(knowledge / "claims.jsonl"),
            "sources":  count_lines(knowledge / "sources.jsonl"),
        },
        "verification_queue_count": len((latest.get("verification_queue") or [])),
    }


def read_dreamer_room() -> dict:
    room = Path("os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/hermes/workspace/profiles/dreamer/workspace/room")
    if not room.exists():
        return {"available": False}
    walks_dir = room / "walks"
    retros_dir = room / "retrospectives"
    sprint_lock = room / "signal-state" / "sprint.lock"
    summary = _safe_load_json(room / "signal-state" / "summary.json", {})
    fascinations = (room / "fascinations.md").read_text()[:1500] if (room / "fascinations.md").exists() else ""
    lessons_path = room / "lessons.md"
    lessons_tail = ""
    if lessons_path.exists():
        try:
            content = lessons_path.read_text()
            # Just lessons (lines starting with -); skip header
            lessons_tail = "\n".join(l for l in content.splitlines() if l.startswith("- "))[-1500:]
        except OSError:
            pass

    return {
        "available": True,
        "walks_count": len(list(walks_dir.glob("*.json"))) if walks_dir.exists() else 0,
        "retrospectives_count": len(list(retros_dir.glob("*.md"))) if retros_dir.exists() else 0,
        "sprint_lock": _safe_load_json(sprint_lock, None),
        "lanes": (summary.get("lanes") or {}),
        "fascinations": fascinations,
        "lessons_tail": lessons_tail,
    }


def read_active_regressions() -> dict:
    return _safe_load_json(lib.STATE_DIR / "active-regressions.json",
                            {"regressions": [], "updated_at": None})


def read_qa_rerun_queue() -> dict:
    return _safe_load_json(lib.STATE_DIR / "qa-rerun-queue.json",
                            {"queue": [], "updated_at": None})


# ---------------------------------------------------------------------------
# WRITE primitives (Slice 2) — mutate state; every action emits an event
# ---------------------------------------------------------------------------

def _run_just(profile: str, recipe: str, *args: str, env: dict | None = None,
              timeout: int = 600) -> tuple[int, str, str]:
    """Run `just <recipe> <args>` in a profile dir. Returns (rc, stdout, stderr)."""
    profile_dir = lib.HERMES_PROFILES_ROOT / profile
    cmd = ["just", recipe, *args]
    proc = subprocess.run(
        cmd, cwd=str(profile_dir),
        capture_output=True, text=True, timeout=timeout, env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _run_python(script: Path, *args: str, env: dict | None = None,
                timeout: int = 600) -> tuple[int, str, str]:
    py = "os.environ.get("BUILDROOM_PATH", "os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/buildroom")/.venv/bin/python"
    cmd = [py, str(script), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return proc.returncode, proc.stdout, proc.stderr


def seed_content_track(topic: str, intent: str = "",
                        platforms: list[str] | None = None,
                        slug: str | None = None) -> dict:
    """Create a content-vault seed + manifest by invoking content-studio."""
    if not topic or not topic.strip():
        return {"result": "fail", "reason": "topic required"}
    plats = [p for p in (platforms or list(VALID_PLATFORMS)) if p in VALID_PLATFORMS]
    if not plats:
        return {"result": "fail", "reason": "no valid platforms"}
    use_slug = slug or _slugify(topic)
    args = ["seed", "--topic", topic, "--platforms", ",".join(plats), "--slug", use_slug]
    if intent:
        args.extend(["--intent", intent])
    rc, out, err = _run_python(
        lib.HERMES_PROFILES_ROOT / "content-studio" / "scripts" / "studio.py",
        *args,
    )
    payload = {"slug": use_slug, "topic": topic, "platforms": plats, "rc": rc}
    try:
        payload["receipt"] = json.loads(out.strip().splitlines()[-1]) if out else None
    except json.JSONDecodeError:
        payload["receipt"] = None
    _emit_event("seed-content", payload)
    if rc != 0:
        return {"result": "fail", "reason": err.strip() or out.strip(), **payload}
    return {"result": "ok", **payload}


def _studio_action(action: str, slug: str, platform: str | None = None) -> dict:
    """Run a content-studio mode (draft / humanize / editor-review)."""
    if action not in {"draft", "humanize", "editor-review"}:
        return {"result": "fail", "reason": f"unknown action {action}"}
    args = [action, "--slug", slug]
    if platform and action != "editor-review":
        if platform not in VALID_PLATFORMS:
            return {"result": "fail", "reason": f"invalid platform {platform}"}
        args.extend(["--platform", platform])
    rc, out, err = _run_python(
        lib.HERMES_PROFILES_ROOT / "content-studio" / "scripts" / "studio.py",
        *args,
        timeout=900,
    )
    payload = {"slug": slug, "action": action, "platform": platform, "rc": rc}
    try:
        payload["receipt"] = json.loads(out.strip().splitlines()[-1]) if out else None
    except json.JSONDecodeError:
        payload["receipt"] = None
    _emit_event(f"content-{action}", payload)
    if rc != 0:
        return {"result": "fail", "reason": err.strip() or out.strip(), **payload}
    return {"result": "ok", **payload}


def draft_content(slug: str, platform: str | None = None) -> dict:
    return _studio_action("draft", slug, platform)


def humanize_content(slug: str, platform: str | None = None) -> dict:
    return _studio_action("humanize", slug, platform)


def editor_review_content(slug: str) -> dict:
    return _studio_action("editor-review", slug)


def capture_post_receipt(slug: str, platform: str, post_url: str,
                         post_id: str | None = None,
                         account_handle: str | None = None) -> dict:
    """Write a schema-valid post-receipt for an operator-paste post."""
    if platform not in VALID_PLATFORMS:
        return {"result": "fail", "reason": f"invalid platform {platform}"}
    if not post_url or not post_url.startswith(("http://", "https://")):
        return {"result": "fail", "reason": "post_url must be http(s)://"}

    track_dir = lib.CONTENT_VAULT / "tracks" / slug
    if not track_dir.exists():
        return {"result": "fail", "reason": f"track {slug} not found"}
    receipt_id = f"receipt-{slug}-{platform}-{lib.now_run_id()}"
    receipt = {
        "schema_version": 1,
        "receipt_id": receipt_id,
        "track_id": slug,
        "platform": platform,
        "produced_by": "concierge",
        "produced_at": lib.now_iso(),
        "posting_mode": "operator-paste",
        "post_url": post_url,
    }
    if post_id:
        receipt["post_id"] = post_id
    if account_handle:
        receipt["account_handle"] = account_handle
    errs = lib.validate(receipt, "post-receipt")
    if errs:
        return {"result": "fail", "reason": "schema validation", "errors": errs[:3]}

    out_path = track_dir / f"post-receipt-{platform}.json"
    lib.write_json_atomic(out_path, receipt)

    # Update track status to "posted"
    manifest_path = track_dir / f"{slug}.content-track.json"
    if manifest_path.exists():
        m = _safe_load_json(manifest_path, {})
        if m:
            m["status"] = "posted"
            m["produced_at"] = lib.now_iso()
            lib.write_json_atomic(manifest_path, m)

    # Append to performance ledger as a marker
    lib.append_jsonl(lib.CONTENT_VAULT / "performance-ledger.jsonl", {
        "event": "post",
        "slug": slug,
        "platform": platform,
        "post_url": post_url,
        "captured_at": lib.now_iso(),
    })

    _emit_event("post-receipt", {"slug": slug, "platform": platform,
                                  "post_url": post_url, "receipt_id": receipt_id})
    return {"result": "ok", "receipt_id": receipt_id, "wrote": str(out_path)}


def promote_idea(slug: str) -> dict:
    """Force-promote a slug from dreamer's signal-board (sprint-locked)."""
    rc, out, err = _run_python(
        Path("os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/hermes/workspace/profiles/dreamer/scripts/promote.py"),
        "--slug", slug,
    )
    _emit_event("promote-idea", {"slug": slug, "rc": rc,
                                  "stdout": out[:500], "stderr": err[:500]})
    if rc != 0:
        return {"result": "fail", "reason": err.strip() or out.strip()}
    return {"result": "ok", "slug": slug, "stdout": out.strip()}


def create_kanban_task(profile: str, title: str, body: str = "") -> dict:
    """Drop a task into Hermes' kanban for a specific profile."""
    if profile not in VALID_PROFILES:
        return {"result": "fail", "reason": f"unknown profile {profile}"}
    if not title or not title.strip():
        return {"result": "fail", "reason": "title required"}
    env = {
        "HOME": "/var/lib/agents",
        "HERMES_HOME": "os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/hermes",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
    }
    cmd = [
        "hermes", "kanban", "create",
        "--title", title,
        "--assignee", profile,
    ]
    if body:
        cmd.extend(["--body", body])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    _emit_event("kanban-task", {"profile": profile, "title": title,
                                  "rc": proc.returncode,
                                  "stdout": proc.stdout[:500]})
    if proc.returncode != 0:
        return {"result": "fail", "reason": proc.stderr.strip() or proc.stdout.strip()}
    return {"result": "ok", "profile": profile, "title": title}


def request_trust_sweep() -> dict:
    rc, out, err = _run_python(
        Path("os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/hermes/workspace/profiles/trust/scripts/sweep.py"),
    )
    _emit_event("trust-sweep-requested", {"rc": rc, "stdout": out[:500]})
    if rc != 0:
        return {"result": "fail", "reason": err.strip() or out.strip()}
    return {"result": "ok", "stdout": out.strip()}


def request_research_refresh() -> dict:
    rc, out, err = _run_python(
        Path("os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/hermes/workspace/profiles/research/scripts/research_agent_refresh.py"),
        "--mode", "refresh",
        timeout=1200,
    )
    _emit_event("research-refresh-requested", {"rc": rc, "stdout": out[:500]})
    if rc != 0:
        return {"result": "fail", "reason": err.strip() or out.strip()}
    return {"result": "ok", "stdout": out.strip()}


# ---------------------------------------------------------------------------
# Action registry — concierge introspects this to know what's available
# ---------------------------------------------------------------------------

ACTIONS = {
    # READ
    "read_trust_state":          {"fn": read_trust_state, "kind": "read"},
    "read_kanban":               {"fn": read_kanban, "kind": "read"},
    "read_events_tail":          {"fn": read_events_tail, "kind": "read"},
    "read_content_tracks":       {"fn": read_content_tracks, "kind": "read"},
    "read_content_vault_status": {"fn": read_content_vault_status, "kind": "read"},
    "read_voice_status":         {"fn": read_voice_status, "kind": "read"},
    "read_agent_runtime_status": {"fn": read_agent_runtime_status, "kind": "read"},
    "read_research_summary":     {"fn": read_research_summary, "kind": "read"},
    "read_dreamer_room":         {"fn": read_dreamer_room, "kind": "read"},
    "read_active_regressions":   {"fn": read_active_regressions, "kind": "read"},
    "read_qa_rerun_queue":       {"fn": read_qa_rerun_queue, "kind": "read"},
    # WRITE
    "seed_content_track":        {"fn": seed_content_track, "kind": "write"},
    "draft_content":             {"fn": draft_content, "kind": "write"},
    "humanize_content":          {"fn": humanize_content, "kind": "write"},
    "editor_review_content":     {"fn": editor_review_content, "kind": "write"},
    "capture_post_receipt":      {"fn": capture_post_receipt, "kind": "write"},
    "promote_idea":              {"fn": promote_idea, "kind": "write"},
    "create_kanban_task":        {"fn": create_kanban_task, "kind": "write"},
    "request_trust_sweep":       {"fn": request_trust_sweep, "kind": "write"},
    "request_research_refresh":  {"fn": request_research_refresh, "kind": "write"},
}


def execute(action_name: str, args: dict) -> dict:
    if action_name not in ACTIONS:
        return {"result": "fail", "reason": f"unknown action {action_name}"}
    fn = ACTIONS[action_name]["fn"]
    try:
        return fn(**(args or {}))
    except TypeError as e:
        return {"result": "fail", "reason": f"bad args for {action_name}: {e}"}
    except Exception as e:
        _emit_event("action-error", {"action": action_name, "error": str(e)})
        return {"result": "fail", "reason": str(e)}
