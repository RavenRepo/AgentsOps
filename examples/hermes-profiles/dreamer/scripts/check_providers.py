#!/usr/bin/env python3
"""Print provider readiness for the dreamer profile."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import is_provider_configured, load_secrets_into_env  # noqa: E402

CHECK = "\u2713"
X = "\u2717"


def main() -> int:
    load_secrets_into_env()
    print("Provider keys:")
    for name, marker in [
        ("openrouter", "openrouter/foo"),
        ("opencode-zen", "opencode-zen/foo"),
        ("nvidia", "nvidia/foo"),
    ]:
        ok = is_provider_configured(marker)
        print(f"  {name:<14} : {CHECK if ok else X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
