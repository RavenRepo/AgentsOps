"""Shared library for Goku VPS agent profiles.

Profiles import from here instead of duplicating common code:

    from agent_lib import (
        call_model, is_provider_configured,
        validate, validate_or_raise, ValidationError,
        load_profile_config, load_secrets_into_env,
        now_iso, now_run_id, slug_id,
        append_jsonl, read_jsonl, write_atomic, write_json_atomic,
        STATE_DIR, TRACKS_DIR, track_dir, artifact_path, list_tracks,
        has_artifact, read_artifact, tracks_pending,
    )

Each profile keeps its OWN vault_paths.py for filesystem layout (paths
differ per profile), but everything else is shared.
"""
from .schema_check import validate, validate_or_raise, ValidationError
from .llm import call_model, is_provider_configured, parse_model_id, LLMError
from .config import load_profile_config, load_secrets_into_env, expand_env
from .ledger import (
    now_iso,
    now_run_id,
    slug_id,
    append_jsonl,
    read_jsonl,
    write_atomic,
    write_json_atomic,
)
from .state_paths import (
    STATE_DIR,
    TRACKS_DIR,
    EVENTS_LEDGER,
    APPROVAL_LEDGER,
    ARTIFACT_KINDS,
    track_dir,
    artifact_path,
    list_tracks,
    has_artifact,
    read_artifact,
    tracks_pending,
)

__all__ = [
    "validate",
    "validate_or_raise",
    "ValidationError",
    "call_model",
    "is_provider_configured",
    "parse_model_id",
    "LLMError",
    "load_profile_config",
    "load_secrets_into_env",
    "expand_env",
    "now_iso",
    "now_run_id",
    "slug_id",
    "append_jsonl",
    "read_jsonl",
    "write_atomic",
    "write_json_atomic",
    "STATE_DIR",
    "TRACKS_DIR",
    "EVENTS_LEDGER",
    "APPROVAL_LEDGER",
    "ARTIFACT_KINDS",
    "track_dir",
    "artifact_path",
    "list_tracks",
    "has_artifact",
    "read_artifact",
    "tracks_pending",
]
