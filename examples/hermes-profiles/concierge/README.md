# concierge

Chief-of-staff agent. Owns the operator interface from inside Telegram.
Reads state across all 9 other profiles + content-vault. Dispatches actions
through the existing chain (no shortcuts, no schema bypasses).

See [`SOUL.md`](./SOUL.md) for identity and hard rules.
See [`Justfile`](./Justfile) for entry points.

## How the operator interacts

Open Telegram, message the concierge bot:

```
trust?
what's pending in kanban
draft a medium post on "why specialization beats consolidation"
promote slug some-cool-idea
```

Concierge reads the room every turn, picks at most one action, replies
in executive prose.

## Three slices, all shipped

| Slice | What | Status |
|---|---|---|
| 1 | Read-only Q&A on Telegram | live (`hermes-concierge-listener.service`) |
| 2 | Action layer — seed/draft/humanize/editor-review/promote/post-receipt/etc. | live (same service) |
| 3 | Proactive push notifications (5-min timer) | live (`hermes-concierge-notifier.service/timer`) |

## Files

```
scripts/
├── concierge.py            — main reasoning loop (LLM round-trip per turn)
├── router_actions.py       — read + write primitives, action registry
├── telegram_listener.py    — long-poll + auth gate + dispatcher
├── notifier.py             — Slice 3 push notifier
└── lib/__init__.py         — paths + agent_lib re-exports
```

## State

All concierge state lives at `/opt/agent-data/state/concierge/`:

- `chat-history.jsonl`        — every operator message + concierge reply
- `.telegram-offset`          — Telegram update offset (replay protection)
- `.notifier-cursor.json`     — what notifier has already surfaced
- `.notifier-rate-limit.json` — same-kind event suppression window

## Authorization

The bot starts in **lockdown mode** — it answers messages with the chat_id
+ instructions to add it to `TELEGRAM_ALLOWED_CHAT_IDS` in `secrets.env`.

Once the operator adds the chat_id, the listener picks up the new env on its
next loop (it re-reads secrets each iteration).
