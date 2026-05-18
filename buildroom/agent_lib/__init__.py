"""Goku agent_lib — Shared utilities for Hermes profiles and OpenClaw agents."""

from .validation import validate, validate_or_raise, ValidationError
from .llm import call_model, is_provider_configured, LLMError
from .filesystem import (
    load_profile_config,
    load_secrets_into_env,
    STATE_DIR,
    TRACKS_DIR,
    EVENTS_LEDGER,
    APPROVAL_LEDGER,
    track_dir,
    artifact_path,
    list_tracks,
    has_artifact,
    read_artifact,
    write_json_atomic,
    write_atomic,
    append_jsonl,
    read_jsonl,
)
from .ledger import now_iso, now_run_id, slug_id

__version__ = "0.1.0"
__all__ = [
    # Validation
    "validate",
    "validate_or_raise",
    "ValidationError",
    # LLM
    "call_model",
    "is_provider_configured",
    "LLMError",
    # Filesystem
    "load_profile_config",
    "load_secrets_into_env",
    "STATE_DIR",
    "TRACKS_DIR",
    "EVENTS_LEDGER",
    "APPROVAL_LEDGER",
    "track_dir",
    "artifact_path",
    "list_tracks",
    "has_artifact",
    "read_artifact",
    "write_json_atomic",
    "write_atomic",
    "append_jsonl",
    "read_jsonl",
    # Ledger
    "now_iso",
    "now_run_id",
    "slug_id",
]
