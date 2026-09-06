export type FindingSeverity = "info" | "warning" | "error";
export type FindingStatus = "READY" | "NEEDS_REVIEW" | "BLOCKED";
export type ReviewMode = "full" | "local";

export type ScanProgressState = "RUNNING" | "COMPLETE" | "PARTIAL" | "FAILED";
export type ScanProgressStage = "receiving_media" | "preparing_media" | "technical_checks"
  | "preparing_ai_media" | "opening_review" | "continuity_review" | "factual_review"
  | "preparing_review" | "final_report" | "complete" | "failed";

export interface ScanProgressTask {
  task_id: string;
  label: string;
  status: "Done" | "Working" | "Waiting" | "Unavailable";
}

export interface ScanProgress {
  progress_id: string;
  review_mode: ReviewMode;
  state: ScanProgressState;
  stage: ScanProgressStage;
  percent: number;
  message: string;
  created_at_epoch_seconds: number;
  updated_at_epoch_seconds: number;
  tasks: ScanProgressTask[];
}
export type ScanCompleteness = "COMPLETE" | "PARTIAL" | "FAILED";

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface Finding {
  code: string;
  severity: FindingSeverity;
  status: FindingStatus;
  message: string;
  source: string;
  timestamp_start_seconds: number | null;
  timestamp_end_seconds: number | null;
  details: Record<string, JsonValue> | null;
  suggestion: string | null;
}

export interface MediaInspection {
  duration_seconds: number | null;
  format_name: string | null;
  file_size_bytes: number;
  has_video: boolean;
  video_stream_count: number;
  video_codec: string | null;
  width: number | null;
  height: number | null;
  display_aspect_ratio: string | null;
  frame_rate: number | null;
  pixel_format: string | null;
  has_audio: boolean;
  audio_stream_count: number;
  audio_codec: string | null;
  channel_count: number | null;
  sample_rate: number | null;
}

export interface CheckResult {
  check_id: string;
  passed: boolean;
  finding_codes: string[];
}

export interface CaptionSummary {
  source_format: string;
  cue_count: number;
  first_caption_seconds: number | null;
  last_caption_seconds: number | null;
  covered_duration_seconds: number;
  timeline_coverage_percent: number | null;
}

export type AIReviewStatus = "disabled" | "not_run" | "succeeded" | "unavailable" | "failed";

export interface AIReviewSummary {
  enabled: boolean;
  provider: string;
  model: string;
  status: AIReviewStatus;
  observation_count: number;
  runtime_seconds: number | null;
  cleanup_succeeded: boolean | null;
  reason_code: string | null;
}

export interface ExecutionIssue {
  component: string;
  reason_code: string;
  message: string;
  retryable: boolean;
}

export interface CapabilityReason {
  code: string;
  message: string;
}

export interface PreflightCapabilities {
  ffprobe_available: boolean;
  ffmpeg_available: boolean;
  gemini_dependency_available: boolean;
  gemini_api_key_configured: boolean;
  full_review_available: boolean;
  metadata_assist_available: boolean;
  local_checks_available: boolean;
  transcription_dependency_available: boolean;
  transcription_enabled: boolean;
  supported_review_modes: ReviewMode[];
  maximum_video_upload_size_bytes: number;
  full_review_unavailable_reasons: CapabilityReason[];
}

export type PromiseCheckStatus = "disabled" | "aligned" | "needs_review" | "not_evaluable" | "unavailable";

export interface PromiseCheckSummary {
  status: PromiseCheckStatus;
  inferred_promise: string | null;
  first_substantive_address_seconds: number | null;
  first_substantive_address_evidence: string | null;
  opening_alignment: "direct_delivery" | "relevant_hook" | "relevant_setup" | "unrelated_delay" | "contradiction" | "not_evaluable" | null;
  overall_delivery: "aligned" | "partial" | "mismatched" | "not_evaluable" | null;
  explanation: string | null;
  confidence: number | null;
  thumbnail_alignment: "aligned" | "mismatched" | "not_evaluable" | null;
}

export type ViewerPassStatus = "disabled" | "clean" | "needs_review" | "not_evaluable" | "unavailable";

export interface ViewerPassSummary {
  status: ViewerPassStatus;
  summary: string | null;
  issue_count: number;
}

export type ClaimReviewStatus = "disabled" | "no_claims" | "clean" | "inconclusive" | "needs_review" | "unavailable";

export interface ClaimReviewSummary {
  status: ClaimReviewStatus;
  claims_checked: number;
  supported_count: number;
  conflict_count: number;
  insufficient_evidence_count: number;
  explanation: string | null;
}

export type Repairability = "SAFE" | "PREVIEW_REQUIRED" | "HUMAN_ONLY";
export type RepairOperationType = "REMOVE_RANGE";

export interface RepairOperation {
  operation_type: RepairOperationType;
  start_seconds: number;
  end_seconds: number;
}

export interface RepairProposal {
  proposal_id: string;
  finding_code: string;
  finding_title: string;
  explanation: string;
  source: string;
  repairability: Repairability;
  operation: RepairOperation | null;
  start_seconds: number | null;
  end_seconds: number | null;
  expected_duration_change_seconds: number | null;
  original_start_seconds: number | null;
  original_end_seconds: number | null;
  evidence: Record<string, JsonValue> | null;
}

export interface RepairPlan {
  proposals: RepairProposal[];
  safe_count: number;
  preview_required_count: number;
  human_only_count: number;
}

export interface ReleaseBrief {
  source: "ai" | "deterministic" | "fallback";
  headline: string;
  summary: string;
  top_actions: string[];
  positive_note: string | null;
}

export interface MetadataAssistResult {
  title_suggestions: string[];
  description_draft: string;
  cleanup_succeeded: boolean;
}

export interface PreflightReport {
  schema_version: string;
  verdict: FindingStatus;
  scan_completeness: ScanCompleteness;
  review_mode: ReviewMode;
  execution_issues: ExecutionIssue[];
  media: MediaInspection;
  findings: Finding[];
  checks: CheckResult[];
  checks_run_count: number;
  passed_check_count: number;
  warning_count: number;
  critical_count: number;
  configuration_profile: string;
  configuration_source: string | null;
  caption_summary: CaptionSummary | null;
  ai_review: AIReviewSummary;
  promise_check: PromiseCheckSummary;
  viewer_pass: ViewerPassSummary;
  claim_review: ClaimReviewSummary;
  repair_plan: RepairPlan;
  release_brief: ReleaseBrief;
  scan_duration_seconds: number;
}

export type RepairVerificationStatus = "VERIFIED" | "NEEDS_REVIEW" | "INCOMPLETE";
export type FindingComparisonStatus = "RESOLVED" | "REMAINING" | "NEW";

export interface FindingComparison {
  status: FindingComparisonStatus;
  original_finding: Finding | null;
  repaired_finding: Finding | null;
  expected_repaired_start_seconds: number | null;
  expected_repaired_end_seconds: number | null;
  deterministically_verified: boolean;
  explanation: string;
}

export interface RepairIntegrityResult {
  passed: boolean;
  duration_matches: boolean;
  streams_match: boolean;
  resolution_matches: boolean;
  operations_verified: number;
  reference_intervals_survived: boolean;
  explanation: string;
}

export interface UnexpectedChangeInterval {
  start_seconds: number;
  end_seconds: number;
  maximum_mean_difference: number;
  sample_count: number;
}

export interface ReviewReelEntry {
  reel_start_seconds: number;
  reel_end_seconds: number;
  source_start_seconds: number;
  source_end_seconds: number;
  reason: string;
  category: string;
  source_id: string | null;
}

export interface ReviewReelManifest {
  entries: ReviewReelEntry[];
  total_duration_seconds: number;
}

export interface VerificationReport {
  schema_version: string;
  status: RepairVerificationStatus;
  approved_repair_count: number;
  resolved: FindingComparison[];
  remaining: FindingComparison[];
  new: FindingComparison[];
  unexpected_changes: UnexpectedChangeInterval[];
  original_duration_seconds: number;
  repaired_duration_seconds: number;
  expected_duration_seconds: number;
  integrity: RepairIntegrityResult;
  repaired_preflight_report: PreflightReport;
  regression_analysis_completeness: ScanCompleteness;
  review_reel_manifest: ReviewReelManifest;
  review_reel_available: boolean;
  limitations: string[];
}
