from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseProviderAdapter(ABC):
    """
    Abstract base class for all model provider adapters.

    Business layer must ONLY call ModelRouter.call(role, messages).
    It must never instantiate a provider directly or reference provider-specific APIs.

    To add a new provider (Qwen, DeepSeek, MiMo, Gemini, OpenRouter, SiliconFlow...):
    1. Create a new file in providers/ (e.g., qwen.py)
    2. Subclass BaseProviderAdapter
    3. Implement chat_completion() and get_provider_name()
    4. Register the provider in ModelRouter._init_providers()
    """

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> str:
        """
        Call the provider's chat completion API.

        Args:
            messages: List of {"role": "user"|"assistant"|"system", "content": str}
            model: Model identifier string (e.g. "gpt-4o", "deepseek-chat")
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Provider-specific extra parameters

        Returns:
            The assistant's response text (content only, not the full API response object)

        Raises:
            Exception: On API errors, network failures, or invalid responses
        """
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return a unique string identifier for this provider."""
        pass
