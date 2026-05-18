#!/usr/bin/env python3
"""Tiny end-to-end test: pings the default model with a fixed prompt.

If this works, the full stack is wired:
  secrets.env -> apply_secrets.py -> Hermes .env -> os.environ
                                 -> lib.config.load_secrets_into_env()
                                 -> lib.llm.call_model() -> OpenRouter -> reply
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import call_model, load_secrets_into_env, load_profile_config, PROFILE_ROOT, LLMError


def main() -> int:
    load_secrets_into_env()
    config = load_profile_config(PROFILE_ROOT)
    model = config["models"]["default"]
    print(f"calling: {model}")
    t0 = time.time()
    try:
        reply = call_model(
            model=model,
            messages=[
                {"role": "system", "content": "You are a one-word echo. Reply with exactly one word."},
                {"role": "user", "content": "Say 'pong' and nothing else."},
            ],
            temperature=0.0,
            max_tokens=10,
        )
    except LLMError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    elapsed = time.time() - t0
    print(f"reply: {reply.strip()!r}  ({elapsed:.2f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
