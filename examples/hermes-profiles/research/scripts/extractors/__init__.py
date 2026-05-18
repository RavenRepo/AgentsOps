"""Extractors turn raw collector items into structured artifacts."""
from .findings import extract_findings
from .claims import extract_claims

__all__ = ["extract_findings", "extract_claims"]
