#!/usr/bin/env python3
"""Print provider readiness."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import is_provider_configured, load_secrets_into_env  # noqa: E402

CHECK = "\u2713"; X = "\u2717"
def main():
    load_secrets_into_env()
    print("Provider keys:")
    for name, m in [("openrouter", "openrouter/foo"),
                    ("opencode-zen", "opencode-zen/foo"),
                    ("opencode-go", "opencode-go/foo"),
                    ("nvidia", "nvidia/foo")]:
        ok = is_provider_configured(m)
        print(f"  {name:<14} : {CHECK if ok else X}")
if __name__ == "__main__": sys.exit(main() or 0)
