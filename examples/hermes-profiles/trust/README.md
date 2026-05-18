# trust

Read-only room-health reporter. Sweeps recent contract-chain tracks and
writes `state/trust-report.json` + `state/trust-report.md`.

Identity: see [`SOUL.md`](./SOUL.md).
Operations: see [`Justfile`](./Justfile).

## Quick reference

```bash
sudo -u agents just sweep            # produce a fresh report
sudo -u agents just sweep-dry        # see what it would produce, no writes
sudo -u agents just status           # show latest trust state
sudo -u agents just events           # tail recent state transitions
```

## Outputs

- `state/trust-report.json` — canonical, schema-validated against `trust-report.schema.json`
- `state/trust-report.md` — human-readable
- `state/trust-history/<report_id>.json` — append-only archive
- `state/events.jsonl` — appended on every state transition

## Hard rules

See `SOUL.md`. Summary: never modifies any verification/qa/delta/main-review/track artifact. Read-only.
