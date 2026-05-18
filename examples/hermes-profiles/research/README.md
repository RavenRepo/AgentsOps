# Research agent profile

The evidence operator. See `SOUL.md` for identity and rules.

## Layout

```
SOUL.md                       — identity, boundaries, what this profile cannot do
config.yaml                   — model routing, schedule, source plan ref, validation flags
Justfile                      — common operations (bootstrap / refresh / digest / status)
README.md                     — you are here
scripts/
  research_agent_refresh.py   — main entry point, mode-driven
  print_research_digest.py    — render operator/subc/brief tier output
  lib/
    __init__.py
    vault_paths.py            — filesystem layout (single source of truth)
    schema_check.py           — buildroom JSON schema validation
    llm.py                    — OpenAI-compatible client (openrouter/opencode-zen/nvidia)
    config.py                 — config.yaml loader with ${VAR} expansion
skills/
  research-agent-loop/
    SKILL.md                  — Hermes-compatible skill description (8 modes)
workspace/
  research-vault/             — the data layer (created on bootstrap)
    context/                  — interest-profile.json, source-plan.md
    dossiers/                 — per-topic Markdown
    knowledge/                — claims.jsonl, findings.jsonl, sources.jsonl
    queue/                    — verification-leads, source-suggestions, handoffs
    notes/                    — operator-brief.md, daily-summary.md
    raw/<run-id>/             — raw captures
    wiki/                     — Obsidian-compatible wiki layer
    runs/<timestamp>.json     — run receipts
    health/                   — latest-health-check.json
    ops/                      — operator-cockpit.html, source-balance.md
    *.research-input.json     — buildroom artifacts (validated)
```

## Quick start

From this directory on the VPS:

```bash
just deps         # one-time: install openai + pyyaml in buildroom venv
just bootstrap    # creates stub interest-profile and source-plan
# (fill in keys at /opt/agent-data/secrets.env, run apply-secrets)
just refresh      # main loop (skeleton until Phase 8b lands collectors)
just status       # show latest run + ledger sizes
just validate     # validate research-input artifacts against buildroom schema
```

## Phases

- **8a** (current): scaffolding — SOUL, config, schema-aware Python lib, mode-driven entry point, vault structure, validation hooks.
- **8b** (next): collectors — X account scraper, GitHub watcher, RSS, Substack/Medium fetchers. Real LLM-backed finding extraction + claim synthesis.
- **8c**: bootstrap with real interest profile + first refresh end-to-end against API keys; verify research-input.json validates and gets picked up by dreamer's inbox.
- **8d**: cron schedule via systemd timers (refresh every 6h, digest 3x/day, subc-brief daily, midday-focus 1x/day, backup 1x/day).

## Cron note (Phase 8d)

The schedule lives in `config.yaml` under `schedule:` for documentation, but actual scheduling
will be implemented as systemd timers under `/etc/systemd/system/hermes-research-*.{service,timer}`.
We use systemd timers (not cron) for proper logging via journald, easy enable/disable, and resource limits.
