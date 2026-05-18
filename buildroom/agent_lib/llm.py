"""Multi-provider LLM router for Goku agents."""

import os
import json
from typing import Optional, List, Dict, Any
import httpx

class LLMError(Exception):
    """LLM provider error."""
    pass

# Provider configuration
PROVIDERS = {
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "key_env": "NVIDIA_API_KEY",
    },
    "opencode-zen": {
        "base_url": "https://opencode.ai/zen/v1",
        "key_env": "OPENCODE_API_KEY",
    },
    "opencode-go": {
        "base_url": "https://opencode.ai/zen/go/v1",
        "key_env": "OPENCODE_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
    },
}

def is_provider_configured(model_id: str) -> bool:
    """Check if provider for model_id has API key configured."""
    provider, _ = model_id.split("/", 1)
    if provider not in PROVIDERS:
        return False
    key_env = PROVIDERS[provider]["key_env"]
    return bool(os.getenv(key_env))

def call_model(
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    json_mode: bool = False,
    **kwargs
) -> str:
    """
    Call LLM model.
    
    Args:
        model: Model ID (e.g., "nvidia/meta/llama-3.1-8b-instruct")
        messages: List of {"role": "...", "content": "..."} dicts
        temperature: Sampling temperature (0-1)
        json_mode: Request JSON response
        **kwargs: Additional params (max_tokens, etc.)
    
    Returns:
        Model response text
        
    Raises:
        LLMError: If provider not configured or request fails
    """
    # Parse model ID
    if "/" not in model:
        raise LLMError(f"Invalid model ID: {model}. Use provider/model format.")
    
    provider, model_name = model.split("/", 1)
    
    if provider not in PROVIDERS:
        raise LLMError(f"Unknown provider: {provider}")
    
    provider_config = PROVIDERS[provider]
    api_key = os.getenv(provider_config["key_env"])
    if not api_key:
        raise LLMError(f"API key not configured for {provider}. Set {provider_config['key_env']}")
    
    # Build request
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        **kwargs,
    }
    
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    
    # Call API
    try:
        with httpx.Client() as client:
            response = client.post(
                f"{provider_config['base_url']}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
    except httpx.HTTPError as e:
        raise LLMError(f"Request failed: {e}")
    except (KeyError, json.JSONDecodeError) as e:
        raise LLMError(f"Invalid response: {e}")
