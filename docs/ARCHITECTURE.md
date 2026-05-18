# ARCHITECTURE.md — Goku System Design

> **Note**: This document is adapted from the reference Goku implementation. Paths are templatable for your infrastructure.

## Overview

**Goku** is a compounding-judgment agent system that combines strategic reasoning (Hermes brain) with tactical execution (OpenClaw hands). All state lives in a configurable data directory (e.g., `/opt/agent-data/` in the reference, `{DATA_DIR}` in your deployment).

**Core principles:**
- ✅ No agent approves its own work
- ✅ Every artifact validates before promotion
- ✅ Append-only audit trail
- ✅ Workspace isolation
- ✅ Provider agnostic

## System Architecture

```
┌──────────────────────────────── HERMES (the brain) ─────────────────────────┐
│                                                                              │
│   research-agent       Evidence collector + LLM extraction                   │
│        ↓                Output: research-input.json (findings+claims+sources)│
│   dreamer              Pattern-noticer (4 walk modes + retrospectives)       │
│        ↓                Output: idea-contract.json → state/tracks/           │
│   main                 Approval gate (risk band + decision)                  │
│        ↓                Output: main-review.json + product-plan.json         │
│   coder                Builder (file generation via LLM)                     │
│        ↓                Output: build-plan.json + verification.json          │
│   qa                   Independent verifier (re-hashes, re-runs)             │
│        ↓                Output: qa-verification.json + verification-delta    │
│   trust                Room health reporter (reads deltas, writes trust-report)│
│        ↓                Output: state/trust-report.json (clean/watch/...)    │
│   retention            Curator (keep/improve/park/prune)                     │
│                         Output: retention-review.json                        │
│                                                                              │
│   + Hermes built-in: kanban, sessions, skills, dashboard, gateway            │
└──────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ↓
┌──────────────── BUILDROOM (shared schemas + tooling + lib) ─────────────────┐
│   13 JSON schemas, validator, cockpit renderer, agent_lib (Python pkg)      │
│   + delta_consumer.py (verification-delta state machine)                    │
└──────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ↓
┌──────────────── STATE — {DATA_DIR}/state/tracks/{slug}/ ──────────────────┐
│   The contract chain artifacts. One folder per idea card.                    │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────── OPENCLAW (the hands) ───────────────────────────┐
│   main         Default agent (general-purpose)                              │
│   agents/*     Specialized agents (OSINT, delivery, research, etc.)         │
│                                                                              │
│   Gateway, Control UI w/ token auth                                          │
│   Sandboxed via Docker/Podman (configurable per-agent)                       │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Hard Rules (Enforced)

1. **No agent approves its own work** — qa always writes its own receipt
2. **Every artifact validates** before being promoted to `state/tracks/`
3. **Coder may only write** inside `allowed_paths`; protected surfaces are sacred
4. **qa re-hashes** every file and re-runs every command independently
5. **Trust is read-only** — it never modifies verification or qa files
6. **Schema validation gates** every handoff between profiles
7. **Audit ledger is append-only** — every main decision logs permanently
8. **High/critical risk** requires `force_approval` with audit entry

## Data Flow

```
Sources (RSS, GitHub, APIs)
    │
    ↓ (research-agent, e.g. 6-hourly)
{DATA_DIR}/research-vault/raw/          ← raw collector captures
    │
    ↓ (LLM finding extraction)
{DATA_DIR}/research-vault/findings.jsonl ← append-only ledger
    │
    ↓ (compose & validate)
research-vault/research-*.research-input.json
    │
    ↓ (dreamer reads)
dreamer/walks/<walk-id>.{md,json}        ← walk notes
    │
    ↓ (signal filter — deterministic)
state/tracks/<slug>/<slug>.idea-contract.json  ← promoted idea
    │
    ↓ (main review, e.g. hourly)
state/tracks/<slug>/<slug>.main-review.json
state/tracks/<slug>/<slug>.product-plan.json
state/approval-ledger.jsonl              ← approval decision logged
    │
    ↓ (coder builds)
state/tracks/<slug>/work/                ← isolated workspace
state/tracks/<slug>/<slug>.verification.json
    │
    ↓ (qa independently verifies)
state/tracks/<slug>/<slug>.qa-verification.json
state/tracks/<slug>/<slug>.verification-delta.json
    │
    ↓ (trust sweep)
state/trust-report.json                  ← anomalies flagged
```

## Filesystem Layout

```
{DATA_DIR}/                              # owned by agents user
├── secrets.env                          # 0600 — API keys (NEVER commit)
│
├── hermes/                              # Hermes runtime
│   ├── config.yaml                      # Hermes configuration
│   ├── kanban.db                        # SQLite-backed task board
│   ├── workspace/profiles/              # actual profile directories
│   │   ├── research/
│   │   │   ├── SOUL.md                  # identity + constraints
│   │   │   ├── config.yaml              # model routing, schedule
│   │   │   ├── scripts/
│   │   │   │   ├── main.py              # mode-driven entry point
│   │   │   │   ├── check_providers.py   # dependency check
│   │   │   │   └── lib/__init__.py      # lib re-exports
│   │   │   ├── skills/
│   │   │   └── workspace/               # agent-owned writable area
│   │   ├── dreamer/, main/, coder/, qa/, retention/, trust/
│   │   └── content/                     # user-provided profiles
│   └── profiles/                        # ← symlinks for Hermes discovery
│       ├── research → ../workspace/profiles/research
│       ├── dreamer → ../workspace/profiles/dreamer
│       └── (etc.)
│
├── openclaw/                            # OpenClaw runtime
│   ├── openclaw.json                    # OpenClaw config
│   ├── agents/                          # per-agent workspace dirs
│   └── logs/
│
├── buildroom/                           # shared schemas + lib
│   ├── agent_lib/                       # Python package
│   │   ├── validation.py                # schema validator
│   │   ├── llm.py                       # multi-provider LLM router
│   │   ├── filesystem.py                # state management
│   │   └── ledger.py                    # audit helpers
│   ├── schemas/                         # 13 JSON schemas
│   ├── scripts/
│   │   ├── validate.py                  # CLI validator
│   │   ├── apply_secrets.py             # secret manager
│   │   └── render_cockpit.py            # dashboard generator
│   └── examples/
│
└── state/                               # cross-profile shared state
    ├── events.jsonl                     # event log
    ├── approval-ledger.jsonl            # audit trail
    ├── tracks/
    │   ├── <slug>/
    │   │   ├── <slug>.idea-contract.json
    │   │   ├── <slug>.main-review.json
    │   │   ├── <slug>.product-plan.json
    │   │   ├── <slug>.build-plan.json
    │   │   ├── <slug>.verification.json
    │   │   ├── <slug>.qa-verification.json
    │   │   ├── <slug>.verification-delta.json
    │   │   ├── <slug>.retention-review.json
    │   │   └── work/                    # coder's isolated workspace
    │   └── (other slug dirs)
    ├── trust-report.json                # latest trust state
    ├── operator-summary.json            # cockpit data
    └── operator-cockpit.html            # rendered dashboard
```

## Profiles Explained

### research-agent
**Purpose**: Collect and extract evidence from external sources  
**Inputs**: RSS feeds, GitHub releases, APIs  
**Outputs**: `research-input.json` (findings, claims, sources)  
**Schedule**: Typically 6-hourly, customizable  
**Key files**: `scripts/research_agent_refresh.py`

### dreamer
**Purpose**: Pattern-noticer that generates ideas from research  
**Inputs**: `research-input.json`  
**Outputs**: `idea-contract.json` (promoted ideas)  
**Modes**: drift (from research), continue (existing), tangent (curiosity), tend (maintenance)  
**Key files**: `scripts/walk.py`, `scripts/signal_filter.py`, `scripts/promote.py`

### main
**Purpose**: Approval gate with risk-scoring  
**Inputs**: `idea-contract.json`  
**Outputs**: `main-review.json`, `product-plan.json`  
**Decision**: approved / deferred / rejected (with reasoning)  
**Key files**: `scripts/process_review.py`

### coder
**Purpose**: Builder (generates files via LLM)  
**Inputs**: `product-plan.json`  
**Outputs**: `build-plan.json`, `verification.json` (hashes, commands)  
**Workspace**: `state/tracks/<slug>/work/` (isolated)  
**Key files**: `scripts/build.py`

### qa
**Purpose**: Independent verifier (re-hashes, re-runs)  
**Inputs**: `verification.json` (coder's receipts)  
**Outputs**: `qa-verification.json`, `verification-delta.json`  
**Rule**: Never trusts coder's receipts — always re-verifies  
**Key files**: `scripts/verify.py`

### trust
**Purpose**: Health reporter (reads deltas, flags anomalies)  
**Inputs**: `verification-delta.json`, all artifacts  
**Outputs**: `trust-report.json` (clean / watch / investigate)  
**Schedule**: 4× daily (e.g., 02:45, 08:45, 14:45, 20:45)  
**Key files**: `scripts/sweep.py`

### retention
**Purpose**: Curator (age-based recommendations)  
**Inputs**: `state/tracks/*/`  
**Outputs**: `retention-review.json` (keep / improve / park / prune)  
**Schedule**: Daily (e.g., 03:00)  
**Rule**: Prune always requires operator confirmation  
**Key files**: `scripts/sweep.py`

## Key Patterns

### 1. Mode-Driven Entry Point
Every profile's `main.py` is mode-driven:
```python
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=MODES)
    args = ap.parse_args()
    
    handlers = {
        "research": lambda: mode_research(),
        "extract": lambda: mode_extract(),
        # ...
    }
    receipt = handlers[args.mode]()
    print(json.dumps(receipt))
```

### 2. agent_lib as Shared Package
All profiles use a shared Python package (`buildroom/agent_lib/`). Each profile's `scripts/lib/__init__.py` re-exports it plus profile-specific paths:
```python
from agent_lib import (
    validate, validate_or_raise,
    call_model, is_provider_configured,
    load_profile_config, load_secrets_into_env,
    STATE_DIR, TRACKS_DIR, artifact_path, ...
)
```

### 3. Schema Validation as Hard Gate
Before any artifact is written to `state/tracks/`:
```python
errs = lib.validate(artifact, "product-plan")
if errs:
    return {"result": "fail", "errors": errs[:3]}
lib.write_json_atomic(path, artifact)  # only if valid
```

### 4. Audit Ledger (Append-Only)
Every main decision appends to `state/approval-ledger.jsonl`:
```json
{"event":"main-review","slug":"foo","decision":"approved","risk_band":"low","logged_at":"2026-05-18T..."}
```

### 5. Workspace Isolation
Coder writes only within `state/tracks/<slug>/work/`:
```python
work = tracks_dir / slug / "work"
declared = work / declared_path_str.lstrip("/")
resolved = declared.resolve()
assert str(resolved).startswith(str(work.resolve()))  # path traversal check
```

## LLM Routing

Model IDs are provider-qualified: `{provider}/{model_name}`

| Provider | ID Format | Base URL |
|---|---|---|
| NVIDIA | `nvidia/meta/llama-3.1-8b-instruct` | `https://integrate.api.nvidia.com/v1` |
| OpenCode Zen | `opencode-zen/big-pickle` | `https://opencode.ai/zen/v1` |
| OpenCode Go | `opencode-go/qwen3.6-plus` | `https://opencode.ai/zen/go/v1` |
| OpenRouter | `openrouter/meta-llama/llama-2-70b-chat` | `https://openrouter.ai/api/v1` |

Free options always available. Swap with one `secrets.env` edit — no code changes.

## Systemd Integration

Profiles run via systemd timers (not cron):
- Better logging (journald)
- Easy enable/disable per timer
- `Persistent=true` recovers missed runs
- `RandomizedDelaySec` prevents thundering herd

Example:
```ini
[Unit]
Description=Goku research-agent refresh
After=network-online.target

[Timer]
OnBootSec=5min
OnUnitActiveSec=6h
RandomizedDelaySec=2min
Persistent=true

[Install]
WantedBy=timers.target
```

## Deployment Considerations

### Network
- SSH: Tailscale-only (or VPN)
- Dashboards: Behind Tailscale ACLs
- APIs: Use only environment variables for keys
- HTTPS: Recommended for production

### Scaling
- **Single machine**: Hermes + OpenClaw on same box, state on local disk
- **Multi-machine**: Shared NFS/SFTP for `{DATA_DIR}`, agents on different boxes
- **Cloud**: Deploy on VPS (Linode, Hetzner, Hostinger, AWS)

### Monitoring
- Monitor `state/approval-ledger.jsonl` for decisions
- Monitor `state/trust-report.json` for anomalies
- Logs via `journalctl` (systemd)
- Health check: `{DATA_DIR}/state/operator-summary.json` (updated every 5 min)

## Extension Points

1. **Add a new profile**: Copy template, fill SOUL.md + config.yaml + scripts/main.py
2. **Add a new OpenClaw agent**: Copy template, bind to messaging channel
3. **Add a new schema**: Define JSON schema in `schemas/`, register in validator
4. **Add a new LLM provider**: Edit `agent_lib/llm.py` (10 lines), add env var
5. **Add a new data source** (research): Add collector in `scripts/collectors/`

## See Also

- [OPERATIONS.md](./OPERATIONS.md) — Day-to-day troubleshooting
- [ONBOARDING.md](./ONBOARDING.md) — Adding agents
- [SETUP.md](./SETUP.md) — Fresh installation
- [CONCEPTS.md](./CONCEPTS.md) — Terminology

---

*Last updated: 2026-05 (reference: Goku v1, production-proven)*
