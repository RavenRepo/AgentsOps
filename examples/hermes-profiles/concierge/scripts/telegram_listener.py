#!/usr/bin/env python3
"""
telegram_listener.py — long-poll Telegram bot, dispatch to concierge.

Runs as a long-lived systemd service (Restart=always).

Auth model:
- TELEGRAM_BOT_TOKEN_CONCIERGE must be set.
- TELEGRAM_ALLOWED_CHAT_IDS is a comma-separated list of chat_ids.
- If empty, the listener enters LOCKDOWN: every incoming message gets a
  reply with the chat_id and instructions, and is logged. The operator
  edits secrets.env to add the chat_id, then the listener picks up the
  new env on next iteration (we re-read every loop).

Reliability:
- Long-poll timeout 25s (Telegram caps at 60).
- Retries on network errors with backoff.
- Persist Telegram update offset to disk so restarts don't replay messages.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402
import concierge  # noqa: E402

CONFIG = lib.load_profile_config(lib.PROFILE_ROOT)


def _read_env(name: str) -> str:
    """Read env var (respects operator's just-edited secrets.env on each loop)."""
    return (os.environ.get(name) or "").strip()


def _allowed_chat_ids() -> set[str]:
    raw = _read_env(CONFIG["telegram"].get("allowed_chat_ids_env",
                                            "TELEGRAM_ALLOWED_CHAT_IDS"))
    if not raw:
        return set()
    return {s.strip() for s in raw.split(",") if s.strip()}


def _bot_token() -> str:
    return _read_env(CONFIG["telegram"].get("bot_token_env",
                                             "TELEGRAM_BOT_TOKEN_CONCIERGE"))


def _telegram_get(method: str, params: dict, timeout: int = 35) -> dict:
    token = _bot_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN_CONCIERGE not set")
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def _telegram_post(method: str, payload: dict, timeout: int = 30) -> dict:
    token = _bot_token()
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_message(chat_id: str | int, text: str, parse_mode: str = "Markdown") -> None:
    cap = int(CONFIG["telegram"].get("max_message_length", 4000))
    if len(text) > cap:
        text = text[: cap - 30] + "\n\n_(truncated)_"
    try:
        _telegram_post("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        })
    except urllib.error.HTTPError as e:
        # Markdown parse errors → retry as plain text
        if e.code == 400:
            try:
                _telegram_post("sendMessage", {
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                })
                return
            except Exception as e2:
                print(f"[telegram] sendMessage plain retry failed: {e2}", file=sys.stderr)
        raise


# ---------------------------------------------------------------------------
# Offset persistence — never replay processed updates
# ---------------------------------------------------------------------------

def _read_offset() -> int:
    f = lib.TELEGRAM_OFFSET_FILE
    if not f.exists():
        return 0
    try:
        return int(f.read_text().strip() or "0")
    except (OSError, ValueError):
        return 0


def _write_offset(off: int) -> None:
    lib.ensure_dirs()
    lib.write_atomic(lib.TELEGRAM_OFFSET_FILE, str(off))


# ---------------------------------------------------------------------------
# Dispatch one update
# ---------------------------------------------------------------------------

def _process_update(update: dict) -> None:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    text = msg.get("text") or ""
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    chat_id_str = str(chat_id)

    allowed = _allowed_chat_ids()
    if not allowed:
        # LOCKDOWN: discovery mode — tell the user how to authorize.
        send_message(chat_id, (
            "🔒 *Concierge is locked down.*\n\n"
            f"Your chat_id is: `{chat_id_str}`\n\n"
            "An operator must add this to `TELEGRAM_ALLOWED_CHAT_IDS` "
            "in `os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/secrets.env` on the VPS. After that, I'll respond.\n\n"
            "From the VPS:\n"
            "```\n"
            "sudo sed -i 's/^TELEGRAM_ALLOWED_CHAT_IDS=.*/"
            f"TELEGRAM_ALLOWED_CHAT_IDS={chat_id_str}/' os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/secrets.env\n"
            "```"
        ))
        # Log so the VPS journal also has the chat_id
        lib.append_jsonl(lib.EVENTS_LEDGER, {
            "event": "concierge-lockdown-ping",
            "chat_id": chat_id_str,
            "text": text[:300],
            "logged_at": lib.now_iso(),
        })
        return

    if chat_id_str not in allowed:
        send_message(chat_id, "🚫 _Unauthorized chat_id._")
        lib.append_jsonl(lib.EVENTS_LEDGER, {
            "event": "concierge-unauthorized",
            "chat_id": chat_id_str,
            "logged_at": lib.now_iso(),
        })
        return

    # Authorized — dispatch
    try:
        reply = concierge.handle(text, chat_id_str)
    except Exception as e:
        reply = f"_(concierge crashed: {str(e)[:300]})_"
        lib.append_jsonl(lib.EVENTS_LEDGER, {
            "event": "concierge-crash",
            "chat_id": chat_id_str,
            "error": str(e)[:1000],
            "logged_at": lib.now_iso(),
        })
    send_message(chat_id, reply)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> int:
    # Load secrets into env so token is visible
    lib.load_secrets_into_env()
    if not _bot_token():
        print("[listener] TELEGRAM_BOT_TOKEN_CONCIERGE not set; refusing to start", file=sys.stderr)
        return 1

    lib.ensure_dirs()
    offset = _read_offset()
    poll_timeout = int(CONFIG["telegram"].get("long_poll_timeout_seconds", 25))
    print(f"[listener] starting · offset={offset} · poll_timeout={poll_timeout}s · allowed={list(_allowed_chat_ids())}")

    backoff = 1
    while True:
        try:
            # Re-load env each loop so operator can add chat_id without restart
            lib.load_secrets_into_env()
            params = {"timeout": poll_timeout}
            if offset:
                params["offset"] = offset + 1
            data = _telegram_get("getUpdates", params, timeout=poll_timeout + 5)
            if not data.get("ok"):
                print(f"[listener] getUpdates not ok: {data}", file=sys.stderr)
                time.sleep(min(backoff, 30))
                backoff = min(backoff * 2, 30)
                continue
            backoff = 1
            updates = data.get("result") or []
            for u in updates:
                uid = u.get("update_id", 0)
                try:
                    _process_update(u)
                except Exception as e:
                    print(f"[listener] process error: {e}", file=sys.stderr)
                if uid > offset:
                    offset = uid
                    _write_offset(offset)
        except urllib.error.URLError as e:
            print(f"[listener] network error: {e}; sleeping {backoff}s", file=sys.stderr)
            time.sleep(min(backoff, 30))
            backoff = min(backoff * 2, 30)
        except KeyboardInterrupt:
            print("[listener] keyboard interrupt; exit")
            return 0
        except Exception as e:
            print(f"[listener] loop crash: {e}; sleeping {backoff}s", file=sys.stderr)
            time.sleep(min(backoff, 30))
            backoff = min(backoff * 2, 30)


if __name__ == "__main__":
    sys.exit(main())
