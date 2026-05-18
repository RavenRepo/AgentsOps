"""Filesystem and state management for Goku agents."""

import json
import os
from pathlib import Path
from typing import Any, List, Optional, Dict

# Environment-based paths (customizable for each deployment)
DATA_DIR = Path(os.getenv("GOKU_DATA_DIR", "/opt/agent-data"))
STATE_DIR = DATA_DIR / "state"
TRACKS_DIR = STATE_DIR / "tracks"
EVENTS_LEDGER = STATE_DIR / "events.jsonl"
APPROVAL_LEDGER = STATE_DIR / "approval-ledger.jsonl"

def load_profile_config(profile_root: Path) -> dict:
    """Load profile config.yaml."""
    config_path = profile_root / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    
    # Simple YAML parse (or use pyyaml if available)
    import yaml
    with open(config_path) as f:
        return yaml.safe_load(f)

def load_secrets_into_env() -> None:
    """Load secrets.env into environment."""
    secrets_path = DATA_DIR / "secrets.env"
    if not secrets_path.exists():
        return  # Not required
    
    with open(secrets_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                key, _, value = line.partition("=")
                os.environ[key.strip()] = value.strip()

def track_dir(slug: str) -> Path:
    """Get track directory for slug."""
    return TRACKS_DIR / slug

def artifact_path(slug: str, artifact_type: str) -> Path:
    """Get artifact path for slug + type (e.g., "idea-contract")."""
    return track_dir(slug) / f"{slug}.{artifact_type}.json"

def list_tracks() -> List[str]:
    """List all track slugs."""
    if not TRACKS_DIR.exists():
        return []
    return [d.name for d in TRACKS_DIR.iterdir() if d.is_dir()]

def has_artifact(slug: str, artifact_type: str) -> bool:
    """Check if artifact exists."""
    return artifact_path(slug, artifact_type).exists()

def read_artifact(slug: str, artifact_type: str) -> dict:
    """Read artifact JSON."""
    path = artifact_path(slug, artifact_type)
    if not path.exists():
        raise FileNotFoundError(f"Artifact not found: {path}")
    with open(path) as f:
        return json.load(f)

def write_json_atomic(path: Path, data: Any) -> None:
    """Atomically write JSON to file (write temp, rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "w") as f:
        json.dump(data, f, indent=2)
    temp_path.replace(path)

def write_atomic(path: Path, content: str) -> None:
    """Atomically write text to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "w") as f:
        f.write(content)
    temp_path.replace(path)

def append_jsonl(path: Path, obj: dict) -> None:
    """Append JSON line to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")

def read_jsonl(path: Path) -> List[dict]:
    """Read JSONL file into list of dicts."""
    if not path.exists():
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]

def tracks_pending(artifact_type: str) -> List[str]:
    """List slugs with artifact_type."""
    pending = []
    for slug in list_tracks():
        if has_artifact(slug, artifact_type):
            pending.append(slug)
    return pending
