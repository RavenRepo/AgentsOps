# Security Policy

## Reporting Vulnerabilities

**Please do NOT open a public issue** for security vulnerabilities.

Instead, email security@example.com (replace with actual contact) with:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

We will acknowledge within 48 hours and aim to fix within 7 days.

## Security Guidelines

### API Keys & Secrets

- **Never commit** `.env` or `secrets.env`
- **Never log** API keys, tokens, or passwords
- **Use environment variables** for all secrets
- **Rotate credentials** regularly
- **.env should be 0600** (read/write owner only)

### Schema Validation

- **Every artifact validates** before being promoted
- **Validation fails = no file written** — fail safe
- **Schema defines the contract** — LLM output must conform
- **Never bypass validation** even during debugging

### Path Traversal

- **All file paths are validated** before access
- **Paths are resolved relative to `workspace/`**
- **Path traversal (e.g., `../../../`) is rejected**
- **Use `(workspace_dir / declared_path).resolve()` + prefix check**

### Audit Trail

- **Every decision logs to `approval-ledger.jsonl`**
- **Append-only** — cannot be modified after creation
- **Includes timestamp + decision maker + reasoning**
- **Regularly backup** the audit ledger offsite

### Workspace Isolation

- **Each agent runs in its own workspace**
- **Coder can only write in `allowed_paths`**
- **OpenClaw agents run in isolated containers**
- **No cross-agent filesystem access**

### Network Security

- **All dashboards behind Tailscale** (or VPN)
- **SSH on Tailscale only** — no public port 22
- **API keys in environment** — not in config files
- **HTTPS for all HTTP services** (recommended)

### Dependencies

- **Pin dependency versions** in `requirements.txt`
- **Review dependencies before upgrading**
- **Use `pip audit`** to check for known vulnerabilities
- **Keep `buildroom/` separate** from agent workspaces

### LLM Input Validation

- **Never trust LLM output** — always validate against schema
- **Prompt injection via LLM** is a real threat
- **Sanitize before logging** to prevent log injection
- **Use JSON mode** when possible (structured output)

## Best Practices

### For Developers

- **Use type hints** (Python 3.10+)
- **Validate at system boundaries** (inputs from users, APIs, LLMs)
- **Fail securely** — when in doubt, deny
- **Log security events** (approval decisions, validation failures)
- **Review schema changes** — they are security boundaries

### For Operators

- **Restrict agent permissions** (file paths, model access)
- **Monitor audit ledger** for anomalies
- **Rotate API keys** on a schedule
- **Use Tailscale ACLs** to gate who can access dashboards
- **Keep Hermes/OpenClaw updated**

### For Users

- **Keep `.env` private** — treat like SSH keys
- **Regularly audit logs** — check `approval-ledger.jsonl`
- **Restrict workspace access** — only agents that need it
- **Use strong credentials** for Hermes/OpenClaw accounts
- **Report suspicious activity** — overly-detailed agents, odd artifacts

## Known Issues

None currently. Report any security concerns to the email above.

## Version History

- **2026-05 (v0.1.0)**: Initial release
