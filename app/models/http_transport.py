"""Bounded HTTPS transport for fixed adapter endpoints; no redirect or retry."""

import json
from urllib.request import build_opener, HTTPRedirectHandler, Request


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class JsonTransport:
    def post(self, url: str, headers: dict, payload: dict, timeout: int = 60) -> dict:
        request = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            body = response.read(1500001)
        if len(body) > 1500000:
            raise ValueError("provider_response_limit")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise ValueError("provider_response_invalid")
        return result


def wire_schema(value):
    """Translate optional validation keywords to a common provider subset.

    Canonical local validation remains mandatory and unchanged. Empty-array
    constraints and length bounds are repeated in instructions/local validation.
    """
    if isinstance(value, list):
        return [wire_schema(x) for x in value]
    if not isinstance(value, dict):
        return value
    result = {k: ({"type": "string"} if k == "items" and v is False else wire_schema(v)) for k, v in value.items() if k not in {
        "title", "default", "minLength", "maxLength", "minItems", "maxItems", "uniqueItems", "format",
    }}
    if "const" in result:
        result["enum"] = [result.pop("const")]
    return result
