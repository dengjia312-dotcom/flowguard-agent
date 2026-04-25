from typing import Dict, List, Any

from .providers.base import BaseProviderAdapter
from .providers.openai_compatible import OpenAICompatibleAdapter

# TODO: Import additional provider adapters as they are implemented:
# from .providers.qwen import QwenAdapter
# from .providers.deepseek import DeepSeekAdapter
# from .providers.mimo import MiMoAdapter
# from .providers.gemini import GeminiAdapter
# from .providers.openrouter import OpenRouterAdapter
# from .providers.siliconflow import SiliconFlowAdapter


class ModelRouter:
    """
    The only entry point for model calls in business logic.

    Business layer calls: await model_router.call("planner", messages)
    It must never reference provider names, model IDs, or API keys directly.

    To add a new provider:
      1. Implement providers/your_provider.py (subclass BaseProviderAdapter)
      2. Add the provider key to agent.config.json under "providers"
      3. Register it in _init_providers() below
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self._providers: Dict[str, BaseProviderAdapter] = {}
        self._init_providers()

    def _init_providers(self) -> None:
        providers_config = self.config.get("providers", {})
        for provider_name, provider_conf in providers_config.items():
            if provider_name == "openai_compatible":
                self._providers[provider_name] = OpenAICompatibleAdapter(
                    base_url=provider_conf["baseUrl"],
                    api_key_env_var=provider_conf["apiKeyEnvVar"],
                )
            # TODO: Register additional providers here when adapters are ready:
            # elif provider_name == "qwen":
            #     self._providers[provider_name] = QwenAdapter(...)
            # elif provider_name == "deepseek":
            #     self._providers[provider_name] = DeepSeekAdapter(...)

    async def call(self, role: str, messages: List[Dict[str, str]]) -> str:
        """
        Route a model call by role to the correct provider + model.

        Args:
            role: One of "planner" | "vision" | "imageGeneration" | "embedding"
            messages: Chat message list

        Returns:
            Model response text

        Raises:
            ValueError: If role or provider is not configured
            Exception: On API failure
        """
        models_config = self.config.get("models", {})
        if role not in models_config:
            raise ValueError(
                f"Model role '{role}' is not defined in agent.config.json. "
                f"Available roles: {list(models_config.keys())}"
            )

        model_conf = models_config[role]
        provider_name = model_conf["provider"]

        if provider_name not in self._providers:
            raise ValueError(
                f"Provider '{provider_name}' is configured for role '{role}' "
                f"but has no registered adapter. "
                f"Add it to ModelRouter._init_providers()."
            )

        provider = self._providers[provider_name]
        return await provider.chat_completion(
            messages=messages,
            model=model_conf["model"],
            temperature=model_conf.get("temperature", 0.7),
            max_tokens=model_conf.get("maxTokens", 2048),
        )
