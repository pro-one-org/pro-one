"""Strict untrusted-output structure; contextual IDs are checked separately."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictDraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GeneratedSection(StrictDraftModel):
    section_id: str = Field(min_length=1, max_length=120)
    kind: Literal["legal_information", "control", "user_fact"]
    text: str = Field(min_length=1, max_length=6000)
    claim_ids: list[str] = Field(max_length=30)
    citation_ids: list[str] = Field(max_length=30)
    user_fact_ids: list[str] = Field(max_length=30)
    actions: list[str] = Field(max_length=20)
    conclusions: list[str] = Field(max_length=20)


class GeneratedDraft(StrictDraftModel):
    workflow_id: str = Field(min_length=1, max_length=120)
    sections: list[GeneratedSection] = Field(min_length=1, max_length=30)
    citations_used: list[str] = Field(max_length=50)
    disclosures_included: list[str] = Field(max_length=50)
    limitations_included: list[str] = Field(max_length=100)
