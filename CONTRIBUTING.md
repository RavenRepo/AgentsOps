# Contributing to Goku

Thanks for your interest! Contributions are welcome.

## Getting Started

1. **Fork** this repo
2. **Clone** your fork locally
3. **Create a branch** for your change (`git checkout -b feature/your-feature`)
4. **Make changes** (see guidelines below)
5. **Test** your changes
6. **Commit** with a clear message
7. **Push** and open a **Pull Request**

## Guidelines

### Code Style

- Python: `black` + `ruff` (we'll add CI checks)
- Schema: Keep JSON schemas minimal + documented
- Docs: Markdown with clear headings + examples

### Adding a New Agent Template

If you're creating a new template:

1. **Create** `templates/my-agent/` following the structure
2. **Write** `SOUL.md` (50-100 lines, identity + constraints)
3. **Add** `config.yaml` with model routing
4. **Stub** `scripts/main.py` with mode-driven entry point
5. **Document** in `README.md` what the agent does
6. **Test** locally before submitting

See `templates/hermes-profile/` and `templates/openclaw-agent/` for examples.

### Adding a New Schema

If you're adding a new artifact type:

1. **Define** the schema in `schemas/your-artifact.schema.json`
2. **Reference** it in `buildroom/agent_lib/validation.py`
3. **Add tests** in `tests/unit/test_validation.py`
4. **Document** the schema's purpose + version in a comment
5. **Add example** in `schemas/examples/` (demo JSON)

### Documentation

- Keep language accessible (explain jargon)
- Include real examples and code snippets
- Link between related docs
- Update `docs/CONCEPTS.md` if introducing new terms

### Pull Request Process

1. **Small PRs are better** — easier to review
2. **Clear title + description** — explain the "why"
3. **Link any issues** — use `Fixes #123` in the description
4. **Tests pass** — run `pytest` before submitting
5. **Docs updated** — if you change behavior, update docs

Example PR:
```markdown
# Add Telegram notification agent

**What**: New OpenClaw agent for Telegram delivery
**Why**: Needed for user notifications from the contract chain
**How**: 
- Added templates/openclaw-agent/telegram-notifier/
- Includes config.yaml with channel bindings
- Validates against existing schemas

Fixes #42
```

## Reporting Issues

**Before opening an issue**, check:
- [ ] Not a duplicate (search existing issues)
- [ ] Reproducible (include steps)
- [ ] In scope (feature request? see ROADMAP)

**When reporting a bug**, include:
```markdown
## Steps to Reproduce
1. ...
2. ...
3. ...

## Expected Behavior
...

## Actual Behavior
...

## Environment
- OS: [Fedora 40 / Ubuntu 24.04 / other]
- Python: [3.11 / 3.12 / etc.]
- Relevant output / logs
```

## Project Values

- **Ship it**: Complete > perfect. We iterate.
- **No self-approval**: Every change gets reviewed.
- **Docs matter**: Code without docs is a liability.
- **Tests catch bugs**: New code = new tests.
- **Schemas are sacred**: Validation is our firewall.

## Questions?

- **Architecture**: Post in [Discussions](https://github.com/RavenRepo/AgentsOps/discussions)
- **Bug**: [Open an issue](https://github.com/RavenRepo/AgentsOps/issues)
- **Design feedback**: Ping us before you PR — saves rework

Thanks for contributing! 🚀
