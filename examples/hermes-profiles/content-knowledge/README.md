# content-knowledge

Maintains per-platform vaults + playbooks. The studio reads the playbook
when it drafts. See [`SOUL.md`](./SOUL.md) for identity, [`Justfile`](./Justfile)
for entry points.

```bash
sudo -u agents just refresh-medium
sudo -u agents just refresh-x
sudo -u agents just refresh-all
sudo -u agents just status
sudo -u agents just playbook-rebuild medium
```

## Vault paths

```
content-vault/
├── medium-vault/, x-vault/, linkedin-vault/, substack-vault/, seo-vault/
│   └── findings.jsonl, algo-watch.jsonl, sources.jsonl, raw/
└── playbooks/
    ├── medium-playbook.{md,json}
    ├── x-playbook.{md,json}
    ├── linkedin-playbook.{md,json}
    ├── substack-playbook.{md,json}
    └── seo-playbook.{md,json}
```

Each platform-playbook.json validates against `buildroom/schemas/platform-playbook.schema.json`.
