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
  release_contract_extraction_available: boolean;
  local_checks_available: boolean;
  revision_check_available: boolean;
  revision_semantic_review_available: boolean;
  transcription_dependency_available: boolean;
  transcription_enabled: boolean;
  local_evidence_recovery_available: boolean;
  supported_review_modes: ReviewMode[];
  maximum_video_upload_size_bytes: number;
  full_review_unavailable_reasons: CapabilityReason[];
}

export type ReleaseRequirementType = "REQUIRED_TEXT" | "REQUIRED_EXACT_TOKEN" | "REQUIRED_URL"
  | "REQUIRED_BEFORE_TIME" | "FORBIDDEN_TEXT" | "TITLE_CONTAINS" | "DESCRIPTION_CONTAINS"
  | "DESCRIPTION_URL" | "MAX_DURATION" | "MIN_RESOLUTION" | "ASPECT_RATIO"
  | "CAPTIONS_REQUIRED" | "THUMBNAIL_REQUIRED" | "REQUIRED_TALKING_POINT" | "FORBIDDEN_CLAIM";
export type ContractEvaluationClass = "DETERMINISTIC" | "SEMANTIC";
export type ContractStatus = "PASS" | "FAIL" | "NEEDS_REVIEW" | "NOT_EVALUATED";

export interface ReleaseRequirement {
  id: string;
  type: ReleaseRequirementType;
  instruction: string;
  provenance: "manual" | "extracted";
  source_excerpt: string | null;
  evaluation_class: ContractEvaluationClass;
  value?: string;
  before_seconds?: number;
  maximum_seconds?: number;
  minimum_width?: number;
  minimum_height?: number;
  width_ratio?: number;
  height_ratio?: number;
  tolerance?: number;
}

export interface ReleaseContract {
  schema_version: "1.0";
  name: string | null;
  requirements: ReleaseRequirement[];
}

export interface ContractRequirementResult {
  requirement_id: string;
  requirement_type: ReleaseRequirementType;
  instruction: string;
  evaluation_class: ContractEvaluationClass;
  status: ContractStatus;
  expected: string | null;
  evidence: string;
  evidence_source: "SUPPLIED_CAPTIONS" | "PUBLISHING_METADATA" | "MEDIA_MEASUREMENT" | "LOCAL_MACHINE_TRANSCRIPT" | "HUMAN_CONFIRMED_AUDIO_EVIDENCE" | "AI_SEMANTIC" | "NONE";
  timestamp_seconds: number | null;
  confidence: number | null;
  reason_code: string | null;
  audio_evidence: ContractAudioEvidence | null;
}

export interface ContractAudioEvidence {
  artifact_sha256: string;
  start_seconds: number;
  end_seconds: number;
  proposition: string;
  machine_text: string | null;
  transcription_engine: string | null;
  transcription_model: string | null;
  confirmation_id: string | null;
  confirmed_at: string | null;
}

export interface MachineEvidenceCandidate {
  candidate_id: string;
  artifact_sha256: string;
  requirement_id: string;
  requirement_sha256: string;
  requirement_type: "REQUIRED_TEXT" | "REQUIRED_EXACT_TOKEN" | "REQUIRED_BEFORE_TIME" | "FORBIDDEN_TEXT";
  proposition: string;
  expected_value: string;
  start_seconds: number;
  end_seconds: number;
  machine_text: string;
  confidence: number | null;
  engine: "faster-whisper";
  model: string;
  evidence_source: "LOCAL_MACHINE_TRANSCRIPT";
}

export interface HumanAudioConfirmation {
  confirmation_id: string;
  artifact_sha256: string;
  requirement_id: string;
  requirement_sha256: string;
  requirement_type: MachineEvidenceCandidate["requirement_type"];
  proposition: string;
  confirmed_value: string;
  start_seconds: number;
  end_seconds: number;
  confirmed_at: string;
  evidence_source: "HUMAN_CONFIRMED_AUDIO_EVIDENCE";
}

export interface AudioEvidenceState {
  status: "NOT_NEEDED" | "COMPLETED" | "UNAVAILABLE";
  reason: string;
  artifact_sha256: string | null;
  engine: string | null;
  model: string | null;
  transcript_character_count: number;
  transcript_truncated: boolean;
  candidates: MachineEvidenceCandidate[];
  confirmations: HumanAudioConfirmation[];
  runtime_seconds: number;
}

export type ReleasePlanCategory = "BLOCKING_REQUIREMENT" | "SAFE_AUTOMATION" | "CONFIRM_EVIDENCE" | "HUMAN_REVIEW" | "INFORMATIONAL";

export interface ReleasePlan {
  items: Array<{ item_id: string; category: ReleasePlanCategory; title: string; reference_id: string | null; timestamp_seconds: number | null }>;
  blocking_requirement_count: number;
  safe_automation_count: number;
  confirm_evidence_count: number;
  human_review_count: number;
  informational_count: number;
}

export interface ReleaseContractEvaluation {
  contract: ReleaseContract | null;
  results: ContractRequirementResult[];
  passed_count: number;
  failed_count: number;
  needs_review_count: number;
  not_evaluated_count: number;
  runtime_seconds: number;
}

export type PackageComponentState = "PRESENT_VALID" | "PRESENT_INVALID" | "ABSENT" | "NOT_REQUIRED";

export interface PackageComponent {
  state: PackageComponentState;
  detail: string;
}

export interface ThumbnailDeliveryCheck {
  check_id: string;
  label: string;
  status: "PASS" | "NEEDS_REVIEW";
  measured: string;
  expected: string;
}

export interface DeliveryPreviewSurface {
  surface_id: string;
  label: string;
  display_width: number;
  display_height: number;
  safe_margin_fraction: number;
  badge_x: number;
  badge_y: number;
  badge_width: number;
  badge_height: number;
}

export interface DeliveryPreviewMetadata {
  duration_badge_text: string | null;
  surfaces: DeliveryPreviewSurface[];
  critical_region_intersections: Array<{
    region_label: string;
    surface_id: string;
    intersects_duration_badge: boolean;
    intersects_unsafe_edge: boolean;
  }>;
}

export type ThumbnailAssuranceStatus = "CLEAR" | "NEEDS_REVIEW" | "NOT_EVALUATED";

export interface ThumbnailAssuranceBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ThumbnailTextRegion {
  region_id: string;
  evidence_class: "MEASURED" | "ADVISORY" | "NOT_EVALUATED";
  box: ThumbnailAssuranceBox;
  source_x: number;
  source_y: number;
  source_width: number;
  source_height: number;
  estimated_cap_height_pixels: number;
  confidence: number;
  estimated_local_contrast_ratio: number;
  contrast_evidence_confidence: number;
}

export interface DeliveredTextMeasurement {
  region_id: string;
  evidence_class: "MEASURED" | "ADVISORY" | "NOT_EVALUATED";
  surface_id: string;
  delivered_height_pixels: number;
  status: ThumbnailAssuranceStatus;
  badge_overlap_fraction: number;
  edge_safety: "CLEAR" | "NEAR_EDGE" | "INTERSECTS_UNSAFE_AREA";
}

export interface ThumbnailSurfaceAssurance {
  surface_id: string;
  evidence_class: "MEASURED" | "ADVISORY" | "NOT_EVALUATED";
  label: string;
  display_width: number;
  display_height: number;
  unreadable_text_area_share: number | null;
  detail_retention_ratio: number;
  detail_status: ThumbnailAssuranceStatus;
}

export interface ThumbnailAssuranceReport {
  schema_version: string;
  evidence_class: "MEASURED" | "ADVISORY" | "NOT_EVALUATED";
  status: ThumbnailAssuranceStatus;
  source_width: number;
  source_height: number;
  analysis_width: number;
  analysis_height: number;
  confident_region_count: number;
  regions: ThumbnailTextRegion[];
  delivered_text: DeliveredTextMeasurement[];
  surfaces: ThumbnailSurfaceAssurance[];
  minimum_region_confidence: number;
  minimum_delivered_text_height_pixels: number;
  minimum_estimated_contrast_ratio: number;
  minimum_detail_retention_ratio: number;
  reason: string;
  finding_codes: string[];
  decode_seconds: number;
  text_detection_seconds: number;
  contrast_seconds: number;
  detail_seconds: number;
  total_seconds: number;
}

export interface ReleasePackageSummary {
  video: PackageComponent;
  thumbnail: PackageComponent;
  captions: PackageComponent;
  title: PackageComponent;
  description: PackageComponent;
  chapters: PackageComponent;
  release_contract: PackageComponent;
  thumbnail_mime_type: string | null;
  thumbnail_file_size_bytes: number | null;
  thumbnail_width: number | null;
  thumbnail_height: number | null;
  thumbnail_checks: ThumbnailDeliveryCheck[];
  delivery_preview: DeliveryPreviewMetadata | null;
  thumbnail_assurance: ThumbnailAssuranceReport | null;
  construction_seconds: number;
  thumbnail_evaluation_seconds: number;
  preview_metadata_seconds: number;
}

export type RevisionSegmentKind = "UNCHANGED" | "REMOVED" | "INSERTED" | "CHANGED";
export type RevisionRequestStatus = "CHANGE_DETECTED" | "NO_CHANGE_DETECTED" | "NEEDS_LOCATION";

export interface RevisionStreamSummary {
  width: number;
  height: number;
  video_codec: string | null;
  has_audio: boolean;
  audio_codec: string | null;
}

export interface RevisionSegment {
  segment_id: string;
  kind: RevisionSegmentKind;
  previous_start_seconds: number | null;
  previous_end_seconds: number | null;
  revised_start_seconds: number | null;
  revised_end_seconds: number | null;
  visual_distance: number | null;
  audio_distance: number | null;
  visual_changed: boolean;
  audio_changed: boolean;
  match_confidence: number;
  boundary_confidence: "high" | "approximate" | "ambiguous";
}

export interface RevisionMap {
  schema_version: string;
  previous_sha256: string;
  revised_sha256: string;
  previous_duration_seconds: number;
  revised_duration_seconds: number;
  previous_streams: RevisionStreamSummary;
  revised_streams: RevisionStreamSummary;
  sampling_policy: Record<string, number>;
  previous_sample_count: number;
  revised_sample_count: number;
  estimated_unchanged_duration_seconds: number;
  unchanged_ratio: number;
  unchanged_ratio_basis: "previous_duration";
  segments: RevisionSegment[];
  ambiguity_notes: string[];
  analysis_runtime_seconds: number;
  identical_file_fast_path: boolean;
}

export interface RevisionRequest {
  request_id: string;
  source_line: number;
  text: string;
  previous_start_seconds: number | null;
  previous_end_seconds: number | null;
  explicit_range: boolean;
  status: RevisionRequestStatus;
  matched_segment_ids: string[];
  evidence: string;
}

export interface AdditionalRevisionChange {
  segment_id: string;
  kind: RevisionSegmentKind;
  previous_start_seconds: number | null;
  previous_end_seconds: number | null;
  revised_start_seconds: number | null;
  revised_end_seconds: number | null;
  visual_changed: boolean;
  audio_changed: boolean;
  boundary_confidence: "high" | "approximate" | "ambiguous";
}

export interface RevisionCheckReport {
  schema_version: string;
  previous_filename: string;
  revised_filename: string;
  revision_map: RevisionMap;
  revision_requests: RevisionRequest[];
  requested_change_count: number;
  requested_changes_detected_count: number;
  requested_changes_not_detected_count: number;
  requests_needing_location_count: number;
  additional_changes: AdditionalRevisionChange[];
  additional_change_count: number;
  analysis_runtime_seconds: number;
}

export type RevisionSemanticStatus = "APPEARS_SATISFIED" | "APPEARS_UNRESOLVED" | "INCONCLUSIVE" | "NOT_REVIEWED";

export interface RevisionEvidenceRange {
  start_seconds: number;
  end_seconds: number;
}

export interface RevisionSemanticResult {
  request_id: string;
  status: RevisionSemanticStatus;
  confidence: number | null;
  rationale: string;
  observed_previous: string | null;
  observed_revised: string | null;
  reviewed_previous_range: RevisionEvidenceRange | null;
  reviewed_revised_range: RevisionEvidenceRange | null;
  partial_evidence: boolean;
  limitation: string | null;
  reason_code: string | null;
}

export interface RevisionSemanticReviewReport {
  schema_version: string;
  provider: string;
  model: string;
  eligible_count: number;
  requested_count: number;
  reviewed_count: number;
  appears_satisfied_count: number;
  appears_unresolved_count: number;
  inconclusive_count: number;
  not_reviewed_count: number;
  results: RevisionSemanticResult[];
  evidence_render_seconds: number;
  provider_seconds: number;
  total_seconds: number;
  upload_count: number;
  generation_count: number;
  delete_count: number;
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
  release_package: ReleasePackageSummary;
  release_contract: ReleaseContractEvaluation;
  audio_evidence: AudioEvidenceState;
  repair_plan: RepairPlan;
  release_plan: ReleasePlan;
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

export type ReceiptKind = "FINAL_EXPORT" | "REVISION";

export interface ArtifactIdentity {
  sha256: string;
  size_bytes: number;
}

export interface FinalExportReceipt {
  receipt_schema_version: "1.0";
  receipt_kind: "FINAL_EXPORT";
  created_at: string;
  scanner_version: string;
  verdict: FindingStatus;
  scan_completeness: ScanCompleteness;
  configuration_fingerprint_sha256: string;
  package: {
    shipping_video: ArtifactIdentity;
    shipping_role: "ORIGINAL" | "REPAIRED";
    package_fingerprint_sha256: string;
  };
  repair: Record<string, unknown> | null;
  receipt_content_sha256: string;
}

export interface RevisionReceipt {
  receipt_schema_version: "1.0";
  receipt_kind: "REVISION";
  created_at: string;
  scanner_version: string;
  verdict: "NOT_APPLICABLE";
  scan_completeness: "COMPLETE";
  configuration_fingerprint_sha256: string;
  previous_video: ArtifactIdentity;
  revised_video: ArtifactIdentity;
  revision_notes_sha256: string;
  revision_fingerprint_sha256: string;
  receipt_content_sha256: string;
}
