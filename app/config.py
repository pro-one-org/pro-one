"""Server-owned allowlists. Secrets are read only when constructing adapters."""

from dataclasses import dataclass, field
import os
import re

from app.models.anthropic_adapter import AnthropicProvider
from app.models.openai_adapter import OpenAIProvider
from app.models.registry import ProviderRegistry
from app.models.testing import DeterministicTestProvider, TEST_MODEL


def authority_networks(value):
    names = value.split(",") if value else []
    enabled = frozenset(names)
    if len(enabled) != len(names) or enabled - {"virginia_official", "courtlistener"}:
        raise ValueError("unknown_or_duplicate_authority_provider")
    return enabled


@dataclass(frozen=True)
class Settings:
    mode: str = "development"
    provider: str = "testing"
    model: str = TEST_MODEL
    openai_model: str = ""
    anthropic_model: str = ""
    authority_network: str = ""
    corpus_path: str = ""
    conversation_signing_key: bytes | None = field(default=None, repr=False)

    @property
    def courtlistener_enabled(self):
        return "courtlistener" in authority_networks(self.authority_network)

    @classmethod
    def from_environment(cls):
        mode = os.environ.get("PRO_ONE_MODE", "development")
        if mode not in {"development", "production"}:
            raise RuntimeError("Invalid PRO_ONE_MODE; use development or production.")
        provider = os.environ.get("PRO_ONE_MODEL_PROVIDER") or ("testing" if mode == "development" else "")
        model = os.environ.get("PRO_ONE_MODEL") or (TEST_MODEL if provider == "testing" else "")
        authority = os.environ.get("PRO_ONE_AUTHORITY_NETWORK", "")
        try:
            authority_networks(authority)
        except ValueError:
            raise RuntimeError("Invalid PRO_ONE_AUTHORITY_NETWORK") from None
        state_key = os.environ.get("PRO_ONE_CONVERSATION_SIGNING_KEY", "")
        if state_key and not re.fullmatch(r"[0-9a-fA-F]{64}", state_key):
            raise RuntimeError("Invalid PRO_ONE_CONVERSATION_SIGNING_KEY; expected 64 hexadecimal characters.")
        return cls(mode, provider, model, os.environ.get("PRO_ONE_OPENAI_MODEL", ""), os.environ.get("PRO_ONE_ANTHROPIC_MODEL", ""), authority,
                   os.environ.get("PRO_ONE_CORPUS_PATH", ""), bytes.fromhex(state_key) if state_key else None)

    def registry(self, environment=None) -> ProviderRegistry:
        env = os.environ if environment is None else environment
        registry = ProviderRegistry()
        if self.mode == "development":
            registry.register("testing", DeterministicTestProvider(), {TEST_MODEL})
        for provider, adapter, key_name, model in (
            ("openai", OpenAIProvider, "OPENAI_API_KEY", self.openai_model),
            ("anthropic", AnthropicProvider, "ANTHROPIC_API_KEY", self.anthropic_model),
        ):
            models = {m for m in (model, self.model if self.provider == provider else "") if m}
            if models and env.get(key_name):
                registry.register(provider, adapter(env[key_name]), models)
        return registry

    def status(self, registry: ProviderRegistry) -> dict:
        available = registry.configured_models()
        if self.mode == "production":
            available.pop("testing", None)
        return {"mode": self.mode, "provider": self.provider or None, "model": self.model or None,
                "configured": self.model in available.get(self.provider, []), "available": available,
                "testing_provider": self.provider == "testing"}
