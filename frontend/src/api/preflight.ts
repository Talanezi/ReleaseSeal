import type {
  CheckResult,
  CaptionSummary,
  AIReviewSummary,
  PromiseCheckSummary,
  ViewerPassSummary,
  ClaimReviewSummary,
  Finding,
  MediaInspection,
  PreflightCapabilities,
  PreflightReport,
  RepairOperation,
  ReviewMode,
  ReviewReelManifest,
  VerificationReport,
  MetadataAssistResult,
  ScanProgress,
  RevisionCheckReport,
  RevisionSemanticReviewReport,
  ReleaseContract,
  FinalExportReceipt,
  RevisionReceipt,
} from "../types/preflight";
import { PRODUCT_NAME } from "../brand";

export interface RevisionCheckInput {
  previousVideo: File;
  revisedVideo: File;
  notes: string;
}

export interface RevisionSemanticReviewInput {
  previousVideo: File;
  revisedVideo: File;
  revisionCheck: RevisionCheckReport;
}

export interface PreflightScanInput {
  video: File;
  title: string;
  description: string;
  captions?: File | null;
  thumbnail?: File | null;
  reviewMode: ReviewMode;
  releaseContract?: ReleaseContract | null;
}

export interface RepairMediaResult {
  blob: Blob;
  originalDurationSeconds: number | null;
  outputDurationSeconds: number | null;
  removedDurationSeconds: number | null;
}

export interface VerifyRepairInput {
  originalVideo: File;
  repairedVideo: File;
  operations: RepairOperation[];
  originalReport: PreflightReport;
  title: string;
  description: string;
  reviewMode: ReviewMode;
  captions?: File | null;
  thumbnail?: File | null;
}

export interface FinalExportReceiptInput {
  originalVideo: File;
  report: PreflightReport;
  title: string;
  description: string;
  captions?: File | null;
  thumbnail?: File | null;
  repairedVideo?: File | null;
  operations?: RepairOperation[];
  verification?: VerificationReport | null;
  humanDispositions?: Record<string, "PENDING" | "ACCEPTED_INTENTIONAL" | "NEEDS_CHANGE">;
}

export interface RevisionReceiptInput {
  previousVideo: File;
  revisedVideo: File;
  notes: string;
  revisionCheck: RevisionCheckReport;
  semanticReview?: RevisionSemanticReviewReport | null;
}

interface StructuredErrorResponse {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown> | null;
  };
}

export class PreflightApiError extends Error {
  readonly code: string;
  readonly status: number | null;

  constructor(message: string, options: { code: string; status?: number | null; cause?: unknown }) {
    super(message, { cause: options.cause });
    this.name = "PreflightApiError";
    this.code = options.code;
    this.status = options.status ?? null;
  }
}

export async function scanPreflight(
  input: PreflightScanInput,
  options: { signal?: AbortSignal; progressId?: string } = {},
): Promise<PreflightReport> {
  const form = new FormData();
  form.append("file", input.video, input.video.name);
  form.append("title", input.title);
  form.append("description", input.description);
  form.append("review_mode", input.reviewMode);
  if (options.progressId) form.append("progress_id", options.progressId);
  if (input.captions) form.append("captions", input.captions, input.captions.name);
  if (input.thumbnail) form.append("thumbnail", input.thumbnail, input.thumbnail.name);
  if (input.releaseContract) form.append("release_contract_json", JSON.stringify(input.releaseContract));

  let response: Response;
  try {
    response = await fetch("/api/v1/preflight/scan", {
      method: "POST",
      body: form,
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new PreflightApiError(
      `Could not reach the local ${PRODUCT_NAME} backend.`,
      { code: "backend_unreachable", cause: error },
    );
  }

  const payload = await parseJsonResponse(response);
  if (!response.ok) {
    const structured = parseStructuredError(payload);
    throw new PreflightApiError(
      structured?.error.message ?? `The preflight request failed with HTTP ${response.status}.`,
      {
        code: structured?.error.code ?? "request_failed",
        status: response.status,
      },
    );
  }
  if (!isPreflightReport(payload)) {
    throw new PreflightApiError(
      "The backend returned an unexpected preflight report.",
      { code: "invalid_response", status: response.status },
    );
  }
  return payload;
}

export async function extractReleaseContract(brief: string, options: { signal?: AbortSignal } = {}): Promise<ReleaseContract> {
  const form = new FormData();
  form.append("brief", brief);
  let response: Response;
  try {
    response = await fetch("/api/v1/release-contracts/extract", { method: "POST", body: form, signal: options.signal });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new PreflightApiError("Could not reach requirement extraction.", { code: "backend_unreachable", cause: error });
  }
  const payload = await parseJsonResponse(response);
  if (!response.ok) {
    const structured = parseStructuredError(payload);
    throw new PreflightApiError(structured?.error.message ?? "Requirements could not be extracted.", { code: structured?.error.code ?? "request_failed", status: response.status });
  }
  if (!isReleaseContract(payload)) throw new PreflightApiError("The backend returned an invalid release contract.", { code: "invalid_response", status: response.status });
  return payload;
}

export async function createFinalExportReceipt(input: FinalExportReceiptInput, options: { signal?: AbortSignal } = {}): Promise<FinalExportReceipt> {
  const form = new FormData();
  form.append("file", input.originalVideo, input.originalVideo.name);
  form.append("report_json", JSON.stringify(input.report));
  form.append("title", input.title);
  form.append("description", input.description);
  if (input.captions) form.append("captions", input.captions, input.captions.name);
  if (input.thumbnail) form.append("thumbnail", input.thumbnail, input.thumbnail.name);
  if (input.repairedVideo) {
    form.append("repaired_file", input.repairedVideo, input.repairedVideo.name);
    form.append("operations_json", JSON.stringify({ operations: input.operations ?? [] }));
    form.append("verification_json", JSON.stringify(input.verification));
  }
  form.append("human_dispositions_json", JSON.stringify(Object.entries(input.humanDispositions ?? {}).map(([proposal_id, disposition]) => ({ proposal_id, disposition }))));
  const payload = await requestJson("/api/v1/release-receipts/final-export", form, options.signal, "The release receipt could not be created.");
  if (!isFinalExportReceipt(payload)) throw new PreflightApiError("The backend returned an invalid release receipt.", { code: "invalid_response" });
  return payload;
}

export async function createRevisionReceipt(input: RevisionReceiptInput, options: { signal?: AbortSignal } = {}): Promise<RevisionReceipt> {
  const form = new FormData();
  form.append("previous_file", input.previousVideo, input.previousVideo.name);
  form.append("revised_file", input.revisedVideo, input.revisedVideo.name);
  form.append("notes", input.notes);
  form.append("revision_check_json", JSON.stringify(input.revisionCheck));
  if (input.semanticReview) form.append("semantic_review_json", JSON.stringify(input.semanticReview));
  const payload = await requestJson("/api/v1/release-receipts/revision", form, options.signal, "The revision receipt could not be created.");
  if (!isRevisionReceipt(payload)) throw new PreflightApiError("The backend returned an invalid revision receipt.", { code: "invalid_response" });
  return payload;
}

export async function checkRevision(
  input: RevisionCheckInput,
  options: { signal?: AbortSignal } = {},
): Promise<RevisionCheckReport> {
  const form = new FormData();
  form.append("previous_file", input.previousVideo, input.previousVideo.name);
  form.append("revised_file", input.revisedVideo, input.revisedVideo.name);
  form.append("notes", input.notes);
  let response: Response;
  try {
    response = await fetch("/api/v1/revisions/check", { method: "POST", body: form, signal: options.signal });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new PreflightApiError("Could not reach the local revision service.", { code: "revision_backend_unreachable", cause: error });
  }
  const payload = await parseJsonResponse(response);
  if (!response.ok) {
    const structured = parseStructuredError(payload);
    throw new PreflightApiError(
      structured?.error.message ?? "These versions could not be compared.",
      { code: structured?.error.code ?? "revision_check_failed", status: response.status },
    );
  }
  if (!isRevisionCheckReport(payload)) {
    throw new PreflightApiError("The backend returned an unexpected revision report.", { code: "revision_invalid_response", status: response.status });
  }
  return payload;
}

export async function reviewRevisionSemantics(
  input: RevisionSemanticReviewInput,
  options: { signal?: AbortSignal } = {},
): Promise<RevisionSemanticReviewReport> {
  const form = new FormData();
  form.append("previous_file", input.previousVideo, input.previousVideo.name);
  form.append("revised_file", input.revisedVideo, input.revisedVideo.name);
  form.append("revision_check_json", JSON.stringify(input.revisionCheck));
  let response: Response;
  try {
    response = await fetch("/api/v1/revisions/semantic-review", { method: "POST", body: form, signal: options.signal });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new PreflightApiError("Could not reach the local AI revision-review service.", { code: "revision_semantic_backend_unreachable", cause: error });
  }
  const payload = await parseJsonResponse(response);
  if (!response.ok) {
    const structured = parseStructuredError(payload);
    throw new PreflightApiError(structured?.error.message ?? "AI revision review is unavailable.", { code: structured?.error.code ?? "revision_semantic_review_failed", status: response.status });
  }
  if (!isRevisionSemanticReviewReport(payload)) {
    throw new PreflightApiError("The backend returned an unexpected AI revision review.", { code: "revision_semantic_invalid_response", status: response.status });
  }
  return payload;
}

export async function createScanProgress(reviewMode: ReviewMode, options: { signal?: AbortSignal } = {}): Promise<ScanProgress> {
  const form = new FormData();
  form.append("review_mode", reviewMode);
  const response = await fetch("/api/v1/preflight/progress", { method: "POST", body: form, signal: options.signal });
  const payload = await parseJsonResponse(response);
  if (!response.ok || !isScanProgress(payload)) {
    throw new PreflightApiError("Live scan progress could not be started.", { code: response.ok ? "invalid_response" : "request_failed", status: response.status });
  }
  return payload;
}

export async function fetchScanProgress(progressId: string, options: { signal?: AbortSignal } = {}): Promise<ScanProgress> {
  const response = await fetch(`/api/v1/preflight/progress/${encodeURIComponent(progressId)}`, { signal: options.signal });
  const payload = await parseJsonResponse(response);
  if (!response.ok || !isScanProgress(payload)) {
    throw new PreflightApiError("Live scan progress is temporarily unavailable.", { code: response.ok ? "invalid_response" : "request_failed", status: response.status });
  }
  return payload;
}

export async function discardScanProgress(progressId: string): Promise<void> {
  try {
    await fetch(`/api/v1/preflight/progress/${encodeURIComponent(progressId)}`, { method: "DELETE" });
  } catch {
    // Progress records are bounded and ephemeral; scan/reset must not fail on cleanup.
  }
}

export async function fetchCapabilities(
  options: { signal?: AbortSignal } = {},
): Promise<PreflightCapabilities> {
  let response: Response;
  try {
    response = await fetch("/api/v1/capabilities", { signal: options.signal });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new PreflightApiError("Could not load backend capabilities.", {
      code: "backend_unreachable",
      cause: error,
    });
  }
  const payload = await parseJsonResponse(response);
  if (!response.ok || !isPreflightCapabilities(payload)) {
    throw new PreflightApiError("The backend capabilities could not be read.", {
      code: response.ok ? "invalid_response" : "request_failed",
      status: response.status,
    });
  }
  return payload;
}

export async function assistMetadata(
  video: File,
  options: { signal?: AbortSignal; captions?: File | null } = {},
): Promise<MetadataAssistResult> {
  const form = new FormData();
  form.append("file", video, video.name);
  if (options.captions) form.append("captions", options.captions, options.captions.name);
  let response: Response;
  try {
    response = await fetch("/api/v1/metadata/assist", { method: "POST", body: form, signal: options.signal });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new PreflightApiError("AI suggestions could not reach the local backend.", { code: "backend_unreachable", cause: error });
  }
  const payload = await parseJsonResponse(response);
  if (!response.ok) {
    const structured = parseStructuredError(payload);
    throw new PreflightApiError(structured?.error.message ?? "AI suggestions could not be generated.", { code: structured?.error.code ?? "metadata_assist_failed", status: response.status });
  }
  if (!isMetadataAssistResult(payload)) throw new PreflightApiError("The backend returned unexpected AI suggestions.", { code: "invalid_response", status: response.status });
  return payload;
}

export async function previewRepair(
  video: File,
  operation: RepairOperation,
  options: { signal?: AbortSignal } = {},
): Promise<RepairMediaResult> {
  const form = new FormData();
  form.append("file", video, video.name);
  form.append("operation_json", JSON.stringify(operation));
  return requestRepairMedia("/api/v1/repairs/preview", form, options.signal);
}

export async function applyRepairs(
  video: File,
  operations: RepairOperation[],
  options: { signal?: AbortSignal } = {},
): Promise<RepairMediaResult> {
  const form = new FormData();
  form.append("file", video, video.name);
  form.append("operations_json", JSON.stringify({ operations }));
  return requestRepairMedia("/api/v1/repairs/apply", form, options.signal);
}

export async function verifyRepair(input: VerifyRepairInput, options: { signal?: AbortSignal } = {}): Promise<VerificationReport> {
  const form = new FormData();
  form.append("original_file", input.originalVideo, input.originalVideo.name);
  form.append("repaired_file", input.repairedVideo, input.repairedVideo.name);
  form.append("operations_json", JSON.stringify({ operations: input.operations }));
  form.append("original_report_json", JSON.stringify(input.originalReport));
  form.append("title", input.title);
  form.append("description", input.description);
  form.append("review_mode", input.reviewMode);
  if (input.captions) form.append("captions", input.captions, input.captions.name);
  if (input.thumbnail) form.append("thumbnail", input.thumbnail, input.thumbnail.name);
  let response: Response;
  try {
    response = await fetch("/api/v1/repairs/verify", { method: "POST", body: form, signal: options.signal });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new PreflightApiError("The repaired video could not be verified.", { code: "backend_unreachable", cause: error });
  }
  const payload = await parseJsonResponse(response);
  if (!response.ok) {
    const structured = parseStructuredError(payload);
    throw new PreflightApiError(structured?.error.message ?? "The repaired video could not be verified.", { code: structured?.error.code ?? "verification_failed", status: response.status });
  }
  if (!isVerificationReport(payload)) throw new PreflightApiError("The backend returned an unexpected verification report.", { code: "invalid_response", status: response.status });
  return payload;
}

export async function renderReviewReel(repairedVideo: File, manifest: ReviewReelManifest, options: { signal?: AbortSignal } = {}): Promise<RepairMediaResult> {
  const form = new FormData();
  form.append("repaired_file", repairedVideo, repairedVideo.name);
  form.append("manifest_json", JSON.stringify(manifest));
  return requestRepairMedia("/api/v1/repairs/review-reel", form, options.signal);
}

export function errorPresentation(error: unknown): { title: string; message: string; detail?: string } {
  if (error instanceof PreflightApiError) {
    if (error.code === "backend_unreachable") {
      return {
        title: `${PRODUCT_NAME} is unavailable`,
        message: error.message,
        detail: "Start the local FastAPI backend, then return to the scan and try again.",
      };
    }
    if (error.code === "media_tool_unavailable" || error.code.startsWith("ffprobe_")) {
      return {
        title: "Media tools are unavailable",
        message: error.message,
        detail: "Confirm FFmpeg and FFprobe are installed on the backend machine.",
      };
    }
    if (error.code === "invalid_media" || error.code === "empty_file") {
      return {
        title: "This file could not be analyzed",
        message: error.message,
        detail: "Choose a readable, non-empty media file and try again.",
      };
    }
    if (error.code.startsWith("thumbnail_")) {
      return {
        title: "This thumbnail could not be used",
        message: error.message,
        detail: "Choose a valid PNG or JPEG within the configured size limit.",
      };
    }
    if (error.code === "video_upload_too_large") {
      return {
        title: "This video is too large",
        message: error.message,
        detail: "Choose a smaller export or adjust the backend's configured upload limit.",
      };
    }
    if (error.code === "scan_capacity_reached") {
      return {
        title: `${PRODUCT_NAME} is busy`,
        message: error.message,
        detail: "Wait for the active scan to finish, then try again.",
      };
    }
    if (error.code === "request_origin_not_allowed") {
      return {
        title: "This browser cannot start a scan",
        message: error.message,
        detail: `Open ${PRODUCT_NAME} from an allowed local frontend origin.`,
      };
    }
    if (error.code.startsWith("ai_")) {
      return {
        title: "AI assistance is unavailable",
        message: error.code === "ai_provider_quota_exhausted"
          ? "AI assistance has reached its current usage limit."
          : "AI assistance could not finish this request.",
        detail: error.status === 429 ? "Try again after the usage limit resets." : "Try again shortly or continue without suggestions.",
      };
    }
    if (error.code.startsWith("revision_")) {
      return {
        title: "These versions could not be compared",
        message: error.message,
        detail: error.code.includes("unavailable")
          ? "Confirm FFmpeg and FFprobe are available, then try again."
          : "Check both video files and any revision-note timecodes, then try again.",
      };
    }
    return {
      title: "The scan could not be completed",
      message: error.message,
      detail: error.code === "invalid_response"
        ? "The local backend response did not match the expected report format."
        : undefined,
    };
  }
  return {
    title: "The scan could not be completed",
    message: `${PRODUCT_NAME} encountered an unexpected application error.`,
  };
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

async function requestJson(path: string, form: FormData, signal: AbortSignal | undefined, fallback: string): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, { method: "POST", body: form, signal });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new PreflightApiError(fallback, { code: "backend_unreachable", cause: error });
  }
  const payload = await parseJsonResponse(response);
  if (!response.ok) {
    const structured = parseStructuredError(payload);
    throw new PreflightApiError(structured?.error.message ?? fallback, { code: structured?.error.code ?? "request_failed", status: response.status });
  }
  return payload;
}

async function parseJsonResponse(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    if (!response.ok) return null;
    throw new PreflightApiError(
      "The backend returned an unreadable response.",
      { code: "invalid_response", status: response.status },
    );
  }
}

function parseStructuredError(value: unknown): StructuredErrorResponse | null {
  if (!isRecord(value) || !isRecord(value.error)) return null;
  if (typeof value.error.code !== "string" || typeof value.error.message !== "string") return null;
  const details = value.error.details;
  if (details !== null && details !== undefined && !isRecord(details)) return null;
  return {
    error: {
      code: value.error.code,
      message: value.error.message,
      details: details ?? null,
    },
  };
}

function isPreflightReport(value: unknown): value is PreflightReport {
  if (!isRecord(value)) return false;
  return typeof value.schema_version === "string"
    && isFindingStatus(value.verdict)
    && (value.scan_completeness === "COMPLETE" || value.scan_completeness === "PARTIAL" || value.scan_completeness === "FAILED")
    && (value.review_mode === "full" || value.review_mode === "local")
    && Array.isArray(value.execution_issues)
    && value.execution_issues.every(isExecutionIssue)
    && isMediaInspection(value.media)
    && Array.isArray(value.findings)
    && value.findings.every(isFinding)
    && Array.isArray(value.checks)
    && value.checks.every(isCheckResult)
    && isNonnegativeNumber(value.checks_run_count)
    && isNonnegativeNumber(value.passed_check_count)
    && isNonnegativeNumber(value.warning_count)
    && isNonnegativeNumber(value.critical_count)
    && typeof value.configuration_profile === "string"
    && isNullableString(value.configuration_source)
    && (value.caption_summary === null || isCaptionSummary(value.caption_summary))
    && isAIReviewSummary(value.ai_review)
    && isPromiseCheckSummary(value.promise_check)
    && isViewerPassSummary(value.viewer_pass)
    && isClaimReviewSummary(value.claim_review)
    && isReleasePackageSummary(value.release_package)
    && isReleaseContractEvaluation(value.release_contract)
    && isRepairPlan(value.repair_plan)
    && isReleaseBrief(value.release_brief)
    && isNonnegativeNumber(value.scan_duration_seconds);
}

function isReleasePackageSummary(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const component = (item: unknown) => isRecord(item)
    && (item.state === "PRESENT_VALID" || item.state === "PRESENT_INVALID" || item.state === "ABSENT" || item.state === "NOT_REQUIRED")
    && typeof item.detail === "string";
  const components = ["video", "thumbnail", "captions", "title", "description", "chapters", "release_contract"];
  return components.every((key) => component(value[key]))
    && (value.thumbnail_mime_type === null || typeof value.thumbnail_mime_type === "string")
    && (value.thumbnail_file_size_bytes === null || isNonnegativeNumber(value.thumbnail_file_size_bytes))
    && (value.thumbnail_width === null || isNonnegativeNumber(value.thumbnail_width))
    && (value.thumbnail_height === null || isNonnegativeNumber(value.thumbnail_height))
    && Array.isArray(value.thumbnail_checks)
    && value.thumbnail_checks.every((item) => isRecord(item) && typeof item.check_id === "string" && typeof item.label === "string"
      && (item.status === "PASS" || item.status === "NEEDS_REVIEW") && typeof item.measured === "string" && typeof item.expected === "string")
    && (value.delivery_preview === null || (isRecord(value.delivery_preview)
      && (value.delivery_preview.duration_badge_text === null || typeof value.delivery_preview.duration_badge_text === "string")
      && Array.isArray(value.delivery_preview.surfaces)
      && value.delivery_preview.surfaces.every((item) => isRecord(item) && typeof item.surface_id === "string" && typeof item.label === "string"
        && isNonnegativeNumber(item.display_width) && isNonnegativeNumber(item.display_height)
        && isNonnegativeNumber(item.safe_margin_fraction) && isNonnegativeNumber(item.badge_x) && isNonnegativeNumber(item.badge_y)
        && isNonnegativeNumber(item.badge_width) && isNonnegativeNumber(item.badge_height))
      && Array.isArray(value.delivery_preview.critical_region_intersections)))
    && isNonnegativeNumber(value.construction_seconds)
    && isNonnegativeNumber(value.thumbnail_evaluation_seconds)
    && isNonnegativeNumber(value.preview_metadata_seconds);
}

function isReleaseContract(value: unknown): value is ReleaseContract {
  return isRecord(value) && value.schema_version === "1.0" && (value.name === null || typeof value.name === "string")
    && Array.isArray(value.requirements) && value.requirements.length <= 30
    && value.requirements.every(isReleaseRequirement);
}

const releaseRequirementTypes = ["REQUIRED_TEXT", "REQUIRED_EXACT_TOKEN", "REQUIRED_URL", "REQUIRED_BEFORE_TIME", "FORBIDDEN_TEXT", "TITLE_CONTAINS", "DESCRIPTION_CONTAINS", "DESCRIPTION_URL", "MAX_DURATION", "MIN_RESOLUTION", "ASPECT_RATIO", "CAPTIONS_REQUIRED", "THUMBNAIL_REQUIRED", "REQUIRED_TALKING_POINT", "FORBIDDEN_CLAIM"] as const;

function isReleaseRequirement(item: unknown): boolean {
  if (!isRecord(item) || typeof item.id !== "string" || !releaseRequirementTypes.includes(item.type as typeof releaseRequirementTypes[number])
    || typeof item.instruction !== "string" || (item.provenance !== "manual" && item.provenance !== "extracted")
    || (item.source_excerpt !== null && typeof item.source_excerpt !== "string")) return false;
  const semantic = item.type === "REQUIRED_TALKING_POINT" || item.type === "FORBIDDEN_CLAIM";
  if (item.evaluation_class !== (semantic ? "SEMANTIC" : "DETERMINISTIC")) return false;
  if (item.type === "CAPTIONS_REQUIRED" || item.type === "THUMBNAIL_REQUIRED") return true;
  if (item.type === "MAX_DURATION") return typeof item.maximum_seconds === "number" && item.maximum_seconds > 0;
  if (item.type === "MIN_RESOLUTION") return typeof item.minimum_width === "number" && item.minimum_width > 0 && typeof item.minimum_height === "number" && item.minimum_height > 0;
  if (item.type === "ASPECT_RATIO") return typeof item.width_ratio === "number" && item.width_ratio > 0 && typeof item.height_ratio === "number" && item.height_ratio > 0 && typeof item.tolerance === "number";
  return typeof item.value === "string" && item.value.length > 0
    && (item.type !== "REQUIRED_BEFORE_TIME" || (typeof item.before_seconds === "number" && item.before_seconds > 0));
}

function isReleaseContractEvaluation(value: unknown): boolean {
  return isRecord(value) && (value.contract === null || isReleaseContract(value.contract))
    && Array.isArray(value.results) && value.results.every((item) => isRecord(item)
      && typeof item.requirement_id === "string" && releaseRequirementTypes.includes(item.requirement_type as typeof releaseRequirementTypes[number]) && typeof item.instruction === "string"
      && (item.evaluation_class === "DETERMINISTIC" || item.evaluation_class === "SEMANTIC")
      && (item.status === "PASS" || item.status === "FAIL" || item.status === "NEEDS_REVIEW" || item.status === "NOT_EVALUATED")
      && typeof item.evidence === "string" && (item.timestamp_seconds === null || isNonnegativeNumber(item.timestamp_seconds))
      && (item.evidence_source === "CAPTION_TEXT" || item.evidence_source === "PUBLISHING_METADATA" || item.evidence_source === "MEDIA_INSPECTION" || item.evidence_source === "AI_SEMANTIC" || item.evidence_source === "NONE")
      && (item.expected === null || typeof item.expected === "string")
      && (item.confidence === null || (isNonnegativeNumber(item.confidence) && item.confidence <= 1))
      && (item.reason_code === null || typeof item.reason_code === "string"))
    && isNonnegativeNumber(value.passed_count) && isNonnegativeNumber(value.failed_count)
    && isNonnegativeNumber(value.needs_review_count) && isNonnegativeNumber(value.not_evaluated_count)
    && isNonnegativeNumber(value.runtime_seconds);
}

function isScanProgress(value: unknown): value is ScanProgress {
  return isRecord(value)
    && typeof value.progress_id === "string"
    && (value.review_mode === "full" || value.review_mode === "local")
    && (value.state === "RUNNING" || value.state === "COMPLETE" || value.state === "PARTIAL" || value.state === "FAILED")
    && typeof value.stage === "string"
    && isNonnegativeNumber(value.percent) && value.percent <= 100
    && typeof value.message === "string"
    && isNonnegativeNumber(value.created_at_epoch_seconds)
    && isNonnegativeNumber(value.updated_at_epoch_seconds)
    && Array.isArray(value.tasks)
    && value.tasks.every((task) => isRecord(task) && typeof task.task_id === "string"
      && typeof task.label === "string"
      && (task.status === "Done" || task.status === "Working" || task.status === "Waiting" || task.status === "Unavailable"));
}

function isVerificationReport(value: unknown): value is VerificationReport {
  if (!isRecord(value)) return false;
  return typeof value.schema_version === "string"
    && (value.status === "VERIFIED" || value.status === "NEEDS_REVIEW" || value.status === "INCOMPLETE")
    && isNonnegativeNumber(value.approved_repair_count)
    && Array.isArray(value.resolved) && value.resolved.every(isFindingComparison)
    && Array.isArray(value.remaining) && value.remaining.every(isFindingComparison)
    && Array.isArray(value.new) && value.new.every(isFindingComparison)
    && Array.isArray(value.unexpected_changes) && value.unexpected_changes.every(isUnexpectedChange)
    && isNonnegativeNumber(value.original_duration_seconds)
    && isNonnegativeNumber(value.repaired_duration_seconds)
    && isNonnegativeNumber(value.expected_duration_seconds)
    && isRecord(value.integrity) && typeof value.integrity.passed === "boolean"
    && isPreflightReport(value.repaired_preflight_report)
    && (value.regression_analysis_completeness === "COMPLETE" || value.regression_analysis_completeness === "PARTIAL" || value.regression_analysis_completeness === "FAILED")
    && isReviewReelManifest(value.review_reel_manifest)
    && typeof value.review_reel_available === "boolean"
    && Array.isArray(value.limitations) && value.limitations.every((item) => typeof item === "string");
}

function isFindingComparison(value: unknown): boolean {
  return isRecord(value)
    && (value.status === "RESOLVED" || value.status === "REMAINING" || value.status === "NEW")
    && (value.original_finding === null || isFinding(value.original_finding))
    && (value.repaired_finding === null || isFinding(value.repaired_finding))
    && isNullableNumber(value.expected_repaired_start_seconds)
    && isNullableNumber(value.expected_repaired_end_seconds)
    && typeof value.deterministically_verified === "boolean"
    && typeof value.explanation === "string";
}

function isUnexpectedChange(value: unknown): boolean {
  return isRecord(value) && isNonnegativeNumber(value.start_seconds) && isNonnegativeNumber(value.end_seconds)
    && value.end_seconds > value.start_seconds && isNonnegativeNumber(value.maximum_mean_difference) && isNonnegativeNumber(value.sample_count);
}

function isReviewReelManifest(value: unknown): value is ReviewReelManifest {
  return isRecord(value) && Array.isArray(value.entries) && value.entries.every((entry) => isRecord(entry)
    && isNonnegativeNumber(entry.reel_start_seconds) && isNonnegativeNumber(entry.reel_end_seconds)
    && isNonnegativeNumber(entry.source_start_seconds) && isNonnegativeNumber(entry.source_end_seconds)
    && typeof entry.reason === "string" && typeof entry.category === "string"
    && (entry.source_id === null || typeof entry.source_id === "string"))
    && isNonnegativeNumber(value.total_duration_seconds);
}

function isRepairPlan(value: unknown): boolean {
  return isRecord(value)
    && Array.isArray(value.proposals)
    && value.proposals.every(isRepairProposal)
    && isNonnegativeNumber(value.safe_count)
    && isNonnegativeNumber(value.preview_required_count)
    && isNonnegativeNumber(value.human_only_count);
}

function isRepairProposal(value: unknown): boolean {
  return isRecord(value)
    && typeof value.proposal_id === "string"
    && typeof value.finding_code === "string"
    && typeof value.finding_title === "string"
    && typeof value.explanation === "string"
    && typeof value.source === "string"
    && (value.repairability === "SAFE" || value.repairability === "PREVIEW_REQUIRED" || value.repairability === "HUMAN_ONLY")
    && (value.operation === null || isRepairOperation(value.operation))
    && isNullableNumber(value.start_seconds)
    && isNullableNumber(value.end_seconds)
    && isNullableNumber(value.expected_duration_change_seconds)
    && isNullableNumber(value.original_start_seconds)
    && isNullableNumber(value.original_end_seconds)
    && (value.evidence === null || (isRecord(value.evidence) && isJsonObject(value.evidence)));
}

function isRepairOperation(value: unknown): boolean {
  return isRecord(value)
    && value.operation_type === "REMOVE_RANGE"
    && isNonnegativeNumber(value.start_seconds)
    && isNonnegativeNumber(value.end_seconds)
    && value.end_seconds > value.start_seconds;
}

function isExecutionIssue(value: unknown): boolean {
  return isRecord(value)
    && typeof value.component === "string"
    && typeof value.reason_code === "string"
    && typeof value.message === "string"
    && typeof value.retryable === "boolean";
}

function isPreflightCapabilities(value: unknown): value is PreflightCapabilities {
  return isRecord(value)
    && typeof value.ffprobe_available === "boolean"
    && typeof value.ffmpeg_available === "boolean"
    && typeof value.gemini_dependency_available === "boolean"
    && typeof value.gemini_api_key_configured === "boolean"
    && typeof value.full_review_available === "boolean"
    && typeof value.metadata_assist_available === "boolean"
    && typeof value.release_contract_extraction_available === "boolean"
    && typeof value.local_checks_available === "boolean"
    && typeof value.revision_check_available === "boolean"
    && typeof value.revision_semantic_review_available === "boolean"
    && typeof value.transcription_dependency_available === "boolean"
    && typeof value.transcription_enabled === "boolean"
    && Array.isArray(value.supported_review_modes)
    && value.supported_review_modes.every((mode) => mode === "full" || mode === "local")
    && isNonnegativeNumber(value.maximum_video_upload_size_bytes)
    && Array.isArray(value.full_review_unavailable_reasons)
    && value.full_review_unavailable_reasons.every((reason) => isRecord(reason)
      && typeof reason.code === "string" && typeof reason.message === "string");
}

export function isRevisionCheckReport(value: unknown): value is RevisionCheckReport {
  if (!isRecord(value) || !isRecord(value.revision_map)) return false;
  const map = value.revision_map;
  return typeof value.schema_version === "string"
    && typeof value.previous_filename === "string"
    && typeof value.revised_filename === "string"
    && isNonnegativeNumber(value.requested_change_count)
    && isNonnegativeNumber(value.requested_changes_detected_count)
    && isNonnegativeNumber(value.requested_changes_not_detected_count)
    && isNonnegativeNumber(value.requests_needing_location_count)
    && isNonnegativeNumber(value.additional_change_count)
    && isNonnegativeNumber(value.analysis_runtime_seconds)
    && Array.isArray(value.revision_requests) && value.revision_requests.every(isRevisionRequest)
    && Array.isArray(value.additional_changes) && value.additional_changes.every(isRevisionChange)
    && isNonnegativeNumber(map.previous_duration_seconds)
    && isNonnegativeNumber(map.revised_duration_seconds)
    && isNonnegativeNumber(map.estimated_unchanged_duration_seconds)
    && isNonnegativeNumber(map.unchanged_ratio) && map.unchanged_ratio <= 1
    && typeof map.previous_sha256 === "string" && typeof map.revised_sha256 === "string"
    && isRecord(map.previous_streams) && isRecord(map.revised_streams)
    && isRecord(map.sampling_policy)
    && isNonnegativeNumber(map.previous_sample_count) && isNonnegativeNumber(map.revised_sample_count)
    && Array.isArray(map.segments) && map.segments.every(isRevisionSegment)
    && Array.isArray(map.ambiguity_notes) && map.ambiguity_notes.every((item) => typeof item === "string")
    && isNonnegativeNumber(map.analysis_runtime_seconds)
    && typeof map.identical_file_fast_path === "boolean";
}

export function isRevisionSemanticReviewReport(value: unknown): value is RevisionSemanticReviewReport {
  if (!isRecord(value) || !Array.isArray(value.results)) return false;
  const statuses = new Set(["APPEARS_SATISFIED", "APPEARS_UNRESOLVED", "INCONCLUSIVE", "NOT_REVIEWED"]);
  return typeof value.schema_version === "string"
    && typeof value.provider === "string"
    && typeof value.model === "string"
    && ["eligible_count", "requested_count", "reviewed_count", "appears_satisfied_count", "appears_unresolved_count", "inconclusive_count", "not_reviewed_count", "evidence_render_seconds", "provider_seconds", "total_seconds", "upload_count", "generation_count", "delete_count"].every((key) => typeof value[key] === "number")
    && value.results.every((item) => isRecord(item)
      && typeof item.request_id === "string"
      && typeof item.status === "string" && statuses.has(item.status)
      && (item.confidence === null || typeof item.confidence === "number")
      && typeof item.rationale === "string"
      && typeof item.partial_evidence === "boolean");
}

function isFinalExportReceipt(value: unknown): value is FinalExportReceipt {
  return isRecord(value)
    && value.receipt_schema_version === "1.0"
    && value.receipt_kind === "FINAL_EXPORT"
    && typeof value.created_at === "string"
    && typeof value.scanner_version === "string"
    && (value.verdict === "READY" || value.verdict === "NEEDS_REVIEW" || value.verdict === "BLOCKED")
    && (value.scan_completeness === "COMPLETE" || value.scan_completeness === "PARTIAL" || value.scan_completeness === "FAILED")
    && isSha256(value.configuration_fingerprint_sha256)
    && isRecord(value.package)
    && isRecord(value.package.shipping_video)
    && isSha256(value.package.shipping_video.sha256)
    && isNonnegativeNumber(value.package.shipping_video.size_bytes)
    && (value.package.shipping_role === "ORIGINAL" || value.package.shipping_role === "REPAIRED")
    && isSha256(value.package.package_fingerprint_sha256)
    && isSha256(value.receipt_content_sha256);
}

function isRevisionReceipt(value: unknown): value is RevisionReceipt {
  return isRecord(value)
    && value.receipt_schema_version === "1.0"
    && value.receipt_kind === "REVISION"
    && typeof value.created_at === "string"
    && value.verdict === "NOT_APPLICABLE"
    && value.scan_completeness === "COMPLETE"
    && isRecord(value.previous_video) && isSha256(value.previous_video.sha256) && isNonnegativeNumber(value.previous_video.size_bytes)
    && isRecord(value.revised_video) && isSha256(value.revised_video.sha256) && isNonnegativeNumber(value.revised_video.size_bytes)
    && isSha256(value.revision_notes_sha256)
    && isSha256(value.revision_fingerprint_sha256)
    && isSha256(value.receipt_content_sha256);
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function isRevisionRequest(value: unknown): boolean {
  return isRecord(value)
    && typeof value.request_id === "string" && isNonnegativeNumber(value.source_line)
    && typeof value.text === "string"
    && isNullableNumber(value.previous_start_seconds) && isNullableNumber(value.previous_end_seconds)
    && typeof value.explicit_range === "boolean"
    && (value.status === "CHANGE_DETECTED" || value.status === "NO_CHANGE_DETECTED" || value.status === "NEEDS_LOCATION")
    && Array.isArray(value.matched_segment_ids) && value.matched_segment_ids.every((item) => typeof item === "string")
    && typeof value.evidence === "string";
}

function isRevisionChange(value: unknown): boolean {
  return isRecord(value)
    && typeof value.segment_id === "string"
    && isRevisionKind(value.kind)
    && isNullableNumber(value.previous_start_seconds) && isNullableNumber(value.previous_end_seconds)
    && isNullableNumber(value.revised_start_seconds) && isNullableNumber(value.revised_end_seconds)
    && typeof value.visual_changed === "boolean" && typeof value.audio_changed === "boolean"
    && (value.boundary_confidence === "high" || value.boundary_confidence === "approximate" || value.boundary_confidence === "ambiguous");
}

function isRevisionSegment(value: unknown): boolean {
  return isRevisionChange(value)
    && isRecord(value)
    && isNullableNumber(value.visual_distance) && isNullableNumber(value.audio_distance)
    && isNonnegativeNumber(value.match_confidence) && value.match_confidence <= 1;
}

function isRevisionKind(value: unknown): boolean {
  return value === "UNCHANGED" || value === "REMOVED" || value === "INSERTED" || value === "CHANGED";
}

function isClaimReviewSummary(value: unknown): value is ClaimReviewSummary {
  return isRecord(value)
    && (value.status === "disabled" || value.status === "no_claims" || value.status === "clean"
      || value.status === "inconclusive" || value.status === "needs_review" || value.status === "unavailable")
    && isNonnegativeNumber(value.claims_checked)
    && isNonnegativeNumber(value.supported_count)
    && isNonnegativeNumber(value.conflict_count)
    && isNonnegativeNumber(value.insufficient_evidence_count)
    && isNullableString(value.explanation);
}

function isReleaseBrief(value: unknown): boolean {
  return isRecord(value)
    && (value.source === "ai" || value.source === "deterministic" || value.source === "fallback")
    && typeof value.headline === "string"
    && typeof value.summary === "string"
    && Array.isArray(value.top_actions) && value.top_actions.length <= 3 && value.top_actions.every((item) => typeof item === "string")
    && isNullableString(value.positive_note);
}

function isMetadataAssistResult(value: unknown): value is MetadataAssistResult {
  return isRecord(value)
    && Array.isArray(value.title_suggestions) && value.title_suggestions.length === 5
    && value.title_suggestions.every((item) => typeof item === "string")
    && typeof value.description_draft === "string"
    && typeof value.cleanup_succeeded === "boolean";
}

function isViewerPassSummary(value: unknown): value is ViewerPassSummary {
  return isRecord(value)
    && (value.status === "disabled" || value.status === "clean"
      || value.status === "needs_review" || value.status === "not_evaluable"
      || value.status === "unavailable")
    && isNullableString(value.summary)
    && isNonnegativeNumber(value.issue_count);
}

function isAIReviewSummary(value: unknown): value is AIReviewSummary {
  return isRecord(value)
    && typeof value.enabled === "boolean"
    && typeof value.provider === "string"
    && typeof value.model === "string"
    && (value.status === "disabled" || value.status === "not_run" || value.status === "succeeded"
      || value.status === "unavailable" || value.status === "failed")
    && isNonnegativeNumber(value.observation_count)
    && isNullableNumber(value.runtime_seconds)
    && (value.cleanup_succeeded === null || typeof value.cleanup_succeeded === "boolean")
    && isNullableString(value.reason_code);
}

function isPromiseCheckSummary(value: unknown): value is PromiseCheckSummary {
  return isRecord(value)
    && (value.status === "disabled" || value.status === "aligned"
      || value.status === "needs_review" || value.status === "not_evaluable"
      || value.status === "unavailable")
    && isNullableString(value.inferred_promise)
    && isNullableNumber(value.first_substantive_address_seconds)
    && isNullableString(value.first_substantive_address_evidence)
    && (value.opening_alignment === null || value.opening_alignment === "direct_delivery"
      || value.opening_alignment === "relevant_hook" || value.opening_alignment === "relevant_setup"
      || value.opening_alignment === "unrelated_delay" || value.opening_alignment === "contradiction"
      || value.opening_alignment === "not_evaluable")
    && (value.overall_delivery === null || value.overall_delivery === "aligned"
      || value.overall_delivery === "partial" || value.overall_delivery === "mismatched"
      || value.overall_delivery === "not_evaluable")
    && isNullableString(value.explanation)
    && isNullableConfidence(value.confidence)
    && (value.thumbnail_alignment === null || value.thumbnail_alignment === "aligned"
      || value.thumbnail_alignment === "mismatched" || value.thumbnail_alignment === "not_evaluable");
}

function isCaptionSummary(value: unknown): value is CaptionSummary {
  return isRecord(value)
    && typeof value.source_format === "string"
    && isNonnegativeNumber(value.cue_count)
    && isNullableNumber(value.first_caption_seconds)
    && isNullableNumber(value.last_caption_seconds)
    && isNonnegativeNumber(value.covered_duration_seconds)
    && isNullablePercentage(value.timeline_coverage_percent);
}

function isFinding(value: unknown): value is Finding {
  if (!isRecord(value)) return false;
  return typeof value.code === "string"
    && (value.severity === "info" || value.severity === "warning" || value.severity === "error")
    && isFindingStatus(value.status)
    && typeof value.message === "string"
    && typeof value.source === "string"
    && isNullableNumber(value.timestamp_start_seconds)
    && isNullableNumber(value.timestamp_end_seconds)
    && (value.details === null || (isRecord(value.details) && isJsonObject(value.details)))
    && isNullableString(value.suggestion);
}

function isCheckResult(value: unknown): value is CheckResult {
  return isRecord(value)
    && typeof value.check_id === "string"
    && typeof value.passed === "boolean"
    && Array.isArray(value.finding_codes)
    && value.finding_codes.every((code) => typeof code === "string");
}

function isMediaInspection(value: unknown): value is MediaInspection {
  if (!isRecord(value)) return false;
  return isNullableNumber(value.duration_seconds)
    && isNullableString(value.format_name)
    && isNonnegativeNumber(value.file_size_bytes)
    && typeof value.has_video === "boolean"
    && isNonnegativeNumber(value.video_stream_count)
    && isNullableString(value.video_codec)
    && isNullableNumber(value.width)
    && isNullableNumber(value.height)
    && isNullableString(value.display_aspect_ratio)
    && isNullableNumber(value.frame_rate)
    && isNullableString(value.pixel_format)
    && typeof value.has_audio === "boolean"
    && isNonnegativeNumber(value.audio_stream_count)
    && isNullableString(value.audio_codec)
    && isNullableNumber(value.channel_count)
    && isNullableNumber(value.sample_rate);
}

function isFindingStatus(value: unknown): value is PreflightReport["verdict"] {
  return value === "READY" || value === "NEEDS_REVIEW" || value === "BLOCKED";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function isNonnegativeNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isNullablePercentage(value: unknown): value is number | null {
  return value === null || (isNonnegativeNumber(value) && value <= 100);
}

function isNullableConfidence(value: unknown): value is number | null {
  return value === null || (isNonnegativeNumber(value) && value <= 1);
}

function isJsonObject(value: Record<string, unknown>): boolean {
  return Object.values(value).every(isJsonValue);
}

function isJsonValue(value: unknown): boolean {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isRecord(value) && isJsonObject(value);
}

async function requestRepairMedia(
  endpoint: string,
  form: FormData,
  signal?: AbortSignal,
): Promise<RepairMediaResult> {
  let response: Response;
  try {
    response = await fetch(endpoint, { method: "POST", body: form, signal });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new PreflightApiError("Could not reach the local repair service.", {
      code: "backend_unreachable",
      cause: error,
    });
  }
  if (!response.ok) {
    const payload = await parseJsonResponse(response);
    const structured = parseStructuredError(payload);
    throw new PreflightApiError(
      structured?.error.message ?? `The repair request failed with HTTP ${response.status}.`,
      { code: structured?.error.code ?? "repair_request_failed", status: response.status },
    );
  }
  const blob = await response.blob();
  if (!blob.size || !response.headers.get("content-type")?.startsWith("video/mp4")) {
    throw new PreflightApiError("The backend returned an invalid repair video.", {
      code: "repair_response_invalid",
      status: response.status,
    });
  }
  return {
    blob,
    originalDurationSeconds: numericHeader(response, "X-Repair-Original-Duration"),
    outputDurationSeconds: numericHeader(response, "X-Repair-Output-Duration"),
    removedDurationSeconds: numericHeader(response, "X-Repair-Removed-Duration"),
  };
}

function numericHeader(response: Response, name: string): number | null {
  const raw = response.headers.get(name);
  if (raw === null) return null;
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 ? value : null;
}
