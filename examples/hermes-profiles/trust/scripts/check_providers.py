#!/usr/bin/env python3
"""Trust profile provider readiness probe (mostly deterministic)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import is_provider_configured, load_secrets_into_env

CHECK = "\u2713"
X = "\u2717"


def main() -> int:
    load_secrets_into_env()
    print("Provider keys (informational — trust is mostly deterministic):")
    probes = [
        ("openrouter",   "openrouter/foo"),
        ("opencode-zen", "opencode-zen/foo"),
        ("opencode-go",  "opencode-go/foo"),
        ("nvidia",       "nvidia/foo"),
    ]
    for name, m in probes:
        ok = is_provider_configured(m)
        print(f"  {name:<14} : {CHECK if ok else X}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
