#!/usr/bin/env python3
"""
concierge.py — chief-of-staff reasoning loop.

Public entry point used by the Telegram listener:
    handle(message_text, chat_id) -> str
    The returned string is the concierge's reply (markdown-safe for Telegram).

Strategy:
- Single LLM round trip per turn for low latency.
- Gather a structured "room snapshot" (trust + kanban + content + dreamer +
  events tail) into the system prompt every turn.
- Concierge LLM emits JSON: {action: <name|null>, args: {}, reply: "..."}
- If action is set, we execute it via router_actions, capture the receipt,
  and the reply already contains the operator-facing summary.
- For multi-step intents (e.g. seed + draft + humanize + editor) the LLM
  picks one action per turn — the user sees progress and can intervene.

Hard rules from SOUL.md are enforced in code where possible:
- Forbidden actions raise BEFORE the LLM is called.
- Every operator command + every action receipt logs to events.jsonl.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402
import router_actions  # noqa: E402

CONFIG = lib.load_profile_config(lib.PROFILE_ROOT)
SOUL_PATH = lib.PROFILE_ROOT / "SOUL.md"


# ---------------------------------------------------------------------------
# Context gathering — read the room every turn
# ---------------------------------------------------------------------------

def _gather_room_snapshot() -> dict:
    return {
        "trust":           router_actions.read_trust_state(),
        "kanban":          router_actions.read_kanban(),
        "events_tail":     router_actions.read_events_tail(n=12),
        "content_tracks":  router_actions.read_content_tracks(),
        "content_vault":   router_actions.read_content_vault_status(),
        "voice":           router_actions.read_voice_status(),
        "agents":          router_actions.read_agent_runtime_status(),
        "research":        router_actions.read_research_summary(),
        "dreamer":         router_actions.read_dreamer_room(),
        "regressions":     router_actions.read_active_regressions(),
        "qa_rerun_queue":  router_actions.read_qa_rerun_queue(),
    }


def _load_recent_history(chat_id: str | int, n: int = 8) -> list[dict]:
    if not lib.CHAT_HISTORY_JSONL.exists():
        return []
    out = []
    for rec in lib.read_jsonl(lib.CHAT_HISTORY_JSONL):
        if str(rec.get("chat_id")) == str(chat_id):
            out.append(rec)
    return out[-n:]


def _append_history(chat_id: str | int, role: str, text: str,
                     action: dict | None = None) -> None:
    lib.append_jsonl(lib.CHAT_HISTORY_JSONL, {
        "chat_id": str(chat_id),
        "role": role,
        "text": text,
        "action": action,
        "logged_at": lib.now_iso(),
    })


# ---------------------------------------------------------------------------
# Action registry — what the LLM is allowed to call
# ---------------------------------------------------------------------------

ACTION_DESCRIPTIONS = {
    # READ — always safe, no confirmation needed
    "read_trust_state":          "Current trust state + recent concerns + recommendations.",
    "read_kanban":               "Lane-by-lane track view (watching/ready/queued/active/built/ghost/broken).",
    "read_events_tail":          "Recent events.jsonl entries. Args: {n: int}",
    "read_content_tracks":       "All content-vault tracks and their statuses.",
    "read_content_vault_status": "Per-platform vault freshness + playbook health.",
    "read_voice_status":         "Whether voice.md has real samples (humanizer health).",
    "read_agent_runtime_status": "Per-profile last activity + soul presence.",
    "read_research_summary":     "Latest research-input + ledger sizes (findings/claims/sources).",
    "read_dreamer_room":         "Walks count, retrospectives, fascinations, lessons, lanes.",
    "read_active_regressions":   "Tracks currently in regression/disputed state.",
    "read_qa_rerun_queue":       "Tracks queued for QA re-run.",
    # WRITE — always emits an event; require operator intent
    "seed_content_track":        "Create a content track. Args: {topic: str, intent?: str, platforms?: [str], slug?: str}",
    "draft_content":             "Draft platform variants for a track. Args: {slug: str, platform?: str}",
    "humanize_content":          "Humanize drafts in a track. Args: {slug: str, platform?: str}",
    "editor_review_content":     "Editor scores + picks a winning variant. Args: {slug: str}",
    "capture_post_receipt":      "Record that a track was posted. Args: {slug: str, platform: str, post_url: str, post_id?: str, account_handle?: str}",
    "promote_idea":              "Force-promote an idea slug from dreamer's board. Args: {slug: str}",
    "create_kanban_task":        "Drop a task in Hermes kanban. Args: {profile: str, title: str, body?: str}",
    "request_trust_sweep":       "Run trust sweep now (out-of-cycle). Args: {}",
    "request_research_refresh":  "Run research refresh now (slow — may take 1-2 min). Args: {}",
}


def _format_action_help() -> str:
    lines = []
    for name, desc in ACTION_DESCRIPTIONS.items():
        lines.append(f"  - {name}: {desc}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM round trip
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TMPL = """{soul}

---
## CURRENT ROOM SNAPSHOT (refreshed every turn)

```json
{snapshot}
```

---
## YOUR INTERFACE

You receive a single Telegram message from the operator. You return a
SINGLE JSON object:

{{
  "action": "<one of the action names below, or null if pure-read reply is enough>",
  "args": {{ ... }},   // arguments for the action (omit if action is null)
  "reply": "<your operator-facing reply, telegram-safe markdown, max ~3500 chars>"
}}

If the room snapshot above already contains everything needed to answer
the question, set `action: null` and just write `reply`.

If the operator wants you to DO something, set `action` to the right name
and `args` to the right shape — your reply should describe what you're
about to do (or did) in executive prose. Do NOT invent receipts; the
runtime will execute the action and that result becomes the system's
truth. You only get one action per turn — pick the most important one.

### Available actions

{actions}

---
## CHAT HISTORY (most recent last)

{history}

---
## STYLE RULES (from SOUL.md, summarized)

- Direct. Terse. Executive. No "Sure!" / "Of course!" / "Happy to help!"
- Don't apologize for the system's state. Report it.
- Don't ask permission for read operations. Read freely.
- For writes, you can either (a) do it now and report, or (b) confirm
  briefly first if it's destructive (post receipts, kanban tasks, etc.).
- If the operator's intent is ambiguous, ask one sharp clarifying question.
  Don't ramble.
- Telegram-safe markdown: prefer plain text + line breaks. Use `**bold**`
  sparingly. Avoid tables.

OUTPUT JSON ONLY. No prose outside the JSON. No code fences."""


def _build_system_prompt(snapshot: dict, history: list[dict]) -> str:
    soul = SOUL_PATH.read_text() if SOUL_PATH.exists() else "You are the concierge."
    snap_json = json.dumps(snapshot, indent=2)[: int(CONFIG["runtime"].get("context_max_chars", 12000))]
    hist_lines = []
    for rec in history:
        role = rec.get("role", "?")
        txt = (rec.get("text") or "")[:600]
        hist_lines.append(f"[{role}] {txt}")
    hist_blob = "\n".join(hist_lines) if hist_lines else "(no prior turns in this chat)"
    return SYSTEM_PROMPT_TMPL.format(
        soul=soul,
        snapshot=snap_json,
        actions=_format_action_help(),
        history=hist_blob[:4000],
    )


def _ask_llm(system_prompt: str, user_message: str, model: str) -> dict:
    try:
        resp = lib.call_model(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.25,
            max_tokens=2000,
            json_mode=True,
            timeout=int(CONFIG["runtime"].get("request_timeout_seconds", 90)),
        )
        return json.loads(resp)
    except (lib.LLMError, json.JSONDecodeError) as e:
        return {"action": None, "args": {},
                "reply": f"_(concierge had a transport hiccup: {str(e)[:200]}. Try again.)_"}


# ---------------------------------------------------------------------------
# handle() — the public entry point
# ---------------------------------------------------------------------------

def handle(message_text: str, chat_id: str | int) -> str:
    """Process a single operator message; return a Telegram-ready reply."""
    lib.ensure_dirs()
    if not message_text or not message_text.strip():
        return "_(empty message)_"

    msg = message_text.strip()

    # Built-in slash commands — instant, no LLM
    if msg.startswith("/start") or msg.lower() in ("/help", "help"):
        return _builtin_help()
    if msg.lower() == "/whoami":
        return f"chat_id: `{chat_id}`\nstatus: authorized"
    if msg.lower() == "/state":
        return _quick_state_summary()

    model = CONFIG["models"].get("reasoning") or CONFIG["models"]["default"]
    if not lib.is_provider_configured(model):
        return f"_(concierge cannot reason: provider not configured for `{model}`)_"

    snapshot = _gather_room_snapshot()
    history = _load_recent_history(chat_id, n=int(CONFIG["runtime"].get("history_max_turns", 8)))
    sys_prompt = _build_system_prompt(snapshot, history)

    # Log the inbound message
    _append_history(chat_id, "operator", msg)
    lib.append_jsonl(lib.EVENTS_LEDGER, {
        "event": "concierge-operator-msg",
        "chat_id": str(chat_id),
        "text": msg[:1000],
        "logged_at": lib.now_iso(),
    })

    # Ask the LLM
    decision = _ask_llm(sys_prompt, msg, model)
    action = decision.get("action")
    args = decision.get("args") or {}
    reply = (decision.get("reply") or "").strip()

    # Execute the action if any
    receipt = None
    if action and action in router_actions.ACTIONS:
        receipt = router_actions.execute(action, args)
        # If write fails, append a small note so the operator sees it
        if router_actions.ACTIONS[action]["kind"] == "write":
            if receipt.get("result") != "ok":
                reply = (reply + f"\n\n_action `{action}` failed: {receipt.get('reason', '?')}_").strip()
            else:
                reply = (reply + f"\n\n_action `{action}` ok_").strip()

    # Log assistant reply + action
    _append_history(chat_id, "concierge", reply, action={
        "name": action, "args": args, "receipt": receipt,
    } if action else None)
    lib.append_jsonl(lib.EVENTS_LEDGER, {
        "event": "concierge-reply",
        "chat_id": str(chat_id),
        "action": action,
        "result": (receipt or {}).get("result") if receipt else None,
        "logged_at": lib.now_iso(),
    })

    # Truncate to telegram limits
    cap = int(CONFIG["telegram"].get("max_message_length", 4000))
    if len(reply) > cap:
        reply = reply[: cap - 30] + "\n\n_(truncated)_"
    return reply or "_(no reply)_"


# ---------------------------------------------------------------------------
# Built-in helpers
# ---------------------------------------------------------------------------

def _builtin_help() -> str:
    return (
        "I am Concierge. I run Goku's agency from Telegram.\n\n"
        "Ask me anything about state. Examples:\n"
        "  • trust?\n"
        "  • what's in the kanban\n"
        "  • show recent events\n"
        "  • what content tracks are pending\n"
        "  • is voice.md populated\n\n"
        "Tell me what to do. Examples:\n"
        "  • seed a medium post on \"why specialization beats consolidation\"\n"
        "  • draft slug X\n"
        "  • run trust sweep\n"
        "  • promote slug X\n\n"
        "Slash commands:\n"
        "  /state    — quick room summary\n"
        "  /whoami   — your authorized chat_id\n"
        "  /help     — this message"
    )


def _quick_state_summary() -> str:
    s = _gather_room_snapshot()
    trust = s["trust"]
    kanban = s["kanban"]
    voice = s["voice"]
    content = s["content_tracks"]
    research = s["research"]
    parts = []
    if trust.get("available"):
        parts.append(f"**Trust:** `{trust.get('trust_state', '?')}`")
    else:
        parts.append("**Trust:** _no report yet_")
    lanes_summary = " · ".join(
        f"{k}:{len(v)}" for k, v in kanban.get("lanes", {}).items() if v
    )
    parts.append(f"**Kanban:** {lanes_summary or 'all empty'}")
    if research.get("available"):
        led = research.get("ledgers", {})
        parts.append(
            f"**Research:** findings={led.get('findings', 0)} · "
            f"claims={led.get('claims', 0)} · sources={led.get('sources', 0)}"
        )
    parts.append(
        f"**Content:** {content.get('total', 0)} tracks · voice.md "
        + _voice_status_str(voice)
    )
    return "\n".join(parts)


def _voice_status_str(voice: dict) -> str:
    if voice.get("ready"):
        return "ready"
    if not voice.get("present"):
        return "EMPTY"
    return f"samples={voice.get('samples_populated', 0)}"


# CLI entry for ad-hoc testing
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: concierge.py <message>")
        sys.exit(2)
    chat_id = "cli-test"
    print(handle(" ".join(sys.argv[1:]), chat_id))
