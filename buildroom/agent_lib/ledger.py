"""Helpers for append-only JSONL ledgers + ID generation."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


def now_iso() -> str:
    """ISO 8601 UTC timestamp with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_run_id() -> str:
    """Compact run id: 20260517-001234"""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def slug_id(prefix: str | None = None) -> str:
    """Generate a unique slug. Optionally prefixed."""
    short = uuid.uuid4().hex[:8]
    return f"{prefix}-{short}" if prefix else short


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Atomically append one record. Creates parent dir if missing."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
    # Open with O_APPEND so concurrent writers don't corrupt each other.
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o664)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Iterate records. Skips blank lines and lines that fail to parse."""
    path = Path(path)
    if not path.exists():
        return
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def write_atomic(path: Path, content: str) -> None:
    """Write a file atomically (write to .tmp then rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def write_json_atomic(path: Path, data: Any, indent: int = 2) -> None:
    """JSON-encode then atomic write."""
    write_atomic(path, json.dumps(data, indent=indent, ensure_ascii=False))
