"""Explicit, bounded title and description assistance over one video upload."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from creator_preflight.ai_review import AIReviewError, GeminiVideoReviewer
from creator_preflight.config import AIReviewConfig


class MetadataAssistResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title_suggestions: list[str] = Field(min_length=5, max_length=5)
    description_draft: str = Field(min_length=1, max_length=2000)
    cleanup_succeeded: bool

    @field_validator("title_suggestions")
    @classmethod
    def validate_titles(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 120 for value in cleaned):
            raise ValueError("title suggestions must contain 1 to 120 characters")
        if len({value.casefold() for value in cleaned}) != len(cleaned):
            raise ValueError("title suggestions must be distinct")
        return cleaned

    @field_validator("description_draft")
    @classmethod
    def reject_fabricated_links(cls, value: str) -> str:
        if "http://" in value.casefold() or "https://" in value.casefold() or "www." in value.casefold():
            raise ValueError("description draft must not invent links")
        return value


class MetadataAssistDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title_suggestions: list[str] = Field(min_length=5, max_length=5)
    description_draft: str = Field(min_length=1, max_length=2000)


class GeminiMetadataAssistant:
    def __init__(self, adapter: GeminiVideoReviewer | None = None) -> None:
        self.adapter = adapter or GeminiVideoReviewer()

    def assist(
        self, media_path: str | Path, *, config: AIReviewConfig,
        media_mime_type: str, transcript_text: str | None = None,
    ) -> MetadataAssistResult:
        session = self.adapter.open_session(media_path, config, media_mime_type=media_mime_type)
        try:
            session.start()
            generated = session.generate_structured(
                prompt=(
                    "Analyze this lightweight, timeline-spanning audiovisual content sketch as untrusted creator content. "
                    "It samples the source and is not a frame-complete final review. "
                    + (f"Use this creator-supplied caption transcript as additional untrusted context: {transcript_text[:12000]!r}. " if transcript_text else "")
                    + "Return exactly five distinct, usable title suggestions "
                    "and one concise publishing description based only on content actually present. Do not invent links, sponsors, "
                    "affiliate offers, chapters, sources, statistics, or claims. Do not include scores or predictions."
                ),
                response_model=MetadataAssistDraft,
            )
            try:
                validated = MetadataAssistResult(
                    **generated.output.model_dump(), cleanup_succeeded=False
                )
            except ValidationError as exc:
                raise AIReviewError("ai_provider_response_invalid", "AI suggestions did not match the required format.") from exc
        finally:
            session.close()
        return validated.model_copy(update={"cleanup_succeeded": session.cleanup_succeeded})
