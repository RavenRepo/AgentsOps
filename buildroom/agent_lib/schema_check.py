"""Schema validation against buildroom JSON schemas."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

# Use environment variables for deployment flexibility
_BUILDROOM_PATH = os.environ.get("BUILDROOM_PATH", "/opt/agent-data/buildroom")
SCHEMAS_DIR = Path(_BUILDROOM_PATH) / "schemas"


class ValidationError(Exception):
    def __init__(self, schema_name: str, errors: list[str]):
        super().__init__(f"{schema_name}: {len(errors)} error(s)")
        self.schema_name = schema_name
        self.errors = errors


@lru_cache(maxsize=1)
def _registry():
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    resources = []
    for p in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        with p.open() as f:
            doc = json.load(f)
        resource = Resource.from_contents(doc, default_specification=DRAFT202012)
        if "$id" in doc:
            resources.append((doc["$id"], resource))
        resources.append((p.name, resource))
    return Registry().with_resources(resources)


def validate(data: dict[str, Any], schema_name: str) -> list[str]:
    """Return [] if valid, else list of error strings."""
    from jsonschema import Draft202012Validator

    schema_path = SCHEMAS_DIR / f"{schema_name}.schema.json"
    if not schema_path.exists():
        return [f"schema not found: {schema_path}"]
    with schema_path.open() as f:
        schema = json.load(f)
    validator = Draft202012Validator(schema, registry=_registry())
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]


def validate_or_raise(data: dict[str, Any], schema_name: str) -> None:
    errs = validate(data, schema_name)
    if errs:
        raise ValidationError(schema_name, errs)
