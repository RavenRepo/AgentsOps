"""Schema validation for Goku artifacts."""

import json
import jsonschema
from pathlib import Path
from typing import Any, List, Dict

class ValidationError(Exception):
    """Schema validation failed."""
    pass

# Schema paths (relative to buildroom/schemas/)
SCHEMAS = {
    "research-input": "research-input.schema.json",
    "idea-contract": "idea-contract.schema.json",
    "main-review": "main-review.schema.json",
    "product-plan": "product-plan.schema.json",
    "build-plan": "build-plan.schema.json",
    "verification": "verification.schema.json",
    "qa-verification": "qa-verification.schema.json",
    "verification-delta": "verification-delta.schema.json",
    "trust-report": "trust-report.schema.json",
    "retention-review": "retention-review.schema.json",
    "approval-ledger": "approval-ledger.schema.json",
}

_SCHEMA_CACHE: Dict[str, dict] = {}

def _get_schema(schema_name: str) -> dict:
    """Load and cache schema."""
    if schema_name in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[schema_name]
    
    schema_path = Path(__file__).parent.parent / "schemas" / SCHEMAS[schema_name]
    if not schema_path.exists():
        raise ValidationError(f"Schema not found: {schema_path}")
    
    with open(schema_path) as f:
        schema = json.load(f)
    
    _SCHEMA_CACHE[schema_name] = schema
    return schema

def validate(artifact: Any, schema_name: str) -> List[str]:
    """
    Validate artifact against schema.
    
    Returns list of error messages. Empty list = valid.
    """
    if schema_name not in SCHEMAS:
        return [f"Unknown schema: {schema_name}"]
    
    try:
        schema = _get_schema(schema_name)
    except ValidationError as e:
        return [str(e)]
    
    try:
        jsonschema.validate(instance=artifact, schema=schema)
        return []
    except jsonschema.ValidationError as e:
        return [str(e)]

def validate_or_raise(artifact: Any, schema_name: str) -> None:
    """Validate artifact. Raises ValidationError if invalid."""
    errors = validate(artifact, schema_name)
    if errors:
        raise ValidationError(f"Validation failed for {schema_name}:\n" + "\n".join(errors[:3]))
