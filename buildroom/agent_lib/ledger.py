"""Ledger and ID generation helpers for Goku."""

import uuid
from datetime import datetime, timezone

def now_iso() -> str:
    """Current timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()

def now_run_id() -> str:
    """Generate run ID (timestamp-based)."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    uid = str(uuid.uuid4())[:8]
    return f"{ts}-{uid}"

def slug_id(text: str) -> str:
    """Convert text to URL-safe slug."""
    import re
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    return slug[:50]  # max 50 chars
