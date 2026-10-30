"""Explicit provider/model selection with no fallback or content routing."""

from app.models.base import ModelProvider


class ProviderConfigurationError(ValueError):
    pass


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, tuple[ModelProvider, frozenset[str]]] = {}

    def register(self, name: str, adapter: ModelProvider, models: set[str]) -> None:
        if not name or not models or name in self._providers:
            raise ValueError("invalid_provider_registration")
        self._providers[name] = (adapter, frozenset(models))

    def resolve(self, provider: str, model: str) -> ModelProvider:
        if provider not in self._providers:
            raise ProviderConfigurationError("unknown_provider")
        adapter, models = self._providers[provider]
        if model not in models:
            raise ProviderConfigurationError("model_not_configured")
        return adapter

    def configured_models(self) -> dict[str, list[str]]:
        return {name: sorted(models) for name, (_, models) in sorted(self._providers.items())}
