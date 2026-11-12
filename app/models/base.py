"""Small, credential-free domain interface for optional model adapters."""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class GenerationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    provider: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    model: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.-]+$")
    # Legacy caller hint; cannot enable topics without deterministic scope.
    scope: Literal["unconfirmed", "within_workflow", "outside_workflow"] = "unconfirmed"


@dataclass(frozen=True)
class ModelRequest:
    provider: str
    model: str
    instruction_version: str
    instructions: str
    grounded_package: dict[str, Any]
    response_schema: dict[str, Any]
    limits: dict[str, int]
    metadata: dict[str, str]


@dataclass(frozen=True)
class ModelResponse:
    provider: str
    model: str
    success: bool
    output: Any = None
    error_code: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    # Adapter-private diagnostics are never copied into public service results.
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelProvider(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse: ...
