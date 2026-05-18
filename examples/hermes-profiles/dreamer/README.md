# Dreamer profile

The houseguest. See `SOUL.md`.

## Layout

```
SOUL.md                       — identity and boundaries
config.yaml                   — model routing, thresholds, sprint lock
Justfile                      — bootstrap / walk-* / filter / promote / postcard / status
scripts/
  walk.py                     — go on a walk in one of 4 modes (real LLM call)
  signal_filter.py            — deterministic event extraction + scoring (no LLM)
  promote.py                  — shape an idea-contract, validate, write to tracks/
  digest.py                   — operator-facing postcard
  check_providers.py
  lib/
    vault_paths.py            — room layout
    __init__.py               — thin re-export of agent_lib + paths
skills/
  dreamer-loop/SKILL.md       — Hermes-compatible skill description
workspace/room/
  walks/                      — walk notes (.md + .json)
  projects/                   — per-project state (markdown)
  notes/                      — free-form notes
  feedback/                   — retrospectives
  inbox-from-research/        — research-input drops from research-agent
  signal-log/                 — per-walk signal events
  signal-state/
    signal-board.md           — human board
    summary.json              — machine board
    sprint.lock               — present iff a promotion is in flight
  fascinations.md             — long-running interests
  lessons.md                  — accumulated lessons after promotions

# Cross-profile shared state
/opt/agent-data/state/tracks/<slug>/<slug>.idea-contract.json
```

## Pipeline

```
walk → walk note (md+json)
     → signal_filter → board update (signal-board.md, summary.json)
     → if any "ready" card AND sprint lock free
       → promote → idea-contract.json in /opt/agent-data/state/tracks/<slug>/
       → main reviews, if approved coder builds
```

## Quick start

```bash
just bootstrap        # creates room dirs + fascinations.md + lessons.md
just walk-drift       # first walk, drifts from latest research-input
just walk-tangent     # totally free walk
just filter           # explicit signal filter run (also runs after each walk)
just postcard         # see the operator-facing summary
just status           # current state of the room
just promote          # promote top ready card (writes idea-contract)
just promote --dry-run
just promote --slug my-idea
```

## Sprint lock

Only one card in `active` at a time. The lock file at `signal-state/sprint.lock` is created
on promote and must be released by main / coder pipeline (or `just promote --release-lock`)
when the contract chain finishes that card.

## Card states & lanes

The signal filter computes:
- **ready** — score ≥ 6, ≥ 3 walks, ≥ 2 signal types
- **experiment** — score ≥ 3, ≥ 2 walks (smaller scope, file-oriented)
- **watching** — anything below thresholds
- **ghost** — net negative score (cooling > excitement)
