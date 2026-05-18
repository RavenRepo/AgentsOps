#!/usr/bin/env python3
"""
notifier.py — proactive Telegram push notifier (Slice 3).

Runs every ~5 min via systemd timer. Reads:
  - state/events.jsonl (since last cursor)
  - state/trust-report.json
  - dreamer/inbox-from-research/<latest>.md (postcards)
  - content-vault/tracks (drafts ready)

Emits push messages to ALL TELEGRAM_ALLOWED_CHAT_IDS for events worth
surfacing. Rate-limits same-kind events to avoid spam.

Event kinds (each a Telegram push):
  - trust-state-transition      — state flipped (clean ↔ watch ↔ investigate)
  - delta-regression            — coder/qa disagreed; pause work
  - dreamer-postcard            — new postcard ready
  - draft-ready                 — editor verdict: ready
  - voice-md-empty              — daily nag if humanizer is still generic
  - chain-stuck                 — auto-loop ran but produced nothing for 24h+
  - active-regressions-cleared  — all regressions resolved
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402

CONFIG = lib.load_profile_config(lib.PROFILE_ROOT)


# ---------------------------------------------------------------------------
# Cursor + rate-limit persistence
# ---------------------------------------------------------------------------

def _read_cursor() -> dict:
    if not lib.NOTIFIER_CURSOR.exists():
        return {}
    try:
        return json.loads(lib.NOTIFIER_CURSOR.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_cursor(cur: dict) -> None:
    lib.ensure_dirs()
    lib.write_json_atomic(lib.NOTIFIER_CURSOR, cur)


def _read_rate_limit() -> dict:
    if not lib.NOTIFIER_RATE_LIMIT.exists():
        return {}
    try:
        return json.loads(lib.NOTIFIER_RATE_LIMIT.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_rate_limit(rl: dict) -> None:
    lib.ensure_dirs()
    lib.write_json_atomic(lib.NOTIFIER_RATE_LIMIT, rl)


def _rate_ok(kind: str, key: str = "") -> bool:
    """True if we haven't sent this (kind, key) in the last rate_limit window."""
    rl = _read_rate_limit()
    minutes = int(CONFIG["notifier"].get("rate_limit_per_event_kind_minutes", 30))
    rkey = f"{kind}|{key}"
    last = rl.get(rkey)
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    return datetime.now(timezone.utc) - last_dt >= timedelta(minutes=minutes)


def _rate_record(kind: str, key: str = "") -> None:
    rl = _read_rate_limit()
    rl[f"{kind}|{key}"] = lib.now_iso()
    _write_rate_limit(rl)


# ---------------------------------------------------------------------------
# Telegram send
# ---------------------------------------------------------------------------

def _bot_token() -> str:
    return (os.environ.get("TELEGRAM_BOT_TOKEN_CONCIERGE") or "").strip()


def _allowed_chat_ids() -> list[str]:
    raw = (os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS") or "").strip()
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def _send(chat_id: str, text: str) -> None:
    token = _bot_token()
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:3900],
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
    except urllib.error.HTTPError as e:
        # markdown parse error → retry plain
        if e.code == 400:
            payload.pop("parse_mode", None)
            req2 = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                           headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req2, timeout=20).read()
            except Exception as e2:
                print(f"[notifier] send retry failed: {e2}", file=sys.stderr)
        else:
            print(f"[notifier] send error: {e}", file=sys.stderr)
    except Exception as e:
        print(f"[notifier] send error: {e}", file=sys.stderr)


def _broadcast(text: str) -> None:
    for cid in _allowed_chat_ids():
        _send(cid, text)


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

def _check_events(cursor: dict) -> list[tuple[str, str, str]]:
    """Yield (kind, key, message) tuples for new events."""
    out: list[tuple[str, str, str]] = []
    last_event_iso = cursor.get("last_event_iso")
    last_dt = None
    if last_event_iso:
        try:
            last_dt = datetime.fromisoformat(last_event_iso.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    if not lib.EVENTS_LEDGER.exists():
        return out

    newest_iso = last_event_iso
    for evt in lib.read_jsonl(lib.EVENTS_LEDGER):
        ts = evt.get("logged_at") or evt.get("produced_at")
        if not ts:
            continue
        try:
            evt_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if last_dt and evt_dt <= last_dt:
            continue
        # Cleanly handle key events
        kind = evt.get("event", "")
        if kind == "trust-state-transition":
            out.append(("trust-state-transition",
                        f"{evt.get('from')}-{evt.get('to')}",
                        f"⚠️ *Trust transition*\n`{evt.get('from')}` → `{evt.get('to')}`\n_reason: {evt.get('reason', 'n/a')}_"))
        elif kind == "delta-regression":
            out.append(("delta-regression", evt.get("slug", ""),
                        f"🚨 *Regression detected*\n`{evt.get('slug')}` · {evt.get('agreement_state', '')}\nrecommendation: `{evt.get('recommended_action', '')}`"))
        elif kind == "delta-disputed":
            out.append(("delta-disputed", evt.get("slug", ""),
                        f"⚠️ *Delta disputed*\n`{evt.get('slug')}`"))
        elif kind == "delta-confirmed":
            # Only notify if a regression was just cleared
            if evt.get("regression_cleared"):
                out.append(("delta-confirmed-cleared", evt.get("slug", ""),
                            f"✅ *Regression cleared*\n`{evt.get('slug')}` confirmed."))
        elif kind == "concierge-action-error":
            out.append(("action-error", evt.get("action", ""),
                        f"❌ *Concierge action failed*\n`{evt.get('action')}`: {evt.get('error', '')[:400]}"))
        if not newest_iso or ts > newest_iso:
            newest_iso = ts

    if newest_iso:
        cursor["last_event_iso"] = newest_iso
    return out


def _check_dreamer_postcard(cursor: dict) -> list[tuple[str, str, str]]:
    out = []
    inbox = Path("os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/hermes/workspace/profiles/dreamer/workspace/room/inbox-from-research")
    if not inbox.exists():
        return out
    # Find dreamer postcards (these are written by dreamer's digest in postcard mode;
    # in our setup they live in dreamer's notes area or the digest produces stdout —
    # for v1 we treat the *latest retrospective* as a "postcard" candidate)
    retros = Path("os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/hermes/workspace/profiles/dreamer/workspace/room/retrospectives")
    if not retros.exists():
        return out
    files = sorted(retros.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return out
    latest = files[0]
    last_seen = cursor.get("last_postcard_walk")
    if latest.stem == last_seen:
        return out
    cursor["last_postcard_walk"] = latest.stem
    body = latest.read_text()[:1500]
    out.append(("dreamer-postcard", latest.stem,
                f"📮 *Dreamer postcard* — `{latest.stem}`\n\n{body}"))
    return out


def _check_drafts_ready(cursor: dict) -> list[tuple[str, str, str]]:
    out = []
    tracks_dir = Path("os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/content-vault/tracks")
    if not tracks_dir.exists():
        return out
    notified = set(cursor.get("notified_ready_slugs") or [])
    new_notified = set(notified)
    for sd in tracks_dir.iterdir():
        if not sd.is_dir():
            continue
        editor = sd / f"{sd.name}.editor-review.json"
        if not editor.exists():
            continue
        try:
            er = json.loads(editor.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if er.get("verdict") == "ready" and sd.name not in notified:
            new_notified.add(sd.name)
            out.append(("draft-ready", sd.name,
                        f"✏️ *Draft ready* — `{sd.name}`\n"
                        f"verdict: ready · selected: `{er.get('selected_draft_id', '?')}`\n"
                        f"_{(er.get('rationale') or '')[:600]}_"))
    cursor["notified_ready_slugs"] = sorted(new_notified)
    return out


def _check_voice_md_nag(cursor: dict) -> list[tuple[str, str, str]]:
    voice = Path("os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/content-vault/humanizer/voice.md")
    if not voice.exists():
        return [("voice-md-missing", "",
                 "🎙 *voice.md is missing.* Humanizer will be generic. Create `os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/content-vault/humanizer/voice.md` with 5+ samples.")]
    try:
        content = voice.read_text()
    except OSError:
        return []
    populated = sum(1 for l in content.splitlines()
                    if l.strip().startswith("### Sample") and "(paste here)" not in l)
    if populated >= 3:
        return []
    days_between = int(CONFIG["notifier"].get("voice_md_nag_after_days", 1))
    last = cursor.get("last_voice_nag")
    if last:
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - last_dt < timedelta(days=days_between):
                return []
        except (ValueError, TypeError):
            pass
    cursor["last_voice_nag"] = lib.now_iso()
    return [("voice-md-empty", "",
             f"🎙 *voice.md only has {populated} samples.* "
             "Humanizer will sound generic until you paste 5+ real writing samples. "
             "Edit `os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/content-vault/humanizer/voice.md`.")]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    lib.load_secrets_into_env()
    lib.ensure_dirs()

    if not _bot_token():
        print("[notifier] no bot token; skipping", file=sys.stderr)
        return 0
    if not _allowed_chat_ids():
        print("[notifier] no authorized chat_ids; skipping", file=sys.stderr)
        return 0

    cursor = _read_cursor()

    notifications: list[tuple[str, str, str]] = []
    notifications.extend(_check_events(cursor))
    notifications.extend(_check_dreamer_postcard(cursor))
    notifications.extend(_check_drafts_ready(cursor))
    notifications.extend(_check_voice_md_nag(cursor))

    sent = 0
    for kind, key, message in notifications:
        if not _rate_ok(kind, key):
            continue
        _broadcast(message)
        _rate_record(kind, key)
        sent += 1
        # Also log so events.jsonl shows what we surfaced
        lib.append_jsonl(lib.EVENTS_LEDGER, {
            "event": "concierge-notify",
            "kind": kind,
            "key": key,
            "logged_at": lib.now_iso(),
        })

    _write_cursor(cursor)
    print(json.dumps({"result": "ok", "notifications_sent": sent,
                       "candidates": len(notifications)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
