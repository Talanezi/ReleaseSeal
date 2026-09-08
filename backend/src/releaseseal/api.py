"""Thin, bounded FastAPI adapters for inspection and unified scanning."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from threading import Lock
from time import perf_counter

import anyio
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from starlette.background import BackgroundTask

from releaseseal.config import ConfigurationError, PreflightConfig, load_config
from releaseseal.content_sketch import build_content_sketch
from releaseseal.captions import inspect_caption_file
from releaseseal.ai_review import AIReviewError, provider_video_mime_type
from releaseseal.detectors import DetectorExecutionError
from releaseseal.engine import PreflightScanner
from releaseseal.generated_captions import (
    GeneratedCaptionDraft,
    build_generated_caption_draft,
    unavailable_generated_caption_draft,
    verified_reusable_segments,
)
from releaseseal.media import MediaInspectionError, MediaInspector, check_media_tools
from releaseseal.metadata_assist import GeminiMetadataAssistant, MetadataAssistResult
from releaseseal.models import (
    CapabilityReason,
    ErrorResponse,
    MediaInspection,
    PreflightCapabilities,
    PreflightReport,
    PublishingPackage,
    ReviewMode,
)
from releaseseal.progress import ScanProgress, ScanProgressStage, ScanProgressStore
from releaseseal.repair_models import RepairOperation, RepairOperationBatch
from releaseseal.release_contract import MAX_BRIEF_CHARACTERS, ReleaseContract
from releaseseal.release_contract_extraction import GeminiReleaseContractExtractor
from releaseseal.release_evidence import (
    confirm_machine_candidate,
    file_sha256,
    recover_machine_evidence,
    unavailable_evidence_state,
)
from releaseseal.release_report_updates import with_contract_evidence
from releaseseal.release_receipt import (
    FinalExportReceipt,
    HumanDispositionRecord,
    RevisionReceipt,
    build_final_export_receipt,
    build_revision_receipt,
)
from releaseseal.repairs import FFmpegRepairEngine, RepairError
from releaseseal.revision import RevisionMapError, RevisionMapper
from releaseseal.revision_check import RevisionCheckError, RevisionCheckService
from releaseseal.revision_check_models import RevisionCheckReport
from releaseseal.revision_semantic import (
    GeminiRevisionSemanticReviewer,
    RevisionSemanticReviewError,
    RevisionSemanticReviewService,
)
from releaseseal.revision_semantic_models import RevisionSemanticReviewReport
from releaseseal.thumbnails import ThumbnailValidationError
from releaseseal.transcription import TranscriptionUnavailableError, WhisperTranscriber
from releaseseal.verification import transform_caption_file, verify_repair
from releaseseal.verification_models import ReviewReelManifest, VerificationReport

def _load_runtime_config() -> tuple[PreflightConfig, str]:
    config_path = os.environ.get("RELEASESEAL_CONFIG", "").strip()
    return ((load_config(config_path), config_path) if config_path else (PreflightConfig(), "typed defaults"))


_startup_config, _ = _load_runtime_config()
app = FastAPI(title="ReleaseSeal", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_startup_config.api.allowed_browser_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Content-Type"],
    expose_headers=[
        "Content-Disposition",
        "X-Repair-Original-Duration",
        "X-Repair-Output-Duration",
        "X-Repair-Removed-Duration",
    ],
)
_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
_MAX_RELEASE_CONTRACT_JSON_CHARACTERS = 100_000
_MAX_GENERATED_CAPTIONS_JSON_CHARACTERS = 600_000


class UploadLimitError(Exception):
    def __init__(self, maximum_bytes: int):
        self.maximum_bytes = maximum_bytes
        self.message = f"Video exceeds the configured {maximum_bytes}-byte upload limit."


class ScanBusyError(Exception):
    message = "ReleaseSeal is already running the maximum number of scans."


class RequestOriginError(Exception):
    message = "This browser origin is not allowed to start a scan."


class ReviewModeError(Exception):
    message = "Review mode must be either 'full' or 'local'."


class ReleaseContractInputError(Exception):
    message = "The release contract could not be validated."


class ReleaseReceiptInputError(Exception):
    message = "The release receipt inputs could not be validated."


class AudioEvidenceInputError(Exception):
    message = "The local audio evidence request could not be validated."


class _ProcessScanCapacity:
    def __init__(self) -> None:
        self._lock = Lock()
        self._active = 0

    def acquire(self, limit: int) -> bool:
        with self._lock:
            if self._active >= limit:
                return False
            self._active += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)


_scan_capacity = _ProcessScanCapacity()
_scan_progress = ScanProgressStore()


def _error_response(status_code: int, code: str, message: str, details=None) -> JSONResponse:
    body = ErrorResponse(error={"code": code, "message": message, "details": details})
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


@app.exception_handler(MediaInspectionError)
async def media_inspection_error_handler(request: Request, exc: MediaInspectionError) -> JSONResponse:
    del request
    status_code = {
        "file_not_found": 404,
        "media_tool_unavailable": 503,
        "ffprobe_execution_failed": 503,
        "ffprobe_timeout": 504,
    }.get(exc.code, 400)
    return _error_response(status_code, exc.code, exc.message, exc.details)


@app.exception_handler(DetectorExecutionError)
async def detector_error_handler(request: Request, exc: DetectorExecutionError) -> JSONResponse:
    del request
    status_code = {"media_tool_unavailable": 503, "detector_timeout": 504}.get(exc.code, 500)
    return _error_response(status_code, exc.code, exc.message, exc.details)


@app.exception_handler(ConfigurationError)
async def configuration_error_handler(request: Request, exc: ConfigurationError) -> JSONResponse:
    del request
    return _error_response(500, "configuration_invalid", exc.message, {"errors": exc.errors} if exc.errors else None)


@app.exception_handler(ThumbnailValidationError)
async def thumbnail_validation_error_handler(request: Request, exc: ThumbnailValidationError) -> JSONResponse:
    del request
    return _error_response(400, exc.code, exc.message)


@app.exception_handler(UploadLimitError)
async def upload_limit_error_handler(request: Request, exc: UploadLimitError) -> JSONResponse:
    del request
    return _error_response(413, "video_upload_too_large", exc.message, {"maximum_bytes": exc.maximum_bytes})


@app.exception_handler(ScanBusyError)
async def scan_busy_error_handler(request: Request, exc: ScanBusyError) -> JSONResponse:
    del request
    return _error_response(503, "scan_capacity_reached", exc.message)


@app.exception_handler(RequestOriginError)
async def origin_error_handler(request: Request, exc: RequestOriginError) -> JSONResponse:
    del request
    return _error_response(403, "request_origin_not_allowed", exc.message)


@app.exception_handler(ReviewModeError)
async def review_mode_error_handler(request: Request, exc: ReviewModeError) -> JSONResponse:
    del request
    return _error_response(400, "review_mode_invalid", exc.message)


@app.exception_handler(ReleaseContractInputError)
async def release_contract_input_error_handler(request: Request, exc: ReleaseContractInputError) -> JSONResponse:
    del request
    return _error_response(400, "release_contract_invalid", exc.message)


@app.exception_handler(ReleaseReceiptInputError)
async def release_receipt_input_error_handler(request: Request, exc: ReleaseReceiptInputError) -> JSONResponse:
    del request
    return _error_response(400, "release_receipt_invalid", exc.message)


@app.exception_handler(AudioEvidenceInputError)
async def audio_evidence_input_error_handler(request: Request, exc: AudioEvidenceInputError) -> JSONResponse:
    del request
    return _error_response(400, "audio_evidence_invalid", exc.message)


@app.exception_handler(RepairError)
async def repair_error_handler(request: Request, exc: RepairError) -> JSONResponse:
    del request
    status_code = {
        "repair_encoder_unavailable": 503,
        "repair_render_unavailable": 503,
        "repair_render_timeout": 504,
    }.get(exc.code, 400)
    return _error_response(status_code, exc.code, exc.message, exc.details)


@app.exception_handler(AIReviewError)
async def ai_review_error_handler(request: Request, exc: AIReviewError) -> JSONResponse:
    del request
    status_code = 429 if exc.code == "ai_provider_quota_exhausted" else 504 if "timeout" in exc.code else 503
    return _error_response(status_code, exc.code, exc.message)


@app.exception_handler(RevisionMapError)
async def revision_map_error_handler(request: Request, exc: RevisionMapError) -> JSONResponse:
    del request
    status_code = 504 if "timeout" in exc.code else 503 if "unavailable" in exc.code else 400
    return _error_response(status_code, exc.code, exc.message)


@app.exception_handler(RevisionCheckError)
async def revision_check_error_handler(request: Request, exc: RevisionCheckError) -> JSONResponse:
    del request
    return _error_response(400, exc.code, exc.message)


@app.exception_handler(RevisionSemanticReviewError)
async def revision_semantic_error_handler(request: Request, exc: RevisionSemanticReviewError) -> JSONResponse:
    del request
    status_code = 409 if exc.code == "revision_source_mismatch" else 400
    return _error_response(status_code, exc.code, exc.message)


@app.get("/api/v1/capabilities", response_model=PreflightCapabilities)
async def capabilities() -> PreflightCapabilities:
    config, _ = _api_config()
    tools = check_media_tools()
    gemini_dependency = _module_available("google.genai")
    gemini_key = bool(os.environ.get("GEMINI_API_KEY", "").strip())
    reasons: list[CapabilityReason] = []
    if not tools.ffprobe_available or not tools.ffmpeg_available:
        reasons.append(CapabilityReason(code="media_tools_unavailable", message="FFmpeg and FFprobe are required to scan local video."))
    if not gemini_dependency:
        reasons.append(CapabilityReason(code="gemini_dependency_unavailable", message="The optional Gemini backend dependency is not installed."))
    if not gemini_key:
        reasons.append(CapabilityReason(code="gemini_api_key_missing", message="The backend does not have a Gemini API key configured."))
    local_available = tools.ffprobe_available and tools.ffmpeg_available
    return PreflightCapabilities(
        ffprobe_available=tools.ffprobe_available,
        ffmpeg_available=tools.ffmpeg_available,
        gemini_dependency_available=gemini_dependency,
        gemini_api_key_configured=gemini_key,
        full_review_available=local_available and gemini_dependency and gemini_key,
        metadata_assist_available=local_available and gemini_dependency and gemini_key and config.ai_review.metadata_assist.enabled,
        release_contract_extraction_available=gemini_dependency and gemini_key,
        local_checks_available=local_available,
        revision_check_available=local_available,
        revision_semantic_review_available=(
            local_available
            and gemini_dependency
            and gemini_key
            and config.revision_semantic_review.enabled
        ),
        transcription_dependency_available=_module_available("faster_whisper"),
        transcription_enabled=config.transcription.enabled,
        local_evidence_recovery_available=(
            local_available
            and config.transcription.evidence_recovery_enabled
            and _module_available("faster_whisper")
        ),
        local_caption_generation_available=(
            local_available
            and config.transcription.local_files_only
            and _module_available("faster_whisper")
        ),
        supported_review_modes=[ReviewMode.FULL, ReviewMode.LOCAL],
        maximum_video_upload_size_bytes=config.api.maximum_video_upload_size_bytes,
        full_review_unavailable_reasons=reasons,
    )


@app.post("/api/v1/release-contracts/extract", response_model=ReleaseContract)
async def extract_release_contract(request: Request, brief: str = Form(...)) -> ReleaseContract:
    """Structure an explicitly supplied brief; evaluation remains backend-owned."""

    config, _ = _api_config()
    _require_allowed_origin(request, config)
    if not brief.strip() or len(brief) > MAX_BRIEF_CHARACTERS:
        raise ReleaseContractInputError()
    if not _scan_capacity.acquire(config.api.maximum_concurrent_scans):
        raise ScanBusyError()
    try:
        return await anyio.to_thread.run_sync(
            partial(GeminiReleaseContractExtractor().extract, brief, config.ai_review)
        )
    finally:
        _scan_capacity.release()


@app.post("/api/v1/release-contracts/recover-audio-evidence", response_model=PreflightReport)
async def recover_release_audio_evidence(
    request: Request,
    file: UploadFile = File(...),
    report_json: str = Form(...),
    generated_captions_json: str | None = Form(default=None),
) -> PreflightReport:
    """Recover advisory candidates from local ASR without changing contract truth silently."""

    config, _ = _api_config()
    try:
        _require_allowed_origin(request, config)
    except RequestOriginError:
        await file.close()
        raise
    try:
        report = PreflightReport.model_validate_json(report_json)
    except (ValidationError, ValueError, TypeError) as exc:
        await file.close()
        raise AudioEvidenceInputError() from exc
    if not _scan_capacity.acquire(config.api.maximum_concurrent_scans):
        await file.close()
        raise ScanBusyError()
    started = perf_counter()
    try:
        with TemporaryDirectory(prefix="releaseseal-evidence-") as temporary_directory:
            path = _media_temp_path(temporary_directory, file.filename)
            await _copy_upload(file, path, config.api.maximum_video_upload_size_bytes)
            if path.stat().st_size != report.media.file_size_bytes:
                raise AudioEvidenceInputError()
            artifact_sha = await anyio.to_thread.run_sync(partial(file_sha256, path))
            if not config.transcription.evidence_recovery_enabled or not report.media.has_audio:
                state = unavailable_evidence_state(
                    artifact_sha256=artifact_sha,
                    code="audio_evidence_unavailable",
                    message="Local audio evidence recovery is unavailable for this artifact.",
                    runtime_seconds=perf_counter() - started,
                )
                return with_contract_evidence(report, evaluation=report.release_contract, audio_evidence=state)
            if (
                report.media.duration_seconds is not None
                and report.media.duration_seconds > config.transcription.maximum_evidence_duration_seconds
            ):
                state = unavailable_evidence_state(
                    artifact_sha256=artifact_sha,
                    code="audio_evidence_duration_limit",
                    message="This video exceeds the configured local evidence-recovery duration limit.",
                    runtime_seconds=perf_counter() - started,
                )
                return with_contract_evidence(report, evaluation=report.release_contract, audio_evidence=state)
            try:
                if generated_captions_json:
                    if len(generated_captions_json) > _MAX_GENERATED_CAPTIONS_JSON_CHARACTERS:
                        raise AudioEvidenceInputError()
                    draft = GeneratedCaptionDraft.model_validate_json(generated_captions_json)
                    segments = verified_reusable_segments(
                        draft, artifact_sha256=artifact_sha, expected_model=config.transcription.model
                    )
                else:
                    segments = await anyio.to_thread.run_sync(
                        partial(WhisperTranscriber().transcribe, path, config.transcription)
                    )
            except (ValidationError, ValueError) as exc:
                raise AudioEvidenceInputError() from exc
            except TranscriptionUnavailableError as exc:
                state = unavailable_evidence_state(
                    artifact_sha256=artifact_sha,
                    code=exc.code,
                    message=exc.message,
                    runtime_seconds=perf_counter() - started,
                )
                return with_contract_evidence(report, evaluation=report.release_contract, audio_evidence=state)
            state, evaluation = recover_machine_evidence(
                artifact_path=path,
                artifact_sha256=artifact_sha,
                contract=report.release_contract.contract,
                current_evaluation=report.release_contract,
                segments=segments,
                model=config.transcription.model,
                maximum_candidates_per_requirement=config.transcription.maximum_evidence_candidates_per_requirement,
                maximum_transcript_characters=config.transcription.maximum_evidence_transcript_characters,
                started_at=started,
            )
            return with_contract_evidence(report, evaluation=evaluation, audio_evidence=state)
    finally:
        _scan_capacity.release()
        await file.close()


@app.post("/api/v1/captions/generate", response_model=GeneratedCaptionDraft)
async def generate_local_captions(
    request: Request,
    file: UploadFile = File(...),
) -> GeneratedCaptionDraft:
    """Create a bounded machine-generated SRT draft without changing scan truth."""

    config, _ = _api_config()
    try:
        _require_allowed_origin(request, config)
    except RequestOriginError:
        await file.close()
        raise
    if not _scan_capacity.acquire(config.api.maximum_concurrent_scans):
        await file.close()
        raise ScanBusyError()
    started = perf_counter()
    try:
        with TemporaryDirectory(prefix="releaseseal-captions-") as temporary_directory:
            path = _media_temp_path(temporary_directory, file.filename)
            await _copy_upload(file, path, config.api.maximum_video_upload_size_bytes)
            media = await anyio.to_thread.run_sync(MediaInspector().inspect, path)
            if not media.has_audio:
                return unavailable_generated_caption_draft(
                    artifact_path=path,
                    original_filename=file.filename,
                    model=config.transcription.model,
                    reason="This video has no audio track to caption.",
                    started_at=started,
                )
            if not config.transcription.local_files_only:
                return unavailable_generated_caption_draft(
                    artifact_path=path,
                    original_filename=file.filename,
                    model=config.transcription.model,
                    reason="Local caption generation requires a model already present on this device.",
                    started_at=started,
                )
            if (
                media.duration_seconds is not None
                and media.duration_seconds > config.transcription.maximum_evidence_duration_seconds
            ):
                return unavailable_generated_caption_draft(
                    artifact_path=path,
                    original_filename=file.filename,
                    model=config.transcription.model,
                    reason="This video exceeds the configured local caption-generation duration limit.",
                    started_at=started,
                )
            try:
                segments = await anyio.to_thread.run_sync(
                    partial(WhisperTranscriber().transcribe, path, config.transcription)
                )
            except TranscriptionUnavailableError:
                return unavailable_generated_caption_draft(
                    artifact_path=path,
                    original_filename=file.filename,
                    model=config.transcription.model,
                    reason="Local caption model unavailable.",
                    started_at=started,
                )
            return await anyio.to_thread.run_sync(partial(
                build_generated_caption_draft,
                artifact_path=path,
                original_filename=file.filename,
                segments=segments,
                model=config.transcription.model,
                maximum_cues=config.transcription.maximum_generated_caption_cues,
                maximum_characters=config.transcription.maximum_generated_caption_characters,
                started_at=started,
            ))
    finally:
        _scan_capacity.release()
        await file.close()


@app.post("/api/v1/release-contracts/confirm-audio-evidence", response_model=PreflightReport)
async def confirm_release_audio_evidence(
    request: Request,
    file: UploadFile = File(...),
    report_json: str = Form(...),
    candidate_id: str = Form(...),
) -> PreflightReport:
    """Confirm one exact bounded proposition and reevaluate only its requirement."""

    config, _ = _api_config()
    try:
        _require_allowed_origin(request, config)
    except RequestOriginError:
        await file.close()
        raise
    try:
        report = PreflightReport.model_validate_json(report_json)
    except (ValidationError, ValueError, TypeError) as exc:
        await file.close()
        raise AudioEvidenceInputError() from exc
    if not _scan_capacity.acquire(config.api.maximum_concurrent_scans):
        await file.close()
        raise ScanBusyError()
    try:
        with TemporaryDirectory(prefix="releaseseal-confirm-evidence-") as temporary_directory:
            path = _media_temp_path(temporary_directory, file.filename)
            await _copy_upload(file, path, config.api.maximum_video_upload_size_bytes)
            if path.stat().st_size != report.media.file_size_bytes:
                raise AudioEvidenceInputError()
            artifact_sha = await anyio.to_thread.run_sync(partial(file_sha256, path))
            try:
                state, evaluation = confirm_machine_candidate(
                    evaluation=report.release_contract,
                    state=report.audio_evidence,
                    candidate_id=candidate_id,
                    artifact_sha256=artifact_sha,
                )
            except ValueError as exc:
                raise AudioEvidenceInputError() from exc
            return with_contract_evidence(report, evaluation=evaluation, audio_evidence=state)
    finally:
        _scan_capacity.release()
        await file.close()


@app.post("/api/v1/release-receipts/final-export", response_model=FinalExportReceipt)
async def create_final_export_receipt(
    request: Request,
    file: UploadFile = File(...),
    report_json: str = Form(...),
    title: str = Form(default=""),
    description: str = Form(default=""),
    captions: UploadFile | None = File(default=None),
    thumbnail: UploadFile | None = File(default=None),
    repaired_file: UploadFile | None = File(default=None),
    operations_json: str | None = Form(default=None),
    verification_json: str | None = Form(default=None),
    human_dispositions_json: str = Form(default="[]"),
) -> FinalExportReceipt:
    """Bind a trusted Final Export result to the exact supplied package bytes."""

    config, _ = _api_config()
    uploads = (file, captions, thumbnail, repaired_file)
    try:
        _require_allowed_origin(request, config)
        report = PreflightReport.model_validate_json(report_json)
        receipt_config = _effective_web_config(config, report.review_mode)
        dispositions = [
            HumanDispositionRecord.model_validate(item)
            for item in json.loads(human_dispositions_json)
        ]
        repaired_requested = repaired_file is not None
        if repaired_requested:
            if not operations_json or not verification_json:
                raise ValueError("repaired receipt inputs are incomplete")
            operations = RepairOperationBatch.model_validate_json(operations_json).operations
            verification = VerificationReport.model_validate_json(verification_json)
        else:
            if operations_json or verification_json:
                raise ValueError("repair state was supplied without a repaired artifact")
            operations = None
            verification = None
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
        for upload in uploads:
            if upload is not None:
                await upload.close()
        raise ReleaseReceiptInputError() from exc
    if not _scan_capacity.acquire(config.api.maximum_concurrent_scans):
        for upload in uploads:
            if upload is not None:
                await upload.close()
        raise ScanBusyError()
    try:
        with TemporaryDirectory(prefix="releaseseal-receipt-") as temporary_directory:
            directory = Path(temporary_directory)
            original_path = _media_temp_path(temporary_directory, file.filename, stem="original")
            await _copy_upload(file, original_path, config.api.maximum_video_upload_size_bytes)
            repaired_path = None
            if repaired_file is not None:
                repaired_path = _media_temp_path(temporary_directory, repaired_file.filename, stem="repaired")
                await _copy_upload(repaired_file, repaired_path, config.api.maximum_video_upload_size_bytes)
            caption_path = await _copy_optional_bounded(captions, directory / "captions.receipt", config.rules.captions.maximum_file_size_bytes + 1)
            thumbnail_path = await _copy_optional_bounded(thumbnail, directory / "thumbnail.receipt", config.ai_review.promise_check.maximum_thumbnail_file_size_bytes + 1)
            return await anyio.to_thread.run_sync(partial(
                build_final_export_receipt,
                shipping_video_path=repaired_path or original_path,
                original_video_path=original_path if repaired_path else None,
                report=report,
                config=receipt_config,
                title=title,
                description=description,
                thumbnail_path=thumbnail_path,
                captions_path=caption_path,
                operations=operations,
                verification=verification,
                human_dispositions=dispositions,
            ))
    except (ValidationError, ValueError, TypeError) as exc:
        raise ReleaseReceiptInputError() from exc
    finally:
        _scan_capacity.release()
        for upload in uploads:
            if upload is not None:
                await upload.close()


@app.post("/api/v1/release-receipts/revision", response_model=RevisionReceipt)
async def create_revision_receipt(
    request: Request,
    previous_file: UploadFile = File(...),
    revised_file: UploadFile = File(...),
    revision_check_json: str = Form(...),
    notes: str = Form(default=""),
    semantic_review_json: str | None = Form(default=None),
) -> RevisionReceipt:
    """Bind a deterministic Revision result and optional advisory result to both cuts."""

    config, _ = _api_config()
    try:
        _require_allowed_origin(request, config)
        report = RevisionCheckReport.model_validate_json(revision_check_json)
        semantic = RevisionSemanticReviewReport.model_validate_json(semantic_review_json) if semantic_review_json else None
    except (ValidationError, ValueError, TypeError) as exc:
        await previous_file.close()
        await revised_file.close()
        raise ReleaseReceiptInputError() from exc
    if not _scan_capacity.acquire(config.api.maximum_concurrent_scans):
        await previous_file.close()
        await revised_file.close()
        raise ScanBusyError()
    try:
        with TemporaryDirectory(prefix="releaseseal-revision-receipt-") as temporary_directory:
            previous_path = _media_temp_path(temporary_directory, previous_file.filename, stem="previous")
            revised_path = _media_temp_path(temporary_directory, revised_file.filename, stem="revised")
            await _copy_upload(previous_file, previous_path, config.api.maximum_video_upload_size_bytes)
            await _copy_upload(revised_file, revised_path, config.api.maximum_video_upload_size_bytes)
            return await anyio.to_thread.run_sync(partial(
                build_revision_receipt,
                previous_path=previous_path,
                revised_path=revised_path,
                notes=notes,
                report=report,
                config=config,
                semantic=semantic,
            ))
    except (ValidationError, ValueError, TypeError) as exc:
        raise ReleaseReceiptInputError() from exc
    finally:
        _scan_capacity.release()
        await previous_file.close()
        await revised_file.close()


@app.post("/api/v1/revisions/semantic-review", response_model=RevisionSemanticReviewReport)
async def semantic_review_revision(
    request: Request,
    previous_file: UploadFile = File(...),
    revised_file: UploadFile = File(...),
    revision_check_json: str = Form(...),
) -> RevisionSemanticReviewReport:
    """Explicitly review only bounded clips around eligible deterministic changes."""

    config, _ = _api_config()
    try:
        _require_allowed_origin(request, config)
        try:
            report = RevisionCheckReport.model_validate_json(revision_check_json)
        except ValidationError as exc:
            raise RevisionSemanticReviewError(
                "revision_semantic_report_invalid",
                "The supplied revision check could not be validated.",
            ) from exc
    except Exception:
        await previous_file.close()
        await revised_file.close()
        raise
    if not config.revision_semantic_review.enabled:
        await previous_file.close()
        await revised_file.close()
        raise RevisionSemanticReviewError("revision_semantic_disabled", "AI revision review is disabled by server configuration.")
    if not _scan_capacity.acquire(config.api.maximum_concurrent_scans):
        await previous_file.close()
        await revised_file.close()
        raise ScanBusyError()
    try:
        with TemporaryDirectory(prefix="releaseseal-revision-semantic-") as temporary_directory:
            previous_path = _media_temp_path(temporary_directory, previous_file.filename, stem="previous")
            revised_path = _media_temp_path(temporary_directory, revised_file.filename, stem="revised")
            await _copy_upload(previous_file, previous_path, config.api.maximum_video_upload_size_bytes)
            await _copy_upload(revised_file, revised_path, config.api.maximum_video_upload_size_bytes)
            service = RevisionSemanticReviewService(
                config=config.revision_semantic_review,
                reviewer=GeminiRevisionSemanticReviewer(config.ai_review),
            )
            return await anyio.to_thread.run_sync(partial(service.review, previous_path, revised_path, report))
    finally:
        _scan_capacity.release()
        await previous_file.close()
        await revised_file.close()


@app.post("/api/v1/revisions/check", response_model=RevisionCheckReport)
async def check_revision(
    request: Request,
    previous_file: UploadFile = File(...),
    revised_file: UploadFile = File(...),
    notes: str = Form(default=""),
) -> RevisionCheckReport:
    """Compare two temporary finished cuts with the deterministic Revision Mapper."""

    config, _ = _api_config()
    try:
        _require_allowed_origin(request, config)
    except RequestOriginError:
        await previous_file.close()
        await revised_file.close()
        raise
    if not _scan_capacity.acquire(config.api.maximum_concurrent_scans):
        await previous_file.close()
        await revised_file.close()
        raise ScanBusyError()
    try:
        with TemporaryDirectory(prefix="releaseseal-revision-") as temporary_directory:
            previous_path = _media_temp_path(temporary_directory, previous_file.filename, stem="previous")
            revised_path = _media_temp_path(temporary_directory, revised_file.filename, stem="revised")
            await _copy_upload(previous_file, previous_path, config.api.maximum_video_upload_size_bytes)
            await _copy_upload(revised_file, revised_path, config.api.maximum_video_upload_size_bytes)
            service = RevisionCheckService(
                mapper=RevisionMapper(config.revision_map),
                config=config.revision_check,
            )
            return await anyio.to_thread.run_sync(
                partial(
                    service.check,
                    previous_path,
                    revised_path,
                    notes,
                    previous_filename=previous_file.filename or "previous video",
                    revised_filename=revised_file.filename or "revised video",
                )
            )
    finally:
        _scan_capacity.release()
        await previous_file.close()
        await revised_file.close()


@app.post("/api/v1/preflight/progress", response_model=ScanProgress)
async def create_scan_progress(request: Request, review_mode: str = Form(default="local")) -> ScanProgress:
    """Create a short-lived process-local progress record before media upload begins."""

    config, _ = _api_config()
    _require_allowed_origin(request, config)
    mode = _parse_review_mode(review_mode)
    return _scan_progress.create(mode.value)


@app.get("/api/v1/preflight/progress/{progress_id}", response_model=ScanProgress)
async def get_scan_progress(progress_id: str):
    record = _scan_progress.get(progress_id)
    if record is None:
        return _error_response(404, "scan_progress_not_found", "This scan progress record is no longer available.")
    return record


@app.delete("/api/v1/preflight/progress/{progress_id}", status_code=204)
async def delete_scan_progress(request: Request, progress_id: str) -> None:
    config, _ = _api_config()
    _require_allowed_origin(request, config)
    _scan_progress.delete(progress_id)


@app.post("/api/v1/metadata/assist", response_model=MetadataAssistResult)
async def assist_metadata(
    request: Request,
    file: UploadFile = File(...),
    captions: UploadFile | None = File(default=None),
) -> MetadataAssistResult:
    """Explicitly analyze one temporary video for title and description suggestions."""

    base_config, _ = _api_config()
    try:
        _require_allowed_origin(request, base_config)
    except RequestOriginError:
        await file.close()
        if captions is not None:
            await captions.close()
        raise
    config = _effective_web_config(base_config, ReviewMode.FULL)
    if not config.ai_review.metadata_assist.enabled:
        await file.close()
        if captions is not None:
            await captions.close()
        raise AIReviewError("ai_metadata_assist_disabled", "AI suggestions are not available.", unavailable=True)
    if not _scan_capacity.acquire(config.api.maximum_concurrent_scans):
        await file.close()
        if captions is not None:
            await captions.close()
        raise ScanBusyError()
    try:
        with TemporaryDirectory(prefix="releaseseal-assist-") as temporary_directory:
            media_path = _media_temp_path(temporary_directory, file.filename)
            await _copy_upload(file, media_path, config.api.maximum_video_upload_size_bytes)
            media = await anyio.to_thread.run_sync(MediaInspector().inspect, media_path)
            transcript_text = None
            if captions is not None:
                suffix = Path(captions.filename or "").suffix.lower()
                caption_path = Path(temporary_directory) / f"captions{suffix if suffix in {'.srt', '.vtt'} else '.txt'}"
                await _copy_upload(captions, caption_path, config.rules.captions.maximum_file_size_bytes)
                caption_result = inspect_caption_file(
                    caption_path,
                    media_duration_seconds=media.duration_seconds,
                    config=config.rules.captions,
                )
                if caption_result.cues:
                    transcript_text = "\n".join(cue.text for cue in caption_result.cues)
            sketch_path = Path(temporary_directory) / "content-sketch.mp4"
            await anyio.to_thread.run_sync(
                partial(build_content_sketch, media_path, sketch_path, media, config.ai_review.metadata_assist)
            )
            assistant = GeminiMetadataAssistant()
            return await anyio.to_thread.run_sync(
                partial(
                    assistant.assist, sketch_path, config=config.ai_review,
                    media_mime_type="video/mp4", transcript_text=transcript_text,
                )
            )
    finally:
        _scan_capacity.release()
        await file.close()
        if captions is not None:
            await captions.close()


@app.post("/api/v1/media/inspect", response_model=MediaInspection)
async def inspect_uploaded_media(request: Request, file: UploadFile = File(...)) -> MediaInspection:
    config, _ = _api_config()
    _require_allowed_origin(request, config)
    try:
        with TemporaryDirectory(prefix="releaseseal-") as temporary_directory:
            temporary_path = _media_temp_path(temporary_directory, file.filename)
            await _copy_upload(file, temporary_path, config.api.maximum_video_upload_size_bytes)
            return await anyio.to_thread.run_sync(MediaInspector().inspect, temporary_path)
    finally:
        await file.close()


@app.post("/api/v1/preflight/scan", response_model=PreflightReport)
async def scan_uploaded_package(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(default=""),
    description: str = Form(default=""),
    captions: UploadFile | None = File(default=None),
    thumbnail: UploadFile | None = File(default=None),
    review_mode: str = Form(default="local"),
    progress_id: str | None = Form(default=None),
    release_contract_json: str | None = Form(default=None),
) -> PreflightReport:
    """Temporarily store a package and run the shared scanner off the event loop."""

    base_config, configuration_source = _api_config()
    try:
        _require_allowed_origin(request, base_config)
    except RequestOriginError:
        for upload in (file, captions, thumbnail):
            if upload is not None:
                await upload.close()
        raise
    mode = _parse_review_mode(review_mode)
    if release_contract_json and len(release_contract_json) > _MAX_RELEASE_CONTRACT_JSON_CHARACTERS:
        for upload in (file, captions, thumbnail):
            if upload is not None:
                await upload.close()
        raise ReleaseContractInputError()
    try:
        release_contract = (
            ReleaseContract.model_validate_json(release_contract_json)
            if release_contract_json else None
        )
    except ValidationError as exc:
        for upload in (file, captions, thumbnail):
            if upload is not None:
                await upload.close()
        raise ReleaseContractInputError() from exc
    config = _effective_web_config(base_config, mode)
    if not _scan_capacity.acquire(config.api.maximum_concurrent_scans):
        await file.close()
        if captions is not None:
            await captions.close()
        if thumbnail is not None:
            await thumbnail.close()
        raise ScanBusyError()
    try:
        with TemporaryDirectory(prefix="releaseseal-") as temporary_directory:
            if progress_id:
                _scan_progress.ensure(progress_id, mode.value)
                _scan_progress.update(progress_id, ScanProgressStage.RECEIVING_MEDIA, 3, "Getting the video ready")
            temporary_path = _media_temp_path(temporary_directory, file.filename)
            await _copy_upload(file, temporary_path, config.api.maximum_video_upload_size_bytes)
            caption_path = await _copy_optional_bounded(captions, Path(temporary_directory) / "captions.upload", config.rules.captions.maximum_file_size_bytes + 1)
            thumbnail_path = await _copy_optional_bounded(thumbnail, Path(temporary_directory) / "thumbnail.upload", config.ai_review.promise_check.maximum_thumbnail_file_size_bytes + 1)
            if progress_id:
                _scan_progress.update(progress_id, ScanProgressStage.PREPARING_MEDIA, 8, "Getting the video ready")
            package = PublishingPackage(
                title=title,
                description=description,
                captions_path=caption_path,
                thumbnail_path=thumbnail_path,
                release_contract=release_contract,
            )
            scanner = PreflightScanner(config=config, configuration_source=configuration_source)
            def progress(stage: str, percent: int, message: str) -> None:
                if progress_id:
                    _scan_progress.update(progress_id, ScanProgressStage(stage), percent, message)
            report = await anyio.to_thread.run_sync(
                partial(scanner.scan, temporary_path, package, review_mode=mode, progress=progress)
            )
            if progress_id:
                _scan_progress.finish(progress_id, partial=report.scan_completeness.value == "PARTIAL")
            return report
    except Exception:
        if progress_id:
            _scan_progress.fail(progress_id)
        raise
    finally:
        _scan_capacity.release()
        await file.close()
        if captions is not None:
            await captions.close()
        if thumbnail is not None:
            await thumbnail.close()


@app.post("/api/v1/repairs/preview", response_class=FileResponse)
async def preview_repair(
    request: Request,
    file: UploadFile = File(...),
    operation_json: str = Form(...),
) -> FileResponse:
    """Render one short before/after context clip for an allowlisted repair."""

    try:
        operation = RepairOperation.model_validate_json(operation_json)
    except (ValidationError, ValueError, TypeError) as exc:
        await file.close()
        raise RepairError(
            "repair_operation_invalid",
            "The proposed repair operation is invalid.",
        ) from exc
    return await _render_repair_response(
        request=request,
        file=file,
        operations=[operation],
        preview=True,
    )


@app.post("/api/v1/repairs/apply", response_class=FileResponse)
async def apply_repairs(
    request: Request,
    file: UploadFile = File(...),
    operations_json: str = Form(...),
) -> FileResponse:
    """Render one new MP4 containing all approved, non-overlapping repairs."""

    try:
        batch = RepairOperationBatch.model_validate_json(operations_json)
    except (ValidationError, ValueError, TypeError) as exc:
        await file.close()
        raise RepairError(
            "repair_operation_invalid",
            "The approved repair operations are invalid.",
        ) from exc
    return await _render_repair_response(
        request=request,
        file=file,
        operations=batch.operations,
        preview=False,
    )


@app.post("/api/v1/repairs/verify", response_model=VerificationReport)
async def verify_repaired_video(
    request: Request,
    original_file: UploadFile = File(...),
    repaired_file: UploadFile = File(...),
    operations_json: str = Form(...),
    original_report_json: str = Form(...),
    title: str = Form(default=""),
    description: str = Form(default=""),
    review_mode: str = Form(default="local"),
    captions: UploadFile | None = File(default=None),
    thumbnail: UploadFile | None = File(default=None),
) -> VerificationReport:
    """Re-scan a rendered export and verify it against its approved operations."""

    try:
        batch = RepairOperationBatch.model_validate_json(operations_json)
        original_report = PreflightReport.model_validate_json(original_report_json)
    except (ValidationError, ValueError, TypeError) as exc:
        for upload in (original_file, repaired_file, captions, thumbnail):
            if upload is not None:
                await upload.close()
        raise RepairError("verification_request_invalid", "The repair verification request is invalid.") from exc
    base_config, configuration_source = _api_config()
    try:
        _require_allowed_origin(request, base_config)
    except RequestOriginError:
        for upload in (original_file, repaired_file, captions, thumbnail):
            if upload is not None:
                await upload.close()
        raise
    mode = _parse_review_mode(review_mode)
    config = _effective_web_config(base_config, mode)
    if not _scan_capacity.acquire(config.api.maximum_concurrent_scans):
        for upload in (original_file, repaired_file, captions, thumbnail):
            if upload is not None:
                await upload.close()
        raise ScanBusyError()
    try:
        with TemporaryDirectory(prefix="releaseseal-verify-") as temporary_directory:
            directory = Path(temporary_directory)
            original_path = _media_temp_path(temporary_directory, original_file.filename)
            repaired_path = directory / f"repaired{Path(repaired_file.filename or '').suffix.lower() if Path(repaired_file.filename or '').suffix.lower() in _VIDEO_SUFFIXES else '.mp4'}"
            await _copy_upload(original_file, original_path, config.api.maximum_video_upload_size_bytes)
            await _copy_upload(repaired_file, repaired_path, config.api.maximum_video_upload_size_bytes)
            caption_path = await _copy_optional_bounded(captions, directory / "captions.upload", config.rules.captions.maximum_file_size_bytes + 1)
            thumbnail_path = await _copy_optional_bounded(thumbnail, directory / "thumbnail.upload", config.ai_review.promise_check.maximum_thumbnail_file_size_bytes + 1)
            if caption_path is not None:
                original_media = await anyio.to_thread.run_sync(
                    partial(MediaInspector().inspect, original_path)
                )
                if original_media.duration_seconds is None:
                    raise RepairError(
                        "verification_media_invalid",
                        "Repair verification requires a readable original media duration.",
                    )
                caption_path = await anyio.to_thread.run_sync(
                    partial(
                        transform_caption_file,
                        caption_path,
                        directory / "captions.repaired.srt",
                        original_duration=original_media.duration_seconds,
                        operations=batch.operations,
                    )
                )
            package = PublishingPackage(
                title=title,
                description=description,
                captions_path=caption_path,
                thumbnail_path=thumbnail_path,
                release_contract=original_report.release_contract.contract,
            )
            scanner = PreflightScanner(config=config, configuration_source=configuration_source)
            repaired_report = await anyio.to_thread.run_sync(partial(scanner.scan, repaired_path, package, review_mode=mode))
            return await anyio.to_thread.run_sync(
                partial(verify_repair, original_path, repaired_path, batch.operations, original_report, repaired_report, config.verification)
            )
    finally:
        _scan_capacity.release()
        for upload in (original_file, repaired_file, captions, thumbnail):
            if upload is not None:
                await upload.close()


@app.post("/api/v1/repairs/review-reel", response_class=FileResponse)
async def render_review_reel(
    request: Request,
    repaired_file: UploadFile = File(...),
    manifest_json: str = Form(...),
) -> FileResponse:
    """Render the server-validated repaired-timeline intervals in a reel manifest."""

    try:
        manifest = ReviewReelManifest.model_validate_json(manifest_json)
    except (ValidationError, ValueError, TypeError) as exc:
        await repaired_file.close()
        raise RepairError("review_reel_manifest_invalid", "The review reel manifest is invalid.") from exc
    config, _ = _api_config()
    try:
        _require_allowed_origin(request, config)
    except RequestOriginError:
        await repaired_file.close()
        raise
    if not manifest.entries:
        await repaired_file.close()
        raise RepairError("review_reel_empty", "There are no repair moments to include in a review reel.")
    if not _scan_capacity.acquire(config.api.maximum_concurrent_scans):
        await repaired_file.close()
        raise ScanBusyError()
    temporary_directory = Path(mkdtemp(prefix="releaseseal-reel-"))
    response_created = False
    try:
        source_path = _media_temp_path(str(temporary_directory), repaired_file.filename)
        await _copy_upload(repaired_file, source_path, config.api.maximum_video_upload_size_bytes)
        media = await anyio.to_thread.run_sync(MediaInspector().inspect, source_path)
        output_path = temporary_directory / "review-reel.mp4"
        intervals = [(entry.source_start_seconds, entry.source_end_seconds) for entry in manifest.entries]
        result = await anyio.to_thread.run_sync(partial(FFmpegRepairEngine().render_segments, source_path, output_path, intervals, media=media))
        response = FileResponse(
            result.output_path,
            media_type="video/mp4",
            filename="releaseseal.review-reel.mp4",
            background=BackgroundTask(shutil.rmtree, temporary_directory, True),
            headers={"X-Review-Reel-Duration": f"{result.output_duration_seconds:.6f}"},
        )
        response_created = True
        return response
    finally:
        _scan_capacity.release()
        await repaired_file.close()
        if not response_created:
            shutil.rmtree(temporary_directory, ignore_errors=True)


async def _copy_upload(upload: UploadFile, destination: Path, maximum_bytes: int) -> None:
    written = 0
    with destination.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            written += len(chunk)
            if written > maximum_bytes:
                raise UploadLimitError(maximum_bytes)
            output.write(chunk)


async def _render_repair_response(
    *,
    request: Request,
    file: UploadFile,
    operations: list[RepairOperation],
    preview: bool,
) -> FileResponse:
    config, _ = _api_config()
    try:
        _require_allowed_origin(request, config)
    except RequestOriginError:
        await file.close()
        raise
    if not _scan_capacity.acquire(config.api.maximum_concurrent_scans):
        await file.close()
        raise ScanBusyError()
    temporary_directory = Path(mkdtemp(prefix="releaseseal-repair-"))
    response_created = False
    try:
        source_path = _media_temp_path(str(temporary_directory), file.filename)
        await _copy_upload(
            file,
            source_path,
            config.api.maximum_video_upload_size_bytes,
        )
        media = await anyio.to_thread.run_sync(MediaInspector().inspect, source_path)
        output_path = temporary_directory / (
            "repair-preview.mp4" if preview else "repaired.mp4"
        )
        engine = FFmpegRepairEngine()
        if preview:
            result = await anyio.to_thread.run_sync(
                partial(
                    engine.render_preview,
                    source_path,
                    output_path,
                    operations[0],
                    media=media,
                )
            )
        else:
            result = await anyio.to_thread.run_sync(
                partial(
                    engine.render,
                    source_path,
                    output_path,
                    operations,
                    media=media,
                )
            )
        filename = _repair_download_filename(file.filename, preview=preview)
        response = FileResponse(
            result.output_path,
            media_type="video/mp4",
            filename=filename,
            background=BackgroundTask(shutil.rmtree, temporary_directory, True),
            headers={
                "X-Repair-Original-Duration": f"{result.original_duration_seconds:.6f}",
                "X-Repair-Output-Duration": f"{result.output_duration_seconds:.6f}",
                "X-Repair-Removed-Duration": f"{result.removed_duration_seconds:.6f}",
            },
        )
        response_created = True
        return response
    finally:
        _scan_capacity.release()
        await file.close()
        if not response_created:
            shutil.rmtree(temporary_directory, ignore_errors=True)


async def _copy_optional_bounded(upload: UploadFile | None, destination: Path, copy_limit: int) -> Path | None:
    if upload is None:
        return None
    written = 0
    with destination.open("wb") as output:
        while chunk := await upload.read(64 * 1024):
            remaining = copy_limit - written
            if remaining <= 0:
                break
            output.write(chunk[:remaining])
            written += min(len(chunk), remaining)
            if written >= copy_limit:
                break
    return destination


def _media_temp_path(directory: str, filename: str | None, *, stem: str = "upload") -> Path:
    suffix = Path(filename or "").suffix.lower()
    return Path(directory) / f"{stem}{suffix if suffix in _VIDEO_SUFFIXES else '.media'}"


def _repair_download_filename(filename: str | None, *, preview: bool) -> str:
    stem = Path(filename or "video").stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-") or "video"
    suffix = "repair-preview" if preview else "repaired"
    return f"{safe_stem}.{suffix}.mp4"


def _parse_review_mode(value: str) -> ReviewMode:
    try:
        return ReviewMode(value.strip().lower())
    except ValueError as exc:
        raise ReviewModeError() from exc


def _effective_web_config(config: PreflightConfig, mode: ReviewMode) -> PreflightConfig:
    effective = config.model_copy(deep=True)
    if mode is ReviewMode.FULL:
        effective.ai_review.enabled = True
        effective.ai_review.promise_check.enabled = True
        effective.ai_review.viewer_pass.enabled = True
        effective.ai_review.claim_review.enabled = True
        effective.ai_review.release_brief.enabled = True
    else:
        effective.ai_review.enabled = False
    return effective


def _require_allowed_origin(request: Request, config: PreflightConfig) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in config.api.allowed_browser_origins:
        raise RequestOriginError()


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _api_config() -> tuple[PreflightConfig, str]:
    return _load_runtime_config()
