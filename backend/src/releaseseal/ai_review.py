"""Optional Gemini video-review boundary and validated observation contracts."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Generic, Mapping, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from releaseseal.config import AIReviewConfig


class AIObservationType(str, Enum):
    """Objective observation kinds allowed across the provider trust boundary."""

    VISIBLE_TEXT = "visible_text"
    VISUAL_CHANGE = "visual_change"
    PERSON_APPEARS = "person_appears"
    AUDIBLE_SPEECH = "audible_speech"
    AUDIBLE_TONE = "audible_tone"


class AIObservation(BaseModel):
    """One bounded, evidence-oriented observation returned by an AI provider."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    observation_type: AIObservationType
    summary: str = Field(min_length=1, max_length=160)
    explanation: str = Field(min_length=1, max_length=1000)
    evidence: list[str] = Field(default_factory=list, max_length=5)
    start_seconds: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    end_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    suggestion: str | None = Field(default=None, max_length=500)

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 300 for value in cleaned):
            raise ValueError("evidence items must contain 1 to 300 characters")
        return cleaned

    @model_validator(mode="after")
    def validate_timestamp_range(self) -> "AIObservation":
        if self.end_seconds is not None and self.start_seconds is None:
            raise ValueError("end_seconds requires start_seconds")
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds < self.start_seconds
        ):
            raise ValueError("end_seconds cannot be earlier than start_seconds")
        return self


class AIObservationBatch(BaseModel):
    """Native structured-output envelope supplied to Gemini."""

    model_config = ConfigDict(extra="forbid")

    observations: list[AIObservation] = Field(default_factory=list, max_length=10)


class AIReviewResult(BaseModel):
    """Typed provider result plus non-secret lifecycle measurements."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    observations: list[AIObservation]
    upload_seconds: float = Field(ge=0, allow_inf_nan=False)
    processing_seconds: float = Field(ge=0, allow_inf_nan=False)
    generation_seconds: float = Field(ge=0, allow_inf_nan=False)
    total_seconds: float = Field(ge=0, allow_inf_nan=False)
    cleanup_succeeded: bool


class VideoReviewer(Protocol):
    def review(
        self,
        media_path: str | Path,
        media_duration_seconds: float | None,
        config: AIReviewConfig,
    ) -> AIReviewResult: ...


class AIReviewError(Exception):
    """Safe application-level failure from the optional provider boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        unavailable: bool = False,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.unavailable = unavailable
        self.retryable = retryable


ClientFactory = Callable[[str, int], object]
StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


@dataclass(frozen=True)
class StructuredAIReviewResult(Generic[StructuredModel]):
    """Validated task output plus provider lifecycle measurements."""

    provider: str
    model: str
    output: StructuredModel
    upload_seconds: float
    processing_seconds: float
    generation_seconds: float
    total_seconds: float
    cleanup_succeeded: bool


@dataclass(frozen=True)
class ProviderCitation:
    """One URL supplied by provider grounding metadata, never model JSON."""

    title: str
    uri: str
    support_text: str | None = None


@dataclass(frozen=True)
class GroundedStructuredAIReviewResult(Generic[StructuredModel]):
    """Validated grounded output and provider-owned citation metadata."""

    output: StructuredModel
    citations: tuple[ProviderCitation, ...]
    generation_seconds: float


class GeminiReviewSession:
    """One bounded Gemini upload reused by task-specific structured reviews."""

    def __init__(
        self,
        adapter: "GeminiVideoReviewer",
        media_path: str | Path,
        config: AIReviewConfig,
        *,
        media_mime_type: str | None = None,
    ):
        self.adapter = adapter
        self.media_path = Path(media_path)
        self.config = config
        self.media_mime_type = media_mime_type
        self.client = None
        self.remote_file = None
        self.upload_seconds = 0.0
        self.processing_seconds = 0.0
        self.started_at: float | None = None
        self.cleanup_succeeded = False
        self.generation_count = 0

    def start(self) -> "GeminiReviewSession":
        api_key = self.adapter._environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise AIReviewError(
                "ai_api_key_missing",
                "Gemini review is enabled, but GEMINI_API_KEY is not configured on the server.",
                unavailable=True,
            )
        self.client = self.adapter._create_client(api_key, self.config.timeout_seconds)
        self.started_at = self.adapter._clock()
        try:
            upload_started = self.adapter._clock()
            if self.media_mime_type not in SUPPORTED_GEMINI_VIDEO_MIME_TYPES:
                raise AIReviewError(
                    "ai_media_unsupported",
                    "This video container is readable locally but is not supported for Full Review.",
                )
            self.remote_file = self.client.files.upload(
                file=str(self.media_path),
                config={
                    "mime_type": self.media_mime_type,
                    "display_name": self.media_path.name,
                },
            )
            self.upload_seconds = self.adapter._clock() - upload_started
            processing_started = self.adapter._clock()
            self.remote_file = self.adapter._wait_until_active(
                self.client, self.remote_file, self.config.timeout_seconds
            )
            self.processing_seconds = self.adapter._clock() - processing_started
            if not getattr(self.remote_file, "uri", None) or not getattr(self.remote_file, "mime_type", None):
                raise AIReviewError(
                    "ai_provider_response_invalid",
                    "Gemini did not return a usable uploaded-video reference.",
                )
        except AIReviewError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise _classify_provider_error(exc, phase="upload") from exc
        return self

    def generate_structured(
        self,
        *,
        prompt: str,
        response_model: type[StructuredModel],
        validate_output: Callable[[StructuredModel], StructuredModel] | None = None,
        image_path: str | Path | None = None,
        image_mime_type: str | None = None,
    ) -> StructuredAIReviewResult[StructuredModel]:
        if self.client is None or self.remote_file is None or self.started_at is None:
            raise AIReviewError("ai_session_not_started", "Gemini review session is not active.")
        generation_started = self.adapter._clock()
        try:
            contents: list[object] = [self.remote_file, prompt]
            if image_path is not None:
                if not image_mime_type:
                    raise AIReviewError(
                        "ai_image_input_invalid",
                        "Gemini image input is missing a validated media type.",
                    )
                types = _load_google_genai_types()
                contents.insert(
                    1,
                    types.Part.from_bytes(
                        data=Path(image_path).read_bytes(), mime_type=image_mime_type
                    ),
                )
            response = self.client.models.generate_content(
                model=self.config.model,
                contents=contents,
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": response_model.model_json_schema(),
                    "thinking_config": {"thinking_level": "LOW"},
                    "max_output_tokens": 2048,
                    "automatic_function_calling": {"disable": True},
                    "http_options": {
                        "timeout": max(1, round(self.config.timeout_seconds * 1000))
                    },
                },
            )
            generation_seconds = self.adapter._clock() - generation_started
            output = _validate_structured_output(getattr(response, "text", None), response_model)
            if validate_output is not None:
                output = validate_output(output)
            self.generation_count += 1
            return StructuredAIReviewResult(
                provider=self.config.provider,
                model=self.config.model,
                output=output,
                upload_seconds=self.upload_seconds,
                processing_seconds=self.processing_seconds,
                generation_seconds=generation_seconds,
                total_seconds=self.adapter._clock() - self.started_at,
                cleanup_succeeded=False,
            )
        except AIReviewError:
            raise
        except Exception as exc:
            raise _classify_provider_error(exc, phase="generation") from exc

    def generate_grounded_structured(
        self,
        *,
        prompt: str,
        response_model: type[StructuredModel],
        validate_output: Callable[[StructuredModel], StructuredModel] | None = None,
    ) -> GroundedStructuredAIReviewResult[StructuredModel]:
        """Run one text-only structured request grounded with Google Search."""

        if self.client is None or self.started_at is None:
            raise AIReviewError("ai_session_not_started", "Gemini review session is not active.")
        generation_started = self.adapter._clock()
        try:
            types = _load_google_genai_types()
            response = self.client.models.generate_content(
                model=self.config.model,
                contents=prompt,
                config={
                    "tools": [types.Tool(google_search=types.GoogleSearch())],
                    "response_mime_type": "application/json",
                    "response_json_schema": response_model.model_json_schema(),
                    "thinking_config": {"thinking_level": "LOW"},
                    "max_output_tokens": 3072,
                    "automatic_function_calling": {"disable": True},
                    "http_options": {
                        "timeout": max(1, round(self.config.timeout_seconds * 1000))
                    },
                },
            )
            generation_seconds = self.adapter._clock() - generation_started
            output = _validate_structured_output(getattr(response, "text", None), response_model)
            if validate_output is not None:
                output = validate_output(output)
            citations = _provider_citations(response)
            self.generation_count += 1
            return GroundedStructuredAIReviewResult(
                output=output,
                citations=citations,
                generation_seconds=generation_seconds,
            )
        except AIReviewError:
            raise
        except Exception as exc:
            raise _classify_provider_error(exc, phase="grounding") from exc

    def generate_text_structured(
        self,
        *,
        prompt: str,
        response_model: type[StructuredModel],
        validate_output: Callable[[StructuredModel], StructuredModel] | None = None,
    ) -> StructuredAIReviewResult[StructuredModel]:
        """Generate structured text without attaching the uploaded video again."""

        if self.client is None or self.started_at is None:
            raise AIReviewError("ai_session_not_started", "AI review session is not active.")
        generation_started = self.adapter._clock()
        try:
            response = self.client.models.generate_content(
                model=self.config.model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": response_model.model_json_schema(),
                    "thinking_config": {"thinking_level": "LOW"},
                    "max_output_tokens": 1536,
                    "automatic_function_calling": {"disable": True},
                    "http_options": {"timeout": max(1, round(self.config.timeout_seconds * 1000))},
                },
            )
            generation_seconds = self.adapter._clock() - generation_started
            output = _validate_structured_output(getattr(response, "text", None), response_model)
            if validate_output is not None:
                output = validate_output(output)
            self.generation_count += 1
            return StructuredAIReviewResult(
                provider=self.config.provider,
                model=self.config.model,
                output=output,
                upload_seconds=self.upload_seconds,
                processing_seconds=self.processing_seconds,
                generation_seconds=generation_seconds,
                total_seconds=self.adapter._clock() - self.started_at,
                cleanup_succeeded=False,
            )
        except AIReviewError:
            raise
        except Exception as exc:
            raise _classify_provider_error(exc, phase="generation") from exc

    def close(self) -> None:
        if self.client is None:
            return
        if self.remote_file is not None and getattr(self.remote_file, "name", None):
            try:
                self.client.files.delete(name=self.remote_file.name)
                self.cleanup_succeeded = True
            except Exception:
                self.cleanup_succeeded = False
        close = getattr(self.client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        self.client = None


class GeminiVideoReviewer:
    """Upload once, request native structured output, validate, then delete."""

    def __init__(
        self,
        *,
        client_factory: ClientFactory | None = None,
        environ: Mapping[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._client_factory = client_factory
        self._environ = environ if environ is not None else os.environ
        self._sleep = sleep
        self._clock = clock

    def review(
        self,
        media_path: str | Path,
        media_duration_seconds: float | None,
        config: AIReviewConfig,
    ) -> AIReviewResult:
        structured = self.review_structured(
            media_path,
            config=config,
            prompt=_smoke_prompt(config.maximum_observations),
            response_model=AIObservationBatch,
            validate_output=lambda batch: _validate_observation_batch(
                batch,
                media_duration_seconds=media_duration_seconds,
                config=config,
            ),
        )
        return AIReviewResult(
            provider=structured.provider,
            model=structured.model,
            observations=structured.output.observations,
            upload_seconds=structured.upload_seconds,
            processing_seconds=structured.processing_seconds,
            generation_seconds=structured.generation_seconds,
            total_seconds=structured.total_seconds,
            cleanup_succeeded=structured.cleanup_succeeded,
        )

    def review_structured(
        self,
        media_path: str | Path,
        *,
        config: AIReviewConfig,
        prompt: str,
        response_model: type[StructuredModel],
        validate_output: Callable[[StructuredModel], StructuredModel] | None = None,
        image_path: str | Path | None = None,
        image_mime_type: str | None = None,
    ) -> StructuredAIReviewResult[StructuredModel]:
        """Run one schema-constrained task through the proven upload lifecycle."""
        session = self.open_session(media_path, config)
        try:
            session.start()
            result = session.generate_structured(
                prompt=prompt,
                response_model=response_model,
                validate_output=validate_output,
                image_path=image_path,
                image_mime_type=image_mime_type,
            )
        finally:
            session.close()
        return replace(result, cleanup_succeeded=session.cleanup_succeeded)

    def open_session(
        self,
        media_path: str | Path,
        config: AIReviewConfig,
        *,
        media_mime_type: str | None = None,
    ) -> GeminiReviewSession:
        return GeminiReviewSession(
            self,
            media_path,
            config,
            media_mime_type=media_mime_type or _video_mime_from_suffix(media_path),
        )

    def _create_client(self, api_key: str, timeout_seconds: float):
        factory = self._client_factory
        if factory is None:
            try:
                genai = _load_google_genai()
            except ImportError as exc:
                raise AIReviewError(
                    "ai_dependency_unavailable",
                    "Gemini review requires the optional google-genai dependency.",
                    unavailable=True,
                ) from exc

            factory = lambda key, timeout_ms: genai.Client(
                api_key=key, http_options={"timeout": timeout_ms}
            )
        try:
            return factory(api_key, max(1, round(timeout_seconds * 1000)))
        except AIReviewError:
            raise
        except Exception as exc:
            raise AIReviewError(
                "ai_client_initialization_failed",
                "Gemini review could not initialize the provider client.",
                unavailable=True,
            ) from exc

    def _wait_until_active(self, client, remote_file, timeout_seconds: float):
        deadline = self._clock() + timeout_seconds
        while True:
            state = getattr(getattr(remote_file, "state", None), "name", None)
            if state == "ACTIVE":
                return remote_file
            if state == "FAILED":
                raise AIReviewError(
                    "ai_file_processing_failed",
                    "Gemini could not process the uploaded video.",
                )
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise AIReviewError(
                    "ai_file_processing_timeout",
                    "Gemini did not finish processing the uploaded video before the timeout.",
                )
            self._sleep(min(1.0, remaining))
            remote_file = client.files.get(name=remote_file.name)


def classify_provider_error(exc: Exception, *, phase: str) -> AIReviewError:
    """Expose the shared safe provider-error classifier to focused AI adapters."""

    return _classify_provider_error(exc, phase=phase)


def _smoke_prompt(maximum_observations: int) -> str:
    return (
        "Inspect the video itself and report at most "
        f"{maximum_observations} objective, directly observable events. Focus on visible "
        "on-screen text, clear visual state changes, a person appearing, clearly audible "
        "speech, or a clearly audible tone. Use seconds from the start of the video. "
        "Do not infer content from the filename and do not offer general editorial advice."
    )


def _validate_structured_output(
    output_text: object, response_model: type[StructuredModel]
) -> StructuredModel:
    if not isinstance(output_text, str) or not output_text.strip():
        raise AIReviewError(
            "ai_provider_response_invalid",
            "Gemini returned no structured review output.",
        )
    try:
        return response_model.model_validate_json(output_text)
    except ValidationError as exc:
        raise AIReviewError(
            "ai_provider_response_invalid",
            "Gemini returned output that did not match the required schema.",
        ) from exc


def _validate_observation_batch(
    batch: AIObservationBatch,
    *,
    media_duration_seconds: float | None,
    config: AIReviewConfig,
) -> AIObservationBatch:
    if len(batch.observations) > config.maximum_observations:
        raise AIReviewError(
            "ai_provider_response_invalid",
            "Gemini returned more observations than the configured limit.",
        )
    if media_duration_seconds is not None:
        maximum_timestamp = (
            media_duration_seconds + config.timestamp_tolerance_seconds
        )
        for observation in batch.observations:
            if (
                observation.start_seconds is not None
                and observation.start_seconds > maximum_timestamp
            ) or (
                observation.end_seconds is not None
                and observation.end_seconds > maximum_timestamp
            ):
                raise AIReviewError(
                    "ai_observation_timestamp_invalid",
                    "Gemini returned an observation outside the media duration.",
                )
    return batch


def _looks_like_timeout(exc: Exception) -> bool:
    return "timeout" in type(exc).__name__.lower()


def _looks_like_quota_error(exc: Exception) -> bool:
    message = str(exc).upper()
    return "429" in message or "RESOURCE_EXHAUSTED" in message or "RATE LIMIT" in message


SUPPORTED_GEMINI_VIDEO_MIME_TYPES = frozenset(
    {"video/mp4", "video/quicktime", "video/webm"}
)


def provider_video_mime_type(format_name: str | None, media_path: str | Path) -> str | None:
    """Map FFprobe-confirmed containers to a bounded Gemini upload MIME type."""

    formats = {part.strip().lower() for part in (format_name or "").split(",")}
    suffix = Path(media_path).suffix.lower()
    if suffix == ".mp4" and formats.intersection({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}):
        return "video/mp4"
    if suffix == ".mov" and "mov" in formats:
        return "video/quicktime"
    if suffix == ".webm" and formats.intersection({"webm", "matroska"}):
        return "video/webm"
    return None


def _video_mime_from_suffix(media_path: str | Path) -> str | None:
    return {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
    }.get(Path(media_path).suffix.lower())


def _classify_provider_error(exc: Exception, *, phase: str) -> AIReviewError:
    """Translate SDK/network failures into stable, safe application reasons."""

    if _looks_like_timeout(exc):
        return AIReviewError(
            "ai_provider_timeout",
            "Gemini did not respond before the Full Review timeout.",
            unavailable=True,
            retryable=True,
        )

    status_code = getattr(exc, "code", None)
    if isinstance(status_code, int):
        if status_code == 401:
            return AIReviewError(
                "ai_provider_authentication_failed",
                "Gemini rejected the configured server credential.",
                unavailable=True,
            )
        if status_code == 403:
            return AIReviewError(
                "ai_provider_permission_denied",
                "Gemini Full Review is not permitted for the configured server credential.",
                unavailable=True,
            )
        if status_code == 429:
            return AIReviewError(
                "ai_provider_quota_exhausted",
                "Gemini review is temporarily unavailable because the provider quota was reached.",
                unavailable=True,
                retryable=True,
            )
        if status_code >= 500:
            return AIReviewError(
                "ai_provider_unavailable",
                "Gemini is temporarily unavailable.",
                unavailable=True,
                retryable=True,
            )
        if status_code == 400 and _looks_like_unsupported_media(exc):
            return AIReviewError(
                "ai_media_unsupported",
                "Gemini could not process this video's media format for Full Review.",
            )

    if _looks_like_quota_error(exc):
        return AIReviewError(
            "ai_provider_quota_exhausted",
            "Gemini review is temporarily unavailable because the provider quota was reached.",
            unavailable=True,
            retryable=True,
        )
    error_name = type(exc).__name__.lower()
    if any(token in error_name for token in ("connect", "network", "transport")):
        return AIReviewError(
            "ai_provider_unavailable",
            "Gemini could not be reached from the backend.",
            unavailable=True,
            retryable=True,
        )
    code = {
        "upload": "ai_upload_failed",
        "generation": "ai_generation_failed",
        "grounding": "ai_grounding_failed",
    }[phase]
    message = {
        "upload": "Gemini upload could not be completed.",
        "generation": "Gemini generation could not be completed.",
        "grounding": "Gemini grounded verification could not be completed.",
    }[phase]
    return AIReviewError(code, message, retryable=phase != "upload")


def _looks_like_unsupported_media(exc: Exception) -> bool:
    message = str(exc).lower()[:1000]
    return any(
        phrase in message
        for phrase in ("unsupported mime", "unsupported media", "unsupported file", "media format")
    )


def _provider_citations(response: object) -> tuple[ProviderCitation, ...]:
    """Extract only HTTP(S) citations returned in grounding metadata."""

    candidates = getattr(response, "candidates", None) or []
    seen: set[str] = set()
    citations: list[ProviderCitation] = []
    for candidate in candidates:
        metadata = getattr(candidate, "grounding_metadata", None)
        chunks = getattr(metadata, "grounding_chunks", None) or []
        supports = getattr(metadata, "grounding_supports", None) or []
        support_text_by_index: dict[int, list[str]] = {}
        for support in supports:
            segment = getattr(support, "segment", None)
            support_text = getattr(segment, "text", None)
            if not isinstance(support_text, str) or not support_text.strip():
                continue
            for index in getattr(support, "grounding_chunk_indices", None) or []:
                if isinstance(index, int):
                    support_text_by_index.setdefault(index, []).append(support_text.strip())
        for index, chunk in enumerate(chunks):
            web = getattr(chunk, "web", None)
            uri = getattr(web, "uri", None)
            title = getattr(web, "title", None) or getattr(web, "domain", None)
            if not isinstance(uri, str) or not uri.startswith(("https://", "http://")):
                continue
            if uri in seen:
                continue
            seen.add(uri)
            citations.append(ProviderCitation(
                title=str(title or "Source")[:200], uri=uri[:2048],
                support_text=" ".join(support_text_by_index.get(index, []))[:1000] or None,
            ))
    return tuple(citations)


def _load_google_genai():
    from google import genai

    return genai


def _load_google_genai_types():
    from google.genai import types

    return types
