"""Typed contracts for deterministic finished-media revision maps."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RevisionSegmentKind(str, Enum):
    UNCHANGED = "UNCHANGED"
    REMOVED = "REMOVED"
    INSERTED = "INSERTED"
    CHANGED = "CHANGED"


class RevisionStreamSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    video_codec: str | None = None
    has_audio: bool
    audio_codec: str | None = None


class RevisionSamplingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visual_samples_per_second: float = Field(gt=0)
    maximum_visual_samples: int = Field(gt=0, le=1800)
    descriptor_width: int = Field(gt=0)
    descriptor_height: int = Field(gt=0)
    audio_sample_rate: int = Field(gt=0)
    refinement_samples_per_second: float = Field(gt=0)
    maximum_refinement_samples: int = Field(gt=0)


class RevisionSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(pattern=r"^segment-\d{4}$")
    kind: RevisionSegmentKind
    previous_start_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    previous_end_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    revised_start_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    revised_end_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    visual_distance: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    audio_distance: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    visual_changed: bool
    audio_changed: bool
    match_confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    boundary_confidence: Literal["high", "approximate", "ambiguous"]

    @model_validator(mode="after")
    def validate_timeline_presence(self) -> "RevisionSegment":
        previous = self.previous_start_seconds is not None and self.previous_end_seconds is not None
        revised = self.revised_start_seconds is not None and self.revised_end_seconds is not None
        if (self.previous_start_seconds is None) != (self.previous_end_seconds is None):
            raise ValueError("previous segment requires both bounds")
        if (self.revised_start_seconds is None) != (self.revised_end_seconds is None):
            raise ValueError("revised segment requires both bounds")
        if previous and self.previous_end_seconds <= self.previous_start_seconds:
            raise ValueError("previous segment must have positive duration")
        if revised and self.revised_end_seconds <= self.revised_start_seconds:
            raise ValueError("revised segment must have positive duration")
        expected = {
            RevisionSegmentKind.UNCHANGED: (True, True),
            RevisionSegmentKind.CHANGED: (True, True),
            RevisionSegmentKind.REMOVED: (True, False),
            RevisionSegmentKind.INSERTED: (False, True),
        }[self.kind]
        if (previous, revised) != expected:
            raise ValueError("segment timeline presence does not match its kind")
        if self.kind is RevisionSegmentKind.CHANGED and not (self.visual_changed or self.audio_changed):
            raise ValueError("changed segment requires visual or audio evidence")
        return self


class RevisionMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    previous_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    revised_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_duration_seconds: float = Field(gt=0, allow_inf_nan=False)
    revised_duration_seconds: float = Field(gt=0, allow_inf_nan=False)
    previous_streams: RevisionStreamSummary
    revised_streams: RevisionStreamSummary
    sampling_policy: RevisionSamplingPolicy
    previous_sample_count: int = Field(ge=0, le=1800)
    revised_sample_count: int = Field(ge=0, le=1800)
    estimated_unchanged_duration_seconds: float = Field(ge=0, allow_inf_nan=False)
    unchanged_ratio: float = Field(ge=0, le=1, allow_inf_nan=False)
    unchanged_ratio_basis: Literal["previous_duration"] = "previous_duration"
    segments: list[RevisionSegment] = Field(max_length=4000)
    ambiguity_notes: list[str] = Field(default_factory=list, max_length=20)
    analysis_runtime_seconds: float = Field(ge=0, allow_inf_nan=False)
    identical_file_fast_path: bool = False

    @model_validator(mode="after")
    def validate_ordered_bounded_segments(self) -> "RevisionMap":
        if self.estimated_unchanged_duration_seconds > self.previous_duration_seconds + 0.01:
            raise ValueError("unchanged duration exceeds previous duration")
        prior_previous = 0.0
        prior_revised = 0.0
        for segment in self.segments:
            if segment.previous_start_seconds is not None:
                if segment.previous_start_seconds + 0.01 < prior_previous:
                    raise ValueError("previous timeline segments are not ordered")
                if segment.previous_end_seconds > self.previous_duration_seconds + 0.01:
                    raise ValueError("previous segment exceeds media duration")
                prior_previous = segment.previous_end_seconds
            if segment.revised_start_seconds is not None:
                if segment.revised_start_seconds + 0.01 < prior_revised:
                    raise ValueError("revised timeline segments are not ordered")
                if segment.revised_end_seconds > self.revised_duration_seconds + 0.01:
                    raise ValueError("revised segment exceeds media duration")
                prior_revised = segment.revised_end_seconds
        return self
