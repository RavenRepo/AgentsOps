#!/usr/bin/env python3
"""Print provider readiness for the research-agent profile (no key values printed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import is_provider_configured, load_secrets_into_env

CHECK_MARK = "\u2713"
X_MARK = "\u2717"


def main() -> int:
    load_secrets_into_env()
    print("Provider keys (from os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/secrets.env):")
    for name, marker in [("openrouter", "openrouter/foo"),
                         ("opencode-zen", "opencode-zen/foo"),
                         ("nvidia", "nvidia/foo")]:
        ok = is_provider_configured(marker)
        print(f"  {name:<14} : {CHECK_MARK if ok else X_MARK}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
