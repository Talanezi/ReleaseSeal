import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Download,
  Film,
  Headphones,
  MonitorPlay,
  ScanLine,
  Sparkles,
  Tag,
} from "lucide-react";
import type { Finding, FindingStatus, PreflightReport } from "../types/preflight";
import { RepairPanel } from "./RepairPanel";
import {
  findingCategory,
  findingTitle,
  formatBytes,
  formatDuration,
  formatInterval,
  formatTimecode,
} from "../utils/format";

interface ResultsViewProps {
  report: PreflightReport;
  filename?: string;
  previewUrl?: string | null;
  sourceFile?: File | null;
  packageInput?: { title: string; description: string; captions?: File | null; thumbnail?: File | null; reviewMode: "full" | "local" };
}

const verdictCopy: Record<FindingStatus, { label: string; description: string }> = {
  READY: { label: "Ready", description: "No issues requiring review were found." },
  NEEDS_REVIEW: { label: "Needs review", description: "Review the findings before you publish." },
  BLOCKED: { label: "Blocked", description: "Resolve the critical finding before you publish." },
};

const categoryIcons = {
  video: Film,
  audio: Headphones,
  package: Tag,
  captions: ScanLine,
  ai: ScanLine,
  editorial: ScanLine,
  claims: ScanLine,
};

export function ResultsView({
  report,
  filename = "creator-export-final.mp4",
  previewUrl,
  sourceFile = null,
  packageInput,
}: ResultsViewProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const pendingSeek = useRef<number | null>(null);
  const [repairedMedia, setRepairedMedia] = useState<{ file: File; duration: number | null } | null>(null);
  const [reviewReel, setReviewReel] = useState<File | null>(null);
  const [repairedUrl, setRepairedUrl] = useState<string | null>(null);
  const [reviewReelUrl, setReviewReelUrl] = useState<string | null>(null);
  const [mediaMode, setMediaMode] = useState<"original" | "repaired" | "reel">("original");
  const categories = useMemo(
    () => Array.from(new Set(report.findings.map(findingCategory))),
    [report.findings],
  );
  const [activeCategory, setActiveCategory] = useState("all");
  const selectedCategory =
    activeCategory === "all" || categories.includes(activeCategory) ? activeCategory : "all";
  const filteredFindings = report.findings.filter(
    (finding) => selectedCategory === "all" || findingCategory(finding) === selectedCategory,
  );

  useEffect(() => {
    if (!repairedMedia || typeof URL.createObjectURL !== "function") return setRepairedUrl(null);
    const url = URL.createObjectURL(repairedMedia.file);
    setRepairedUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [repairedMedia]);

  useEffect(() => {
    if (!reviewReel || typeof URL.createObjectURL !== "function") return setReviewReelUrl(null);
    const url = URL.createObjectURL(reviewReel);
    setReviewReelUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [reviewReel]);

  const activeMediaUrl = mediaMode === "repaired" ? repairedUrl : mediaMode === "reel" ? reviewReelUrl : previewUrl;
  const selectMedia = (mode: "original" | "repaired" | "reel", seconds?: number) => {
    pendingSeek.current = seconds ?? null;
    setMediaMode(mode);
    if (seconds !== undefined && mediaMode === mode && videoRef.current) {
      videoRef.current.currentTime = seconds;
      videoRef.current.focus({ preventScroll: true });
      pendingSeek.current = null;
    }
  };

  const seekTo = (finding: Finding) => {
    if (finding.timestamp_start_seconds === null) return;
    selectMedia("original", finding.timestamp_start_seconds);
  };
  const seekToSeconds = (seconds: number) => {
    selectMedia("original", seconds);
  };

  return (
    <main className="results page-frame" data-testid="result-state">
      <header className="result-overview">
        <div className="file-identity">
          <h1 title={filename}>{filename}</h1>
          <p>{mediaSummary(report)}</p>
        </div>
        <div className={`result-status verdict-${report.verdict.toLowerCase()}`}>
          <VerdictIcon verdict={report.verdict} />
          <div>
            <h2>{verdictCopy[report.verdict].label}</h2>
            <p>{verdictCopy[report.verdict].description}</p>
          </div>
        </div>
        <p className="result-counts" aria-label="Scan counts">
          <strong>{report.passed_check_count}</strong> passed
          <span aria-hidden="true">·</span>
          <strong>{report.warning_count}</strong> warnings
          <span aria-hidden="true">·</span>
          <strong>{report.critical_count}</strong> critical
        </p>
      </header>

      {report.scan_completeness !== "COMPLETE" && (
        <section className="scan-incomplete" aria-labelledby="scan-incomplete-title">
          <AlertCircle aria-hidden="true" />
          <div>
            <h2 id="scan-incomplete-title">Scan incomplete</h2>
            <p>
              Completed content checks found {report.verdict === "READY" ? "no release issue" : "the findings shown below"},
              but part of the requested review could not finish.
            </p>
            <ul>
              {report.execution_issues.map((issue) => (
                <li key={`${issue.component}-${issue.reason_code}`}>{executionIssueCopy(issue.component)}{issue.retryable ? " Try again shortly." : ""}</li>
              ))}
            </ul>
          </div>
        </section>
      )}

      <section className="release-brief" aria-labelledby="release-brief-title">
        <span><Sparkles aria-hidden="true" /> AI review</span>
        <h2 id="release-brief-title">{report.release_brief.headline}</h2>
        <p>{report.release_brief.summary}</p>
        {report.release_brief.top_actions.length > 0 && <ul>{report.release_brief.top_actions.map((action) => <li key={action}>{action}</li>)}</ul>}
        {report.release_brief.positive_note && <small><Check aria-hidden="true" /> {report.release_brief.positive_note}</small>}
      </section>

      {report.review_mode === "full" && <ReviewDetails report={report} />}

      <div className="review-workspace unified-workspace">
        <section className="media-review" aria-label="Video review">
          <div className="media-mode-tabs" role="tablist" aria-label="Video version">
            <button role="tab" aria-selected={mediaMode === "original"} onClick={() => selectMedia("original")}>Original</button>
            {repairedUrl && <button role="tab" aria-selected={mediaMode === "repaired"} onClick={() => selectMedia("repaired")}>Repaired</button>}
            {reviewReelUrl && <button role="tab" aria-selected={mediaMode === "reel"} onClick={() => selectMedia("reel")}>Review Reel</button>}
          </div>
          <div className="video-frame">
            {activeMediaUrl ? (
              <video ref={videoRef} data-testid="preview-video" data-media-mode={mediaMode} src={activeMediaUrl} controls preload="metadata" onLoadedMetadata={() => {
                if (pendingSeek.current !== null && videoRef.current) {
                  videoRef.current.currentTime = pendingSeek.current;
                  videoRef.current.focus({ preventScroll: true });
                  pendingSeek.current = null;
                }
              }} />
            ) : (
              <div className="video-placeholder">
                <MonitorPlay aria-hidden="true" />
                <strong>No local preview selected</strong>
                <span>Start a new scan with a local video to enable seeking.</span>
              </div>
            )}
          </div>

          <FindingsTimeline
            findings={report.findings}
            duration={report.media.duration_seconds}
            onSeek={seekTo}
          />
          <div className="media-downloads">
            {repairedUrl && repairedMedia && <a className="text-button" href={repairedUrl} download={repairedMedia.file.name}><Download aria-hidden="true" /> Download repaired video</a>}
            {reviewReelUrl && reviewReel && <a className="text-button" href={reviewReelUrl} download={reviewReel.name}><Download aria-hidden="true" /> Download Review Reel</a>}
          </div>
        </section>
      </div>

      <RepairPanel
        report={report}
        sourceFile={sourceFile}
        originalPreviewUrl={previewUrl}
        onSeek={seekToSeconds}
        onRepairedMedia={(file, duration) => { setRepairedMedia(file ? { file, duration } : null); if (!file) setMediaMode("original"); }}
        onReviewReelMedia={(file) => setReviewReel(file)}
        onSelectMedia={selectMedia}
        packageInput={packageInput}
      />

      <details className="all-findings">
        <summary>All findings and technical details</summary>
        <section className="findings-panel" aria-labelledby="findings-title">
          <div className="findings-header">
            <h2 id="findings-title">Findings</h2>
            <span>{filteredFindings.length} of {report.findings.length}</span>
          </div>

          {categories.length > 0 && (
            <div className="filters" aria-label="Filter findings by category">
              <button
                type="button"
                className={selectedCategory === "all" ? "is-active" : ""}
                aria-pressed={selectedCategory === "all"}
                onClick={() => setActiveCategory("all")}
              >
                All <span>{report.findings.length}</span>
              </button>
              {categories.map((category) => (
                <button
                  type="button"
                  key={category}
                  className={selectedCategory === category ? "is-active" : ""}
                  aria-pressed={selectedCategory === category}
                  onClick={() => setActiveCategory(category)}
                >
                  {capitalize(category)}
                  <span>{report.findings.filter((finding) => findingCategory(finding) === category).length}</span>
                </button>
              ))}
            </div>
          )}

          {filteredFindings.length ? (
            <div className="finding-list">
              {filteredFindings.map((finding) => (
                <FindingItem
                  key={`${finding.code}-${finding.timestamp_start_seconds ?? "global"}`}
                  finding={finding}
                  onSeek={seekTo}
                />
              ))}
            </div>
          ) : (
            <div className="empty-findings">
              <CheckCircle2 aria-hidden="true" />
              <h3>No findings requiring review</h3>
              <p>The checks in this report completed without warnings or critical issues.</p>
            </div>
          )}
          <CheckDetails report={report} />
        </section>
      </details>
    </main>
  );
}

function ClaimReviewSummaryView({ report }: { report: PreflightReport }) {
  const claims = report.claim_review;
  const labels = {
    disabled: "Not run",
    no_claims: "No significant claims found",
    clean: `${claims.claims_checked} checked · ${claims.supported_count} supported`,
    inconclusive: `${claims.claims_checked} checked · ${claims.insufficient_evidence_count} inconclusive`,
    needs_review: `${claims.claims_checked} checked · ${claims.conflict_count} to review`,
    unavailable: "Unavailable",
  } as const;
  return (
    <section className={`promise-summary claims-${claims.status}`} aria-labelledby="claim-review-title">
      <div>
        <h2 id="claim-review-title">Factual review</h2>
        <strong>{labels[claims.status]}</strong>
      </div>
      {claims.insufficient_evidence_count > 0 && (
        <p>{claims.insufficient_evidence_count} lacked enough grounded evidence.</p>
      )}
      {claims.status === "unavailable" && <p>Factual review could not finish.</p>}
    </section>
  );
}

function ReviewDetails({ report }: { report: PreflightReport }) {
  const actionable = report.promise_check.status === "needs_review"
    || report.viewer_pass.status === "needs_review"
    || report.claim_review.status === "needs_review"
    || report.promise_check.status === "unavailable"
    || report.viewer_pass.status === "unavailable"
    || report.claim_review.status === "unavailable";
  return (
    <details className="review-details" open={actionable || undefined}>
      <summary>Review details <span>{actionable ? "Needs attention" : "Opening, continuity, and facts checked"}</span></summary>
      <div className="ai-review-summaries" aria-label="Editorial review summaries">
        <PromiseSummary report={report} />
        <ViewerPassSummaryView report={report} />
        <ClaimReviewSummaryView report={report} />
      </div>
    </details>
  );
}

function ViewerPassSummaryView({ report }: { report: PreflightReport }) {
  const viewer = report.viewer_pass;
  const labels = {
    disabled: "Not run",
    clean: "No high-confidence inconsistencies found",
    needs_review: `${viewer.issue_count} ${viewer.issue_count === 1 ? "item" : "items"} to review`,
    not_evaluable: "Not evaluable",
    unavailable: "Unavailable",
  } as const;
  return (
    <section className={`promise-summary viewer-${viewer.status}`} aria-labelledby="viewer-pass-title">
      <div>
        <h2 id="viewer-pass-title">Continuity review</h2>
        <strong>{labels[viewer.status]}</strong>
      </div>
      {viewer.summary && viewer.status !== "unavailable" && <p>{viewer.summary}</p>}
      {viewer.status === "unavailable" && <p>Content review could not finish.</p>}
    </section>
  );
}

function PromiseSummary({ report }: { report: PreflightReport }) {
  const promise = report.promise_check;
  const labels = {
    disabled: "Not run",
    aligned: "Aligned",
    needs_review: "Needs review",
    not_evaluable: "Not evaluable",
    unavailable: "Unavailable",
  } as const;
  return (
    <section className={`promise-summary promise-${promise.status}`} aria-labelledby="promise-title">
      <div>
        <h2 id="promise-title">Opening review</h2>
        <strong>{labels[promise.status]}</strong>
      </div>
      {promise.inferred_promise && (
        <p><span>Promise</span>{promise.inferred_promise}</p>
      )}
      {promise.first_substantive_address_seconds !== null && (
        <p><span>Direct delivery</span><b>{formatTimecode(promise.first_substantive_address_seconds)}</b></p>
      )}
      {promise.opening_alignment && promise.opening_alignment !== "not_evaluable" && (
        <p><span>Opening</span>{capitalize(promise.opening_alignment.replaceAll("_", " "))}</p>
      )}
      {promise.thumbnail_alignment && (
        <p><span>Thumbnail</span>{capitalize(promise.thumbnail_alignment.replaceAll("_", " "))}</p>
      )}
      {!promise.inferred_promise && promise.explanation && promise.status !== "unavailable" && <p>{promise.explanation}</p>}
      {promise.status === "unavailable" && <p>Opening review could not finish.</p>}
    </section>
  );
}

function VerdictIcon({ verdict }: { verdict: FindingStatus }) {
  const Icon = verdict === "READY" ? CheckCircle2 : verdict === "BLOCKED" ? AlertCircle : AlertTriangle;
  return <Icon className="verdict-icon" aria-hidden="true" />;
}

function FindingsTimeline({ findings, duration, onSeek }: {
  findings: Finding[];
  duration: number | null;
  onSeek: (finding: Finding) => void;
}) {
  const timestamped = findings.filter(
    (finding) => finding.timestamp_start_seconds !== null && duration !== null && duration > 0,
  );
  return (
    <section className="timeline" aria-labelledby="timeline-title">
      <h2 id="timeline-title" className="visually-hidden">Findings timeline</h2>
      <div className="timeline-ruler" aria-hidden="true">
        <span>0:00</span>
        <span>{formatDuration(duration ? duration / 2 : null)}</span>
        <span>{formatDuration(duration)}</span>
      </div>
      <div className="timeline-track">
        {timestamped.map((finding, index) => {
          const start = finding.timestamp_start_seconds ?? 0;
          const left = duration ? Math.min(100, Math.max(0, (start / duration) * 100)) : 0;
          return (
            <button
              type="button"
              key={`${finding.code}-${start}`}
              className={`timeline-marker marker-${findingCategory(finding)} severity-${finding.severity}`}
              style={{ left: `${left}%`, top: `${8 + (index % 3) * 15}px` }}
              onClick={() => onSeek(finding)}
              aria-label={`Seek to ${findingTitle(finding)} at ${formatInterval(finding)}`}
              data-tooltip={`${findingTitle(finding)} · ${formatInterval(finding)}`}
            >
              <span />
            </button>
          );
        })}
      </div>
      <p className="timeline-caption">{timestamped.length} timed {timestamped.length === 1 ? "finding" : "findings"}</p>
    </section>
  );
}

function CheckDetails({ report }: { report: PreflightReport }) {
  return (
    <details className="check-details">
      <summary>
        <span>{report.checks_run_count} checks run · {report.passed_check_count} passed</span>
        <span>View details <ChevronDown aria-hidden="true" /></span>
      </summary>
      <ul>
        {report.checks.map((check) => (
          <li key={check.check_id} className={check.passed ? "is-pass" : "is-flagged"}>
            {check.passed ? <Check aria-hidden="true" /> : <AlertTriangle aria-hidden="true" />}
            <span>{humanizeCheck(check.check_id)}</span>
            <small>{check.passed ? "Passed" : check.finding_codes.length ? "Review" : "Incomplete"}</small>
          </li>
        ))}
      </ul>
    </details>
  );
}

function FindingItem({ finding, onSeek }: { finding: Finding; onSeek: (finding: Finding) => void }) {
  const category = findingCategory(finding);
  const CategoryIcon = categoryIcons[category as keyof typeof categoryIcons] ?? ScanLine;
  const interval = formatInterval(finding);
  const severityText = finding.status === "BLOCKED" ? "Critical finding" : "Warning";
  return (
    <article className={`finding-item severity-${finding.severity}`} data-category={category}>
      <span className="finding-severity" title={severityText}>
        {finding.status === "BLOCKED" ? <AlertCircle aria-hidden="true" /> : <AlertTriangle aria-hidden="true" />}
        <span className="visually-hidden">{severityText}:</span>
      </span>
      <div className="finding-content">
        <div className="finding-title-row">
          <h3>{findingTitle(finding)}</h3>
          {interval ? (
            <button type="button" className="timecode-button" onClick={() => onSeek(finding)}>
              <Clock3 aria-hidden="true" /> {interval}
            </button>
          ) : (
            <span className="finding-category"><CategoryIcon aria-hidden="true" />{capitalize(category)}</span>
          )}
        </div>
        <p className="finding-message">{finding.message}</p>
        {finding.suggestion && <p className="finding-suggestion">{finding.suggestion}</p>}
        <EvidenceDetails finding={finding} />
        <FindingSources finding={finding} />
      </div>
    </article>
  );
}

function FindingSources({ finding }: { finding: Finding }) {
  const raw = finding.details?.sources;
  if (!Array.isArray(raw)) return null;
  const sources = raw.filter((item): item is { title: string; url: string } => {
    if (typeof item !== "object" || item === null || Array.isArray(item)) return false;
    const source = item as Record<string, unknown>;
    return typeof source.title === "string" && typeof source.url === "string"
      && (source.url.startsWith("https://") || source.url.startsWith("http://"));
  });
  if (!sources.length) return null;
  return (
    <div className="finding-sources" aria-label="Grounded sources">
      {sources.map((source) => (
        <a key={source.url} href={source.url} target="_blank" rel="noreferrer noopener">
          {source.title}
        </a>
      ))}
    </div>
  );
}

function EvidenceDetails({ finding }: { finding: Finding }) {
  const evidence = evidenceEntries(finding);
  if (!evidence.length) return null;
  return (
    <details className="evidence-details">
      <summary>Technical details <ChevronDown aria-hidden="true" /></summary>
      <dl>
        {evidence.map(([label, value]) => (
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
        ))}
      </dl>
    </details>
  );
}

function evidenceEntries(finding: Finding): Array<[string, string]> {
  const details = finding.details;
  if (!details) return [];
  const evidence: Array<[string, string]> = [];
  if (typeof details.duration_seconds === "number") evidence.push(["Duration", `${details.duration_seconds.toFixed(2)} sec`]);
  if (typeof details.minimum_duration_seconds === "number") evidence.push(["Warning threshold", `${details.minimum_duration_seconds.toFixed(2)} sec`]);
  if (typeof details.measured_peak_dbfs === "number") evidence.push(["Measured peak", `${details.measured_peak_dbfs.toFixed(1)} dBFS`]);
  if (typeof details.warning_threshold_dbfs === "number") evidence.push(["Warning threshold", `${details.warning_threshold_dbfs.toFixed(1)} dBFS`]);
  if (typeof details.near_full_scale_sample_fraction === "number") evidence.push(["Near-full-scale samples", `${(details.near_full_scale_sample_fraction * 100).toFixed(2)}%`]);
  if (typeof details.minimum_near_full_scale_sample_fraction === "number") evidence.push(["Sample-density threshold", `${(details.minimum_near_full_scale_sample_fraction * 100).toFixed(2)}%`]);
  if (typeof details.character_count === "number") evidence.push(["Title length", `${details.character_count} characters`]);
  if (typeof details.maximum_recommended_length === "number") evidence.push(["Recommended maximum", `${details.maximum_recommended_length} characters`]);
  if (typeof details.actual_height === "number") evidence.push(["Actual height", `${details.actual_height}px`]);
  if (typeof details.minimum_height === "number") evidence.push(["Minimum height", `${details.minimum_height}px`]);
  if (typeof details.maximum_uncovered_gap_seconds === "number") evidence.push(["Gap threshold", `${details.maximum_uncovered_gap_seconds.toFixed(2)} sec`]);
  if (typeof details.boundary_tolerance_seconds === "number") evidence.push(["Boundary tolerance", `${details.boundary_tolerance_seconds.toFixed(2)} sec`]);
  if (typeof details.media_duration_seconds === "number") evidence.push(["Media duration", `${details.media_duration_seconds.toFixed(2)} sec`]);
  if (typeof details.confidence === "number") evidence.push(["AI confidence", `${Math.round(details.confidence * 100)}%`]);
  if (typeof details.inferred_promise === "string") evidence.push(["Inferred promise", details.inferred_promise]);
  if (typeof details.direct_delivery_seconds === "number") evidence.push(["Direct delivery", formatTimecode(details.direct_delivery_seconds)]);
  if (typeof details.spoken_evidence === "string") evidence.push(["Spoken evidence", details.spoken_evidence]);
  if (typeof details.visible_evidence === "string") evidence.push(["Visible evidence", details.visible_evidence]);
  if (typeof details.original_start_seconds === "number") {
    const end = typeof details.original_end_seconds === "number" ? details.original_end_seconds : details.original_start_seconds;
    evidence.push(["Original interval", `${formatTimecode(details.original_start_seconds)}–${formatTimecode(end)}`]);
  }
  return evidence;
}

function mediaSummary(report: PreflightReport): string {
  const media = report.media;
  const frame = media.width !== null && media.height !== null ? `${media.width} × ${media.height}` : "Unknown size";
  const video = formatCodec(media.video_codec);
  const audio = formatCodec(media.audio_codec);
  const frameRate = media.frame_rate !== null ? `${media.frame_rate} fps` : "Unknown frame rate";
  const duration = media.duration_seconds !== null && media.duration_seconds < 60
    ? `${Math.round(media.duration_seconds)} sec`
    : formatDuration(media.duration_seconds);
  return `${frame} · ${video} · ${audio} · ${frameRate} · ${duration} · ${formatBytes(media.file_size_bytes)}`;
}

function formatCodec(codec: string | null): string {
  if (!codec) return "No stream";
  if (codec.toLowerCase() === "h264") return "H.264";
  if (codec.toLowerCase() === "h265" || codec.toLowerCase() === "hevc") return "H.265";
  return codec.toUpperCase();
}

function humanizeCheck(value: string): string {
  return value.split(".").map((part) => part.replaceAll("_", " ")).join(" · ");
}

function capitalize(value: string): string {
  if (value === "ai") return "AI";
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function executionIssueCopy(component: string): string {
  if (component.includes("claims")) return "Factual review could not finish.";
  if (component.includes("promise")) return "Promise review could not finish.";
  if (component.includes("viewer")) return "Content review could not finish.";
  if (component.startsWith("ai.")) return "AI review could not finish.";
  if (component.includes("transcription")) return "Speech and caption comparison could not finish.";
  return "Part of the requested review could not finish.";
}
