import os
from typing import List, Dict, Any

import httpx

from .base import BaseProviderAdapter


class OpenAICompatibleAdapter(BaseProviderAdapter):
    """
    Provider adapter for OpenAI and any OpenAI-compatible API.

    Compatible with:
    - OpenAI (api.openai.com)
    - Azure OpenAI (set baseUrl to your Azure endpoint)
    - OpenRouter (openrouter.ai/api/v1)
    - SiliconFlow (api.siliconflow.cn/v1)
    - Qwen / Alibaba Cloud (dashscope compatible endpoint)
    - DeepSeek (api.deepseek.com/v1)
    - MiMo (use appropriate base URL)
    - Any other provider that implements /chat/completions spec

    To switch providers, change baseUrl and apiKeyEnvVar in agent.config.json.
    No code changes required.
    """

    def __init__(self, base_url: str, api_key_env_var: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key_env_var = api_key_env_var
        # Lazy: key is read on first call, not at startup.
        # This allows the service to start in mock mode without an API key.
        self._api_key: str = ""

    def _resolve_api_key(self) -> str:
        """Read API key from env on first actual call. Raises with error code prefix."""
        if not self._api_key:
            key = os.environ.get(self._api_key_env_var, "")
            if not key:
                raise ValueError(
                    f"api_key_missing: environment variable '{self._api_key_env_var}' is not set. "
                    f"Copy .env.example to .env and fill in your key."
                )
            self._api_key = key
        return self._api_key

    def get_provider_name(self) -> str:
        return "openai_compatible"

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._resolve_api_key()}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ValueError(
                f"Unexpected API response structure from {self.base_url}: {data}"
            ) from exc
