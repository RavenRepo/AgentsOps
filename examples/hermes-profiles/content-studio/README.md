# content-studio

Drafts platform-native content, applies the humanizer, and editor-reviews the slate.
See [`SOUL.md`](./SOUL.md), [`Justfile`](./Justfile).

## Workflow

```bash
# 1. Seed a track
sudo -u agents just seed "Why agents need a research department" \
    --intent "drive readers to the goku setup" \
    --platforms medium,x,linkedin

# 2. Draft for all (or one) platforms
sudo -u agents just draft why-agents-need-a-research-department

# 3. Humanize against voice.md
sudo -u agents just humanize why-agents-need-a-research-department

# 4. Editor reviews all variants
sudo -u agents just editor-review why-agents-need-a-research-department

# Then operator approves and content-poster (OpenClaw) posts
```

## Hard rules

- humanize must run before editor-review (only humanized drafts can win)
- Every draft cites `applied_tactics`
- voice.md drives the humanizer; without populated samples the agent skips humanizing
  and notes it honestly in the meta
