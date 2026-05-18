"""OpenAI-compatible LLM client with multi-provider routing."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key_env: str


def _providers() -> dict[str, ProviderConfig]:
    return {
        "openrouter": ProviderConfig(
            name="openrouter",
            base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            api_key_env=
        ),
        "opencode-zen": ProviderConfig(
            name="opencode-zen",
            base_url=os.environ.get("OPENCODE_ZEN_BASE_URL", "https://opencode.ai/zen/v1"),
            api_key_env=
        ),
        "opencode-go": ProviderConfig(
            name="opencode-go",
            base_url=os.environ.get("OPENCODE_GO_BASE_URL", "https://opencode.ai/zen/go/v1"),
            api_key_env="OPENCODE_GO_API_KEY",
        ),
        "nvidia": ProviderConfig(
            name="nvidia",
            base_url=os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            api_key_env=
        ),
        "xai": ProviderConfig(
            name="xai",
            base_url=os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1"),
            api_key_env="XAI_API_KEY",
        ),
    }


class LLMError(Exception):
    """Provider/network error context."""


def parse_model_id(model_id: str) -> tuple[ProviderConfig, str]:
    if "/" not in model_id:
        raise LLMError(f"model id missing provider prefix: {model_id!r}")
    provider, _, name = model_id.partition("/")
    providers = _providers()
    if provider not in providers:
        raise LLMError(f"unknown provider {provider!r} in {model_id!r}; "
                       f"known: {list(providers)}")
    return providers[provider], name


def get_client(provider: ProviderConfig):
    try:
        from openai import OpenAI
    except ImportError as e:
        raise LLMError("openai package not installed") from e
    api_key = os.environ.get(provider.api_key_env)
    if not api_key:
        raise LLMError(
            f"{provider.api_key_env} not set. Fill os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/secrets.env "
            f"and run 'just apply-secrets'."
        )
    return OpenAI(api_key=api_key, base_url=provider.base_url)


def call_model(
    model: str,
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int | None = None,
    json_mode: bool = False,
    timeout: float = 60.0,
    max_retries: int = 2,
) -> str:
    """Call a chat completion. Returns content string."""
    provider, model_name = parse_model_id(model)
    client = get_client(provider)

    kwargs: dict = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "timeout": timeout,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(1 + attempt * 2)
                continue
            raise LLMError(f"{provider.name}/{model_name} failed: {e}") from e
    raise LLMError(f"{provider.name}/{model_name} failed: {last_err}")


def is_provider_configured(model_id: str) -> bool:
    try:
        provider, _ = parse_model_id(model_id)
    except LLMError:
        return False
    return bool(os.environ.get(provider.api_key_env))
