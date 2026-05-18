# Goku: Enterprise-Grade Multi-Agent Orchestration Framework

<div align="center">

[![GitHub license](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/RavenRepo/AgentsOps?style=social)](https://github.com/RavenRepo/AgentsOps)
[![GitHub forks](https://img.shields.io/github/forks/RavenRepo/AgentsOps?style=social)](https://github.com/RavenRepo/AgentsOps)
[![Documentation](https://img.shields.io/badge/docs-read%20the%20docs-success)](./docs)

**Building autonomous systems that compound judgment through verified decision chains.**

[Features](#-features) • [Quick Start](#-quick-start) • [Architecture](#-architecture) • [Documentation](#-documentation) • [Contributing](#-contributing)

</div>

---

## Overview

**Goku** is a production-grade framework for building **compounding-judgment agent systems** where multiple specialized agents collaborate through deterministic, auditable decision chains. Think of it as a system where:

- **Hermes** provides strategic reasoning (the brain)
- **OpenClaw** enables tactical execution (the hands)  
- **Buildroom** ensures every decision is schema-validated and cryptographically audited
- **No agent approves its own work** — every handoff is independently verified

> Perfect for teams building AI systems that need auditability, determinism, and human oversight at scale.

### Real-World Use Cases

🔬 **Research Automation** — Autonomous research profiles that compound evidence into actionable insights  
🏗️ **Product Development** — Idea → Design → Build → Verify → Iterate cycles  
🔍 **Security & Compliance** — Auditable decision chains with tamper-evident ledgers  
📊 **Content Operations** — Multi-stage content review, optimization, and publication  
⚙️ **Enterprise Automation** — Mission-critical workflows with hard validation gates

---

## ✨ Key Features

### 🎯 Core Capabilities

| Feature | Description |
|---------|-------------|
| **Schema-Driven Validation** | 21 JSON schemas enforce artifact structure. Validation failures block writes. |
| **No Self-Approval** | Every agent's output independently verified by another agent. Hard architectural rule. |
| **Append-Only Audit Trail** | Every decision cryptographically logged to `approval-ledger.jsonl`. Tamper-evident. |
| **Multi-Provider LLM Routing** | Switch between OpenRouter, OpenCode Zen, NVIDIA, XAI with a single environment variable. |
| **Workspace Isolation** | Each agent's work sandboxed. Path traversal prevented by design. |
| **Deterministic Pipelines** | Artifacts flow through predictable contract chains. Same input = same output. |

### 🏗️ Architecture Highlights

- **Hermes Profiles**: 10 specialized reasoning agents (research, dreamer, main, coder, qa, trust, retention, etc.)
- **OpenClaw Agents**: Sandboxed execution layer with channel binding
- **Buildroom**: Shared core library (`agent_lib`) + validation engine
- **Contract Chain**: JSON artifacts validate at every stage before promotion
- **State Machine**: Deterministic progression through well-defined phases

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.9+**
- **pip** or **uv**
- **Git**
- API keys for at least one LLM provider (optional, for local testing)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/RavenRepo/AgentsOps.git
cd AgentsOps

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install buildroom core library
cd buildroom
pip install -e .
cd ..

# 4. Set up environment
cp .env.example .env
# Edit .env and add your API keys (optional for development)
```

### Your First Agent (5 minutes)

#### Create a Hermes Profile

```bash
# Clone the template
cp -r templates/hermes-profile my-first-agent
cd my-first-agent

# Edit agent identity
nano SOUL.md

# Edit configuration
nano config.yaml

# Edit agent logic
nano scripts/main.py

# Back to root and validate
cd ../..
python buildroom/scripts/validate.py my-first-agent/config.yaml
```

#### Run a Profile Locally

```bash
export GOKU_DATA_DIR=./goku-data
export BUILDROOM_PATH=./buildroom

cd examples/hermes-profiles/research
python scripts/main.py --config config.yaml --mode test
```

#### Test Artifact Validation

```bash
# Validate all artifacts in state directory
python buildroom/validators/artifact_validator.py state/tracks/example-001/
```

---

## 🏗️ Architecture

### System Design Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        CONTRACT CHAIN                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  research-input.json                                            │
│        ↓ (Dreamer filters, walks, patterns)                     │
│  idea-contract.json                                             │
│        ↓ (Main reviews, risk-scores, approves)                  │
│  product-plan.json                                              │
│        ↓ (Coder builds, generates files, hashes)                │
│  verification.json                                              │
│        ↓ (QA independently re-hashes, re-runs)                  │
│  qa-verification.json + verification-delta.json                 │
│        ↓ (Trust reads deltas, flags anomalies)                  │
│  approval-ledger.jsonl (append-only, tamper-evident)            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Component Layers

**Layer 1: Reasoning (Hermes)**
- Research Agent → Evidence collection + synthesis
- Dreamer Agent → Pattern recognition + signal filtering
- Main Agent → Decision gate + risk scoring
- Trust Agent → Anomaly detection + health reporting
- Retention Agent → Decision curation + improvement

**Layer 2: Execution (OpenClaw)**
- Builder Agent → File generation + verification
- QA Agent → Independent verification + re-testing
- Delivery Agent → Deployment + monitoring

**Layer 3: Validation (Buildroom)**
- 21 JSON schemas → Artifact structure enforcement
- LLM router → Multi-provider model abstraction
- State manager → Append-only ledger + workspace isolation
- Validator → Pre-flight checks before promotion

---

## 📚 Documentation

| Document | Purpose | Audience |
|----------|---------|----------|
| [**SETUP.md**](./docs/SETUP.md) | Fresh installation on your infrastructure | DevOps, Platform Teams |
| [**ARCHITECTURE.md**](./docs/ARCHITECTURE.md) | System design, data flow, hard rules | Architects, Tech Leads |
| [**ONBOARDING.md**](./docs/ONBOARDING.md) | Adding Hermes profiles or OpenClaw agents | Developers, Data Scientists |
| [**OPERATIONS.md**](./docs/OPERATIONS.md) | Troubleshooting + operational runbooks | SRE, Operations Teams |
| [**CONCEPTS.md**](./docs/CONCEPTS.md) | Terminology + design patterns | Everyone |
| [**FAQ.md**](./docs/FAQ.md) | Common questions + gotchas | Everyone |

---

## 📁 Project Structure

```
AgentsOps/
├── 📖 docs/                           # Complete documentation
│   ├── ARCHITECTURE.md
│   ├── SETUP.md
│   ├── ONBOARDING.md
│   ├── OPERATIONS.md
│   ├── CONCEPTS.md
│   ├── FAQ.md
│   └── TROUBLESHOOTING.md
│
├── 🏗️ buildroom/                      # Core shared library
│   ├── agent_lib/
│   │   ├── __init__.py                # Package re-exports
│   │   ├── config.py                  # Secrets + env-var expansion
│   │   ├── llm.py                     # Multi-provider LLM router
│   │   ├── schema_check.py            # Artifact validation engine
│   │   ├── state_paths.py             # Shared state layout
│   │   └── ledger.py                  # Append-only audit trail
│   │
│   ├── schemas/                       # 21 JSON validation schemas
│   │   ├── _common.schema.json
│   │   ├── research-input.schema.json
│   │   ├── idea-contract.schema.json
│   │   ├── product-plan.schema.json
│   │   ├── build-plan.schema.json
│   │   ├── verification.schema.json
│   │   ├── qa-verification.schema.json
│   │   └── [14 more schemas]
│   │
│   ├── scripts/                       # Utilities
│   │   ├── validate.py                # Artifact validator
│   │   ├── bootstrap-env.sh           # Environment setup
│   │   └── health-check.sh
│   │
│   ├── validators/
│   │   └── artifact_validator.py
│   │
│   ├── Justfile                       # Operations recipes
│   └── pyproject.toml
│
├── 🎯 examples/                       # Real reference implementations
│   ├── hermes-profiles/               # 10 production profiles
│   │   ├── research/
│   │   ├── dreamer/
│   │   ├── main/
│   │   ├── coder/
│   │   ├── qa/
│   │   ├── trust/
│   │   ├── retention/
│   │   ├── content-knowledge/
│   │   ├── content-studio/
│   │   └── concierge/
│   │
│   └── openclaw-agents/
│       ├── main/
│       └── osint-recon/
│
├── 📋 templates/                      # Agent scaffolding
│   ├── hermes-profile/
│   │   ├── SOUL.md
│   │   ├── config.yaml
│   │   └── scripts/main.py
│   │
│   └── openclaw-agent/
│       ├── SOUL.md
│       ├── config.yaml
│       └── scripts/agent.py
│
├── 🧪 tests/                          # Test suite
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── 🐳 docker/                         # Container configurations
│   ├── Dockerfile.hermes
│   ├── Dockerfile.openclaw
│   └── docker-compose.yml
│
├── ⚙️ config/                         # Configuration templates
│   ├── systemd/
│   └── env/
│
├── .env.example                       # Environment template
├── .gitignore                         # Git exclusions
├── CONTRIBUTING.md                    # Contribution guidelines
├── LICENSE                            # MIT License
├── SECURITY.md                        # Security policies
└── README.md                          # This file
```

---

## 🔐 Design Principles

### 1️⃣ **No Self-Approval**
Every agent's output is independently verified by a different agent. An agent never signs off on its own work. This is a hard architectural constraint, not a policy.

### 2️⃣ **Schema-Driven Validation**
21 JSON schemas define valid artifact structures. Validation is not optional—it's a gate. Invalid artifacts cannot be written to the state machine.

```python
# Invalid artifact = ValidationError + no state change
try:
    validate_artifact(output, schema="product-plan")
except ValidationError:
    raise  # No partial writes, no logging bypass
```

### 3️⃣ **Append-Only Audit Trail**
Every decision logs to `approval-ledger.jsonl`. Entries are immutable. The file is append-only by design (never truncated, never edited). Perfect for compliance audits.

```json
{"timestamp": "2026-05-18T16:30:00Z", "agent": "main", "decision": "approve", "artifact": "track-001", "hash": "sha256:abc..."}
{"timestamp": "2026-05-18T16:31:05Z", "agent": "qa", "decision": "verify-ok", "artifact": "track-001", "hash": "sha256:def..."}
```

### 4️⃣ **Workspace Isolation**
Each agent's work lives in its own directory. Path traversal is prevented by cryptographic path verification. No agent can access another agent's workspace without explicit permission.

### 5️⃣ **Provider Agnostic**
LLM model routing is environment-based. Change `HERMES_DEFAULT_MODEL` to switch from OpenRouter to NVIDIA to OpenCode Zen—without touching agent code.

### 6️⃣ **Deterministic Pipelines**
Artifacts flow through well-defined contract chains. Same input + same model + same seed = same output (modulo LLM randomness). Reproducible by design.

---

## 🛠️ Core Components

### buildroom/agent_lib

Shared Python package used by all agents:

- **config.py** — Loads `secrets.env`, expands `${VAR}` patterns in YAML
- **llm.py** — Multi-provider router (OpenRouter, OpenCode Zen, NVIDIA, XAI)
- **schema_check.py** — Validates artifacts against JSON schemas
- **state_paths.py** — Shared state directory layout
- **ledger.py** — Append-only audit trail helpers

### Hermes Profiles (10 Reasoning Agents)

| Profile | Purpose | Input | Output |
|---------|---------|-------|--------|
| **research** | Evidence collection + synthesis | APIs, RSS, GitHub | research-input.json |
| **dreamer** | Pattern recognition + signal filtering | research-input.json | idea-contract.json |
| **main** | Decision gate + risk scoring | idea-contract.json | product-plan.json |
| **coder** | Builder + file generator | product-plan.json | verification.json |
| **qa** | Independent verifier | verification.json | qa-verification.json |
| **trust** | Health reporter + anomaly detector | qa-verification.json | trust-report.json |
| **retention** | Decision curator + improver | All artifacts | retention-review.json |
| **content-knowledge** | Knowledge base builder | product-plan.json | content-track.json |
| **content-studio** | Content optimizer | content-track.json | seo-recommendations.json |
| **concierge** | Delivery orchestrator | All artifacts | approval-ledger.jsonl |

---

## 💻 Local Development

### Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install buildroom in editable mode
cd buildroom
pip install -e .

# Run tests
pytest tests/

# Back to root
cd ..
```

### Testing a Profile

```bash
# Set environment variables
export GOKU_DATA_DIR=$PWD/goku-data
export BUILDROOM_PATH=$PWD/buildroom

# Run a profile
cd examples/hermes-profiles/research
python scripts/main.py --config config.yaml --mode test --verbose
```

### Validating Artifacts

```bash
# Validate all artifacts in a track
python buildroom/scripts/validate.py state/tracks/my-track-001/

# Validate a single artifact
python buildroom/scripts/validate.py state/tracks/my-track-001/my-track-001.idea-contract.json
```

---

## 🌐 Deployment

### Supported Environments

| Environment | Status | Guide |
|-------------|--------|-------|
| **Linux** (Ubuntu, Fedora) | ✅ Tested | [SETUP.md](./docs/SETUP.md) |
| **systemd** (Auto-loop) | ✅ Supported | [OPERATIONS.md](./docs/OPERATIONS.md) |
| **Docker** / **Podman** | ✅ Supported | [docker/](./docker/) |
| **VPS** (Hetzner, Linode) | ✅ Tested | [SETUP.md](./docs/SETUP.md) |

### Quick Deploy (Docker)

```bash
# Build Hermes profile container
docker build -f docker/Dockerfile.hermes -t goku-research:latest .

# Run with environment injection
docker run -e GOKU_DATA_DIR=/workspace/goku-data \
           -e BUILDROOM_PATH=/workspace/buildroom \
           -e HERMES_DEFAULT_MODEL=openrouter/anthropic/claude-sonnet-4 \
           -v ./goku-data:/workspace/goku-data \
           goku-research:latest
```

See [SETUP.md](./docs/SETUP.md) for detailed deployment instructions.

---

## 🔐 Security

### Built-In Security Features

✅ **No Hardcoded Secrets** — All API keys in `.env` (excluded from git)  
✅ **Schema Validation** — Prevents LLM prompt injection + output drift  
✅ **Path Traversal Prevention** — Cryptographic path verification  
✅ **Audit Ledger** — Every decision logged + tamper-evident  
✅ **Workspace Isolation** — Each agent's work sandboxed  

See [SECURITY.md](./SECURITY.md) for detailed security policies.

---

## 📝 Contributing

We welcome contributions! Goku is built on the belief that **better judgment comes from diverse perspectives**.

See [CONTRIBUTING.md](./CONTRIBUTING.md) for detailed guidelines and contribution areas.

---

## 🙏 Attribution & Credits

**Goku** is built on the innovative work and research of **[gkisokay](https://github.com/gkisokay)**, whose groundbreaking articles and architectural principles inspired the core workflow and design philosophy of this framework.

| Role | Contributor | Contribution |
|------|-------------|--------------|
| **Workflow & Architecture Inspiration** | [gkisokay](https://github.com/gkisokay) | Original research, design patterns, and compound judgment framework concepts |
| **Implementation & Repository** | Repository Maintainers | Goku framework, buildroom library, Hermes profiles, and production integration |

### Key Influences

- **Contract-Driven Architecture** — Inspired by gkisokay's research on deterministic agent systems
- **No Self-Approval Pattern** — Core principle from articles on auditable AI workflows  
- **Schema Validation Gates** — Architectural pattern for preventing drift and ensuring determinism
- **Append-Only Audit Trails** — Security approach pioneered in the original research

> Standing on the shoulders of giants — Goku is a production implementation of groundbreaking research in compound judgment systems.

---

## 📄 License

[MIT](./LICENSE) — Use for commercial and private projects.

---

## 🤝 Support & Community

| Channel | Purpose |
|---------|---------|
| [**Issues**](https://github.com/RavenRepo/AgentsOps/issues) | Bug reports, feature requests |
| [**Discussions**](https://github.com/RavenRepo/AgentsOps/discussions) | Architecture, design patterns, help |
| [**Documentation**](./docs/) | Guides, references, tutorials |

---

## 🚀 Next Steps

**New to Goku?**
1. Read [ARCHITECTURE.md](./docs/ARCHITECTURE.md) (10 min)
2. Try [Quick Start](#-quick-start) (5 min)
3. Build your first profile using [ONBOARDING.md](./docs/ONBOARDING.md) (30 min)

**Want to Deploy?**
1. Follow [SETUP.md](./docs/SETUP.md) (30 min)
2. Set up systemd timers or Docker containers
3. Monitor with [OPERATIONS.md](./docs/OPERATIONS.md)

**Ready to Contribute?**
1. Fork the repo
2. See [CONTRIBUTING.md](./CONTRIBUTING.md)
3. Submit a PR

---

<div align="center">

**[📖 Docs](./docs) • [🐛 Issues](https://github.com/RavenRepo/AgentsOps/issues) • [💬 Discussions](https://github.com/RavenRepo/AgentsOps/discussions) • [⭐ Star](https://github.com/RavenRepo/AgentsOps)**

Built with ❤️ by the Goku team. MIT License © 2026.

</div>
