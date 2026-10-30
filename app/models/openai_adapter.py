"""OpenAI Responses API adapter. Vendor wire details stay in this module."""

import json

from app.models.base import ModelRequest, ModelResponse
from app.models.http_transport import JsonTransport, wire_schema


class OpenAIProvider:
    def __init__(self, api_key: str | None, transport=None) -> None:
        self._key = api_key
        self.transport = transport or JsonTransport()

    def generate(self, request: ModelRequest) -> ModelResponse:
        if not self._key:
            return ModelResponse(request.provider, request.model, False, error_code="provider_unavailable")
        try:
            result = self.transport.post("https://api.openai.com/v1/responses", {"Authorization": "Bearer " + self._key}, {
                "model": request.model, "store": False, "max_output_tokens": request.limits["max_output_tokens"],
                "input": [{"role": "system", "content": request.instructions},
                          {"role": "user", "content": json.dumps(request.grounded_package)}],
                "text": {"format": {"type": "json_schema", "name": "pro_one_draft", "strict": True, "schema": wire_schema(request.response_schema)}},
            })
            if result.get("status") != "completed":
                raise ValueError("incomplete")
            content = [c for o in result.get("output", []) if o.get("type") == "message" for c in o.get("content", [])]
            if not content or any(c.get("type") != "output_text" for c in content):
                raise ValueError("refused_or_unexpected")
            return ModelResponse(request.provider, request.model, True, output="".join(c["text"] for c in content), usage=result.get("usage", {}))
        except Exception:
            return ModelResponse(request.provider, request.model, False, error_code="provider_error")
