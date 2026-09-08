"""Typed presentation contracts for concise release summaries."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReleaseBriefSource(str, Enum):
    AI = "ai"
    DETERMINISTIC = "deterministic"
    FALLBACK = "fallback"


class ReleaseBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source: ReleaseBriefSource
    headline: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=500)
    top_actions: list[str] = Field(default_factory=list, max_length=3)
    positive_note: str | None = Field(default=None, max_length=240)

    @field_validator("top_actions")
    @classmethod
    def bound_actions(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("release brief actions must contain 1 to 200 characters")
        return values


class ReleaseBriefDraft(BaseModel):
    """Provider draft; action identifiers are resolved by the backend."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    headline: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=500)
    top_action_codes: list[str] = Field(default_factory=list, max_length=3)
    positive_note: str | None = Field(default=None, max_length=240)

    @field_validator("summary")
    @classmethod
    def limit_paragraphs(cls, value: str) -> str:
        paragraphs = [part for part in value.split("\n\n") if part.strip()]
        if len(paragraphs) > 3:
            raise ValueError("AI review summary must contain at most three paragraphs")
        return value
