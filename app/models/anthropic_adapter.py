"""Anthropic Messages API adapter; no model tools or autonomous retrieval."""

import json

from app.models.base import ModelRequest, ModelResponse
from app.models.http_transport import JsonTransport, wire_schema


class AnthropicProvider:
    def __init__(self, api_key: str | None, transport=None) -> None:
        self._key = api_key
        self.transport = transport or JsonTransport()

    def generate(self, request: ModelRequest) -> ModelResponse:
        if not self._key:
            return ModelResponse(request.provider, request.model, False, error_code="provider_unavailable")
        try:
            result = self.transport.post("https://api.anthropic.com/v1/messages", {
                "x-api-key": self._key, "anthropic-version": "2023-06-01",
            }, {"model": request.model, "max_tokens": request.limits["max_output_tokens"],
                "system": request.instructions,
                "messages": [{"role": "user", "content": json.dumps(request.grounded_package)}],
                "output_config": {"format": {"type": "json_schema", "schema": wire_schema(request.response_schema)}},
            })
            content = result.get("content", [])
            if result.get("stop_reason") != "end_turn" or not content or any(c.get("type") != "text" for c in content):
                raise ValueError("refused_or_incomplete")
            return ModelResponse(request.provider, request.model, True, output="".join(c["text"] for c in content), usage=result.get("usage", {}))
        except Exception:
            return ModelResponse(request.provider, request.model, False, error_code="provider_error")
