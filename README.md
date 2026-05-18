# Goku — Multi-Agent Orchestration Framework

**A production-grade framework for building compounding-judgment agent systems** combining strategic reasoning (Hermes brain) with tactical execution (OpenClaw hands).

Goku runs research, ideation, planning, building, verification, and retention agents on a unified state machine. **Nothing approves its own work.** Every artifact validates against schemas. Every decision audits to a ledger.

## ✨ What It Is

Goku is a complete, battle-tested agent orchestration system built on:

- **Hermes**: The brain — profiles (research, dreamer, main, coder, qa, retention, trust)
- **OpenClaw**: The hands — sandboxed agents with messaging channel binding
- **Buildroom**: Shared schemas, core libraries, and validation
- **Contract chain**: JSON artifacts flowing through deterministic pipelines
- **No self-approval**: Every cross-profile handoff validates independently

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) for the complete design.

## 🚀 Quick Start

### Installation

```bash
# Clone this repo
git clone https://github.com/RavenRepo/AgentsOps.git
cd AgentsOps

# Install buildroom dependencies
pip install -e buildroom/

# Set up your environment
cp .env.example .env  # and fill in API keys
```

### Adding Your First Agent

#### Option 1: Hermes Profile (agent in the brain)

```bash
cp -r templates/hermes-profile my-research-agent
cd my-research-agent

# Edit SOUL.md (agent identity + constraints)
# Edit config.yaml (model routing, schedule)
# Edit scripts/main.py (agent logic)

# Install and run
cd ../..
just refresh-profile my-research-agent
```

#### Option 2: OpenClaw Agent (agent in the hands)

```bash
cp -r templates/openclaw-agent my-osint-agent
cd my-osint-agent

# Edit SOUL.md (agent identity)
# Edit config.yaml (messaging channels)
# Edit scripts/agent.py (agent logic)

# Register with OpenClaw
openclaw agents add my-osint-agent --workspace my-osint-agent/workspace
```

See [docs/ONBOARDING.md](./docs/ONBOARDING.md) for detailed guides.

## 📚 Documentation

| Document | Purpose |
|---|---|
| [ARCHITECTURE.md](./docs/ARCHITECTURE.md) | System design, data flow, hard rules |
| [SETUP.md](./docs/SETUP.md) | Fresh installation on your infrastructure |
| [ONBOARDING.md](./docs/ONBOARDING.md) | Adding Hermes profiles or OpenClaw agents |
| [OPERATIONS.md](./docs/OPERATIONS.md) | Day-to-day troubleshooting + runbook |
| [CONCEPTS.md](./docs/CONCEPTS.md) | Key terminology + patterns |
| [FAQ.md](./docs/FAQ.md) | Common questions |

## 📁 Project Structure

```
goku-agents/
├── docs/                    # Complete guides (adapted from reference implementations)
├── templates/               # Agent scaffolding templates
│   ├── hermes-profile/     # Minimal Hermes profile with stubs
│   └── openclaw-agent/     # Minimal OpenClaw agent with stubs
├── examples/               # Real reference implementations
│   ├── hermes-profiles/    # Simplified versions of production profiles
│   └── openclaw-agents/    # Example OSINT + delivery agents
├── schemas/                # 13 JSON schemas (validation gates)
└── buildroom/              # Shared core library
    ├── agent_lib/          # Python package (LLM router, validation, state mgmt)
    ├── schemas/            # JSON schema definitions
    ├── scripts/            # Buildroom utilities (validator, cockpit renderer)
    └── examples/           # Demo artifacts
```

## 🔒 Design Principles

### 1. **No Self-Approval**
Every agent's output is independently verified. An agent never signs off on its own work.

### 2. **Schema Validation as Hard Gate**
13 JSON schemas. Every artifact validates before promotion. Validation fails = no file written.

### 3. **Append-Only Audit Trail**
Every decision logs to `approval-ledger.jsonl`. Tamper-evident, offsite-syncable, complete.

### 4. **Workspace Isolation**
Each agent's work lives in its own directory. Path traversal is cryptographically prevented.

### 5. **Provider Agnostic**
LLM model routing (`nvidia/...`, `opencode-go/...`, `openrouter/...`) is a single env var. Swap providers without changing agent code.

### 6. **Contract Chain**
Artifacts flow through deterministic pipelines:
```
research-input.json 
  ↓ (dreamer filters + walks)
idea-contract.json
  ↓ (main reviews, risk-scored)
product-plan.json
  ↓ (coder builds)
verification.json
  ↓ (qa independently verifies)
qa-verification.json + verification-delta.json
```

## 🛠️ Core Components

### buildroom/agent_lib
Shared Python package for all agents:
- `validation.py` — multi-schema validator
- `llm.py` — OpenAI-compatible multi-provider router
- `filesystem.py` — state + artifact management
- `ledger.py` — audit trail helpers

### schemas/
13 JSON schemas defining the contract:
- `research-input.schema.json` — findings + claims + sources
- `idea-contract.schema.json` — idea card structure
- `product-plan.schema.json` — build plan
- `qa-verification.schema.json` — QA verification receipt
- `verification-delta.schema.json` — QA findings (deltas)
- (and 8 more)

### Profiles
Each profile is a Python script + SOUL.md identity:
- **research**: Collects evidence (RSS, GitHub, APIs)
- **dreamer**: Pattern-noticer (4 walk modes, signal filter)
- **main**: Approval gate (risk-scoring, decision)
- **coder**: Builder (file generation + hashing)
- **qa**: Verifier (re-hashes, re-runs, compares)
- **trust**: Health reporter (reads deltas, flags anomalies)
- **retention**: Curator (keep/improve/park/prune)

## 💻 Local Development

```bash
# Install in editable mode
cd buildroom
pip install -e .

# Run tests
pytest tests/

# Validate schemas
python scripts/validate.py state/tracks/*/
```

## 📖 Common Commands

### Testing a Profile Locally

```bash
cd my-profile/scripts
python main.py --mode research --config ../config.yaml
```

### Validating All Artifacts

```bash
cd buildroom
python scripts/validate.py ../state/tracks/*/
```

### Checking Provider Connectivity

```bash
cd my-profile
python scripts/check_providers.py
```

## 🌐 Deployment

Designed for:
- ✅ Linux (Fedora, Ubuntu)
- ✅ systemd timers (auto-loop)
- ✅ Tailscale (secure network)
- ✅ Podman/Docker (agent sandboxing)
- ✅ Cloud (VPS, Hetzner, Linode, etc.)

See [docs/SETUP.md](./docs/SETUP.md) for detailed deployment instructions.

## 🔐 Security

- **No hardcoded secrets** — all API keys in `.env` (0600)
- **Schema validation** — prevents LLM output injection
- **Path traversal protection** — `{agent_work} / {declared_path}` verified
- **Audit ledger** — every decision logged + signed
- **Tailscale-only** — all dashboards behind encrypted mesh
- **Workspace isolation** — each agent's work sandboxed

See [SECURITY.md](./SECURITY.md) for security policies.

## 📝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines.

- **Issues**: Bug reports, feature requests
- **PRs**: Code improvements, documentation, new templates
- **Discussions**: Architecture, patterns, design questions

## 📄 License

[MIT](./LICENSE) — Use for commercial and private projects.

## 🤝 Support

- **Issues**: [GitHub Issues](https://github.com/RavenRepo/AgentsOps/issues)
- **Discussions**: [GitHub Discussions](https://github.com/RavenRepo/AgentsOps/discussions)
- **Docs**: Full documentation in [`docs/`](./docs/)

## 📦 What's in the Box

✅ **Complete architecture documentation** — from reference implementation  
✅ **13 JSON schemas** — validation gates  
✅ **Core library** (`agent_lib/`) — LLM routing, state mgmt, validation  
✅ **Agent templates** — Hermes profiles + OpenClaw agents  
✅ **Example implementations** — simplified reference profiles  
✅ **Test fixtures** — demo artifacts for all schemas  
✅ **Deployment guides** — systemd, Tailscale, CI/CD  
✅ **Troubleshooting runbook** — day-to-day operations  

---

**Ready to build?** Start with [docs/SETUP.md](./docs/SETUP.md) or jump straight to [docs/ONBOARDING.md](./docs/ONBOARDING.md) to add your first agent.
