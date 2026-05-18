"""Config loader: secrets.env -> os.environ, ${VAR} expansion in YAML."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

# Use environment variables for deployment flexibility
_GOKU_DATA_DIR = os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")
SECRETS_PATH = Path(_GOKU_DATA_DIR) / "secrets.env"
_ENV_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::-([^}]*))?\}")


def load_secrets_into_env() -> None:
    """Source {GOKU_DATA_DIR}/secrets.env into os.environ. No-op if not readable."""
    if not SECRETS_PATH.exists():
        return
    try:
        text = SECRETS_PATH.read_text()
    except PermissionError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
            v = v[1:-1]
        os.environ.setdefault(k, v)


def expand_env(value: Any) -> Any:
    """Recursively expand ${VAR} and ${VAR:-default} in strings."""
    if isinstance(value, str):
        def repl(m: re.Match) -> str:
            var = m.group(1)
            default = m.group(2) or ""
            return os.environ.get(var, default)
        return _ENV_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    return value


def load_profile_config(profile_root: Path) -> dict[str, Any]:
    """Load profile_root/config.yaml with env vars expanded."""
    load_secrets_into_env()
    config_path = Path(profile_root) / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"profile config not found: {config_path}")
    with config_path.open() as f:
        raw = yaml.safe_load(f)
    return expand_env(raw)
