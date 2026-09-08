import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Circle,
  Download,
  Film,
  Headphones,
  MonitorPlay,
  ScanLine,
  Sparkles,
  Tag,
} from "lucide-react";
import type { Finding, FindingStatus, GeneratedCaptionDraft, PreflightReport } from "../types/preflight";
import { confirmAudioEvidence, createFinalExportReceipt, errorPresentation, generateLocalCaptions, recoverAudioEvidence } from "../api/preflight";
import { exportReport, RepairPanel } from "./RepairPanel";
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
  evidenceRecoveryAvailable?: boolean;
  captionGenerationAvailable?: boolean;
  onReportUpdate?: (report: PreflightReport) => void;
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
  evidenceRecoveryAvailable = false,
  captionGenerationAvailable = false,
  onReportUpdate,
  packageInput,
}: ResultsViewProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const pendingSeek = useRef<number | null>(null);
  const [repairedMedia, setRepairedMedia] = useState<{ file: File; duration: number | null } | null>(null);
  const [reviewReel, setReviewReel] = useState<File | null>(null);
  const [repairedUrl, setRepairedUrl] = useState<string | null>(null);
  const [reviewReelUrl, setReviewReelUrl] = useState<string | null>(null);
  const [mediaMode, setMediaMode] = useState<"original" | "repaired" | "reel">("original");
  const [generatedCaptions, setGeneratedCaptions] = useState<GeneratedCaptionDraft | null>(null);
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
          <strong>{report.passed_check_count}</strong> checks passed
          <span aria-hidden="true">·</span>
          <strong>{report.warning_count}</strong> review findings
          <span aria-hidden="true">·</span>
          <strong>{report.critical_count}</strong> critical findings
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
        <span><Sparkles aria-hidden="true" /> Review summary</span>
        <h2 id="release-brief-title">{report.release_brief.headline}</h2>
        <p>{report.release_brief.summary}</p>
        {report.release_brief.top_actions.length > 0 && <ul>{report.release_brief.top_actions.map((action) => <li key={action}>{action}</li>)}</ul>}
        {report.release_brief.positive_note && (
          <small className={report.claim_review.status === "inconclusive" ? "release-note-neutral" : undefined}>
            {report.claim_review.status === "inconclusive" ? <Circle aria-hidden="true" /> : <Check aria-hidden="true" />}
            {report.release_brief.positive_note}
          </small>
        )}
      </section>

      <ReleasePackageResults report={report} thumbnail={packageInput?.thumbnail ?? null} />

      {!packageInput?.captions && (
        <GeneratedCaptionsAction
          sourceFile={sourceFile}
          hasAudio={report.media.has_audio}
          available={captionGenerationAvailable}
          draft={generatedCaptions}
          onDraft={setGeneratedCaptions}
        />
      )}

      {report.release_contract.contract && (
        <ReleaseRequirementsResults
          report={report}
          sourceFile={sourceFile}
          recoveryAvailable={evidenceRecoveryAvailable}
          generatedCaptions={generatedCaptions}
          onReportUpdate={onReportUpdate}
          onSeek={seekToSeconds}
        />
      )}

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
      {report.repair_plan.proposals.length === 0 && report.release_plan.items.length === 0 && (
        <OriginalReceiptAction report={report} sourceFile={sourceFile} packageInput={packageInput} />
      )}

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

function ReleasePackageResults({ report, thumbnail }: { report: PreflightReport; thumbnail: File | null }) {
  const [thumbnailUrl, setThumbnailUrl] = useState<string | null>(null);
  const [showSafeArea, setShowSafeArea] = useState(false);
  const [showTextRegions, setShowTextRegions] = useState(false);
  const [showDurationBadge, setShowDurationBadge] = useState(true);
  const [showFlaggedRegions, setShowFlaggedRegions] = useState(false);
  const summary = report.release_package;
  const assurance = summary.thumbnail_assurance;
  useEffect(() => {
    if (!thumbnail || typeof URL.createObjectURL !== "function") {
      setThumbnailUrl(null);
      return;
    }
    const url = URL.createObjectURL(thumbnail);
    setThumbnailUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [thumbnail]);
  const components = [
    ["Video", summary.video], ["Thumbnail", summary.thumbnail], ["Captions", summary.captions],
    ["Title", summary.title], ["Description", summary.description], ["Chapters", summary.chapters],
    ["Release requirements", summary.release_contract],
  ] as const;
  return (
    <section className="release-package" aria-labelledby="release-package-title">
      <div className="release-package-heading">
        <div><span>Delivery checklist</span><h2 id="release-package-title">Release package</h2></div>
      </div>
      <ul className="package-components">
        {components.map(([label, component]) => (
          <li key={label} className={`package-${component.state.toLowerCase()}`}>
            {component.state === "PRESENT_VALID" ? <Check aria-hidden="true" /> : component.state === "PRESENT_INVALID" ? <AlertTriangle aria-hidden="true" /> : <Circle aria-hidden="true" />}
            <span><strong>{label}</strong><small>{component.detail}</small></span>
          </li>
        ))}
      </ul>
      {summary.thumbnail_checks.length > 0 && <div className="thumbnail-checks" aria-label="Thumbnail delivery checks">{summary.thumbnail_checks.map((check) => <p key={check.check_id} className={check.status === "PASS" ? "is-pass" : "is-review"}><strong>{check.label}</strong><span>{check.measured}</span></p>)}</div>}
      {assurance && <div className="thumbnail-assurance" aria-label="Thumbnail delivery assurance">
        <div className="thumbnail-assurance-heading"><div><h3>Thumbnail delivery assurance</h3><p>{assurance.status === "NOT_EVALUATED" ? "No reliable text region was found." : assurance.reason}</p></div><strong className={`assurance-${assurance.status.toLowerCase()}`}>{assurance.status === "CLEAR" ? "No delivery flags" : assurance.status === "NEEDS_REVIEW" ? "Review delivery" : "Analysis abstained"}</strong></div>
        <div className="assurance-measurements">
          <span>{assurance.confident_region_count > 0 ? <><strong>{assurance.confident_region_count}</strong> text {assurance.confident_region_count === 1 ? "region" : "regions"} analyzed</> : "Text analysis abstained"}</span>
          {assurance.regions.map((region) => <span key={region.region_id}><strong>{region.estimated_local_contrast_ratio.toFixed(2)}:1</strong> estimated local contrast</span>)}
          {assurance.surfaces.slice(0, 2).map((surface) => <span key={surface.surface_id}><strong>{Math.round(surface.detail_retention_ratio * 100)}%</strong> detail retained · {surface.label}</span>)}
        </div>
        <div className="assurance-overlay-controls" aria-label="Thumbnail evidence overlays">
          <button type="button" aria-pressed={showTextRegions} onClick={() => setShowTextRegions((value) => !value)}>Text-like regions</button>
          <button type="button" aria-pressed={showFlaggedRegions} onClick={() => setShowFlaggedRegions((value) => !value)}>Flagged regions</button>
          <button type="button" aria-pressed={showDurationBadge} onClick={() => setShowDurationBadge((value) => !value)}>Duration badge</button>
          <button type="button" aria-pressed={showSafeArea} onClick={() => setShowSafeArea((value) => !value)}>Safe area</button>
        </div>
      </div>}
      {thumbnailUrl && summary.delivery_preview && (
        <div className="delivery-preview" aria-label="Thumbnail delivery preview">
          <h3>Delivery preview</h3>
          <p>Relative delivered-size comparison using the supplied artwork and video duration.</p>
          <div className="delivery-surfaces">
            {summary.delivery_preview.surfaces.map((surface) => (
              <figure key={surface.surface_id} style={{ "--delivery-width": surface.display_width } as CSSProperties}>
                <div className={`delivery-artwork${showSafeArea ? " show-safe-area" : ""}`} style={{ aspectRatio: `${surface.display_width} / ${surface.display_height}`, "--safe-margin": `${surface.safe_margin_fraction * 100}%` } as CSSProperties}>
                  <img src={thumbnailUrl} alt="" />
                  {assurance?.regions.map((region) => {
                    const measurement = assurance.delivered_text.find((item) => item.region_id === region.region_id && item.surface_id === surface.surface_id);
                    const flagged = measurement?.status === "NEEDS_REVIEW" || (measurement?.badge_overlap_fraction ?? 0) >= .1 || measurement?.edge_safety === "INTERSECTS_UNSAFE_AREA";
                    if (!showTextRegions && !(showFlaggedRegions && flagged)) return null;
                    return <span key={region.region_id} className={`thumbnail-evidence-box${flagged ? " is-flagged" : ""}`} aria-label={`${flagged ? "Flagged" : "Detected"} text-like region`} style={{ left: `${region.box.x * 100}%`, top: `${region.box.y * 100}%`, width: `${region.box.width * 100}%`, height: `${region.box.height * 100}%` }} />;
                  })}
                  {showDurationBadge && summary.delivery_preview?.duration_badge_text && <span className="duration-badge" style={{ left: `${surface.badge_x * 100}%`, top: `${surface.badge_y * 100}%`, width: `${surface.badge_width * 100}%`, height: `${surface.badge_height * 100}%` }}>{summary.delivery_preview.duration_badge_text}</span>}
                </div>
                <figcaption><strong>{surface.label}</strong><span>{surface.display_width}×{surface.display_height} px delivered box</span>{assurance && <span>{surfaceText(assurance, surface.surface_id)}</span>}</figcaption>
              </figure>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function GeneratedCaptionsAction({ sourceFile, hasAudio, available, draft, onDraft }: {
  sourceFile: File | null;
  hasAudio: boolean;
  available: boolean;
  draft: GeneratedCaptionDraft | null;
  onDraft: (draft: GeneratedCaptionDraft) => void;
}) {
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generate = async () => {
    if (!sourceFile || working || !hasAudio || !available) return;
    setWorking(true);
    setError(null);
    try { onDraft(await generateLocalCaptions(sourceFile)); }
    catch (reason) { setError(errorPresentation(reason).message); }
    finally { setWorking(false); }
  };
  const download = () => {
    if (!draft?.srt_text) return;
    const url = URL.createObjectURL(new Blob([draft.srt_text], { type: "application/x-subrip;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = draft.download_filename;
    anchor.click();
    URL.revokeObjectURL(url);
  };
  return (
    <section className="generated-captions" aria-labelledby="generated-captions-title">
      <div>
        <h2 id="generated-captions-title">Generate captions locally</h2>
        {!draft && <p>{!hasAudio ? "This video has no audio track to caption." : !available ? "Local caption model unavailable." : "Create a timed caption draft on this device."}</p>}
        {draft?.status === "UNAVAILABLE" && <p role="status">{draft.reason}</p>}
        {draft?.status === "COMPLETED" && <>
          <p><strong>Machine-generated captions</strong> · {draft.cue_count} cues · {formatDuration(draft.covered_seconds)} covered</p>
          <details><summary>Preview</summary><ol>{draft.cues.slice(0, 50).map((cue) => <li key={cue.index}><time>{formatTimecode(cue.start_seconds)}</time> {cue.text}</li>)}</ol>{draft.cues.length > 50 && <small>Showing the first 50 cues.</small>}</details>
        </>}
      </div>
      {!draft?.srt_text
        ? <button className="secondary-button" type="button" disabled={!sourceFile || !hasAudio || !available || working} onClick={() => void generate()}>{working ? "Generating locally…" : "Generate captions locally"}</button>
        : <button className="secondary-button" type="button" onClick={download}><Download aria-hidden="true" /> Download SRT</button>}
      {error && <p className="repair-error" role="alert">{error}</p>}
    </section>
  );
}

function surfaceText(assurance: NonNullable<PreflightReport["release_package"]["thumbnail_assurance"]>, surfaceId: string): string {
  const surface = assurance.surfaces.find((item) => item.surface_id === surfaceId);
  const delivered = assurance.delivered_text.filter((item) => item.surface_id === surfaceId);
  if (!surface) return "";
  const smallest = delivered.length ? Math.min(...delivered.map((item) => item.delivered_height_pixels)) : null;
  const text = smallest === null ? "Text size not evaluated" : `Smallest detected text ${smallest.toFixed(1)} px`;
  const unreadable = surface.unreadable_text_area_share === null ? "" : ` · ${Math.round(surface.unreadable_text_area_share * 100)}% text-like area below floor`;
  const detail = `${Math.round(surface.detail_retention_ratio * 100)}% structural detail retained${surface.detail_status === "NEEDS_REVIEW" ? " (detail-loss advisory)" : ""}`;
  return `${text}${unreadable} · ${detail}`;
}

function OriginalReceiptAction({ report, sourceFile, packageInput }: {
  report: PreflightReport;
  sourceFile: File | null;
  packageInput?: { title: string; description: string; captions?: File | null; thumbnail?: File | null; reviewMode: "full" | "local" };
}) {
  const [digest, setDigest] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const create = async () => {
    if (!sourceFile || loading) return;
    setLoading(true); setError(null);
    try {
      const receipt = await createFinalExportReceipt({ originalVideo: sourceFile, report, title: packageInput?.title ?? "", description: packageInput?.description ?? "", captions: packageInput?.captions, thumbnail: packageInput?.thumbnail });
      setDigest(receipt.package.shipping_video.sha256);
      const url = URL.createObjectURL(new Blob([JSON.stringify(receipt, null, 2)], { type: "application/json" }));
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = "releaseseal.release-receipt.json"; anchor.click(); URL.revokeObjectURL(url);
    } catch (reason) { setError(errorPresentation(reason).message); }
    finally { setLoading(false); }
  };
  return <>
    <div className="report-export" aria-label="Export report">
      <span>Export report</span>
      {(["csv", "markdown", "json"] as const).map((format) => <button key={format} className="text-button" type="button" onClick={() => exportReport(format, report, {}, null)}>{format === "markdown" ? "Markdown" : format.toUpperCase()}</button>)}
    </div>
    <section className="release-receipt" aria-labelledby="release-receipt-heading">
    <div><strong id="release-receipt-heading">Release receipt</strong><span>{digest ? `Exact artifact recorded · SHA-256 ${digest.slice(0, 8)}…${digest.slice(-4)} · Verdict ${report.verdict.replace("_", " ")}` : "Bind this result to the exact artifact and release package."}</span><small>The receipt digest detects accidental modification; it is not a digital signature.</small></div>
    <button className="secondary-button" type="button" disabled={!sourceFile || loading} onClick={() => void create()}><Download aria-hidden="true" />{loading ? "Creating receipt…" : "Download release receipt"}</button>
    {error && <p role="alert">{error}</p>}
    </section>
  </>;
}

function ReleaseRequirementsResults({ report, sourceFile, recoveryAvailable, generatedCaptions, onReportUpdate, onSeek }: {
  report: PreflightReport;
  sourceFile: File | null;
  recoveryAvailable: boolean;
  generatedCaptions: GeneratedCaptionDraft | null;
  onReportUpdate?: (report: PreflightReport) => void;
  onSeek: (seconds: number) => void;
}) {
  const review = report.release_contract;
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<string | null>(null);
  const recoverable = review.results.some((item) =>
    item.reason_code === "text_evidence_unavailable" || (
      item.status === "FAIL"
      && item.evidence_source === "SUPPLIED_CAPTIONS"
      && ["REQUIRED_TEXT", "REQUIRED_EXACT_TOKEN", "REQUIRED_BEFORE_TIME"].includes(item.requirement_type)
    )
  );
  const recover = async () => {
    if (!sourceFile || working) return;
    setWorking(true); setError(null);
    try { onReportUpdate?.(await recoverAudioEvidence(sourceFile, report, generatedCaptions)); }
    catch (reason) { setError(errorPresentation(reason).message); }
    finally { setWorking(false); }
  };
  const confirm = async (candidateId: string) => {
    if (!sourceFile || working) return;
    setWorking(true); setError(null);
    try { onReportUpdate?.(await confirmAudioEvidence(sourceFile, report, candidateId)); setSelectedCandidate(null); }
    catch (reason) { setError(errorPresentation(reason).message); }
    finally { setWorking(false); }
  };
  return (
    <section className="release-contract-results" aria-labelledby="release-contract-title">
      <div className="release-contract-heading">
        <div><span>Delivery gate</span><h2 id="release-contract-title">Release requirements</h2></div>
        <p><strong>{review.passed_count} of {review.results.length}</strong> passed · {review.failed_count} failed · {review.needs_review_count} need review{review.not_evaluated_count ? ` · ${review.not_evaluated_count} not evaluated` : ""}</p>
      </div>
      {recoverable && report.audio_evidence.status === "NOT_NEEDED" && (
        <div className="audio-evidence-recovery">
          <div><strong>Spoken evidence is missing</strong><p>Use optional local transcription to find possible moments. Machine suggestions still require your confirmation.</p></div>
          <button className="secondary-button" type="button" disabled={!sourceFile || !recoveryAvailable || working} onClick={() => void recover()}>{working ? "Listening locally…" : "Find audio evidence"}</button>
          {!recoveryAvailable && <small>Local evidence recovery is unavailable because the configured faster-whisper model or dependency is not available locally.</small>}
        </div>
      )}
      {report.audio_evidence.status !== "NOT_NEEDED" && <p className={`audio-evidence-state state-${report.audio_evidence.status.toLowerCase()}`}>{report.audio_evidence.reason}</p>}
      {error && <p className="repair-error" role="alert">{error}</p>}
      <div className="release-contract-list">
        {review.results.map((result) => {
          const candidates = report.audio_evidence.candidates.filter((item) => item.requirement_id === result.requirement_id);
          const confirmed = report.audio_evidence.confirmations.some((item) => item.requirement_id === result.requirement_id);
          return (
          <article className={`contract-result status-${result.status.toLowerCase()}`} key={result.requirement_id}>
            <div className="contract-result-icon" aria-hidden="true">{result.status === "PASS" ? "✓" : result.status === "FAIL" ? "×" : result.status === "NEEDS_REVIEW" ? "!" : "–"}</div>
            <div>
              <h3>{result.instruction}</h3>
              <p>{result.evidence}</p>
              <small>{result.evaluation_class === "DETERMINISTIC" ? "Deterministic" : "AI-assisted"} · {contractSourceLabel(result.evidence_source)}</small>
              {result.expected && <small>Expected: {result.expected}</small>}
              {candidates.length > 0 && !confirmed && <div className="audio-evidence-candidates">
                {candidates.map((candidate) => <div key={candidate.candidate_id}>
                  <p><strong>Local transcription suggests:</strong> “{candidate.machine_text}”</p>
                  <small>Confirmation: {candidate.proposition}</small>
                  <div>
                    <button className="text-button" type="button" onClick={() => { setSelectedCandidate(candidate.candidate_id); onSeek(candidate.start_seconds); }}><Clock3 aria-hidden="true" /> Review audio {formatTimecode(candidate.start_seconds)}–{formatTimecode(candidate.end_seconds)}</button>
                    {selectedCandidate === candidate.candidate_id && <button className="secondary-button" type="button" disabled={working} onClick={() => void confirm(candidate.candidate_id)}>Confirm this evidence</button>}
                    {selectedCandidate === candidate.candidate_id && <button className="text-button" type="button" onClick={() => setSelectedCandidate(null)}>Cancel</button>}
                  </div>
                </div>)}
              </div>}
            </div>
            {result.timestamp_seconds !== null && <button className="timestamp-button" type="button" onClick={() => onSeek(result.timestamp_seconds!)}><Clock3 aria-hidden="true" /> {formatTimecode(result.timestamp_seconds)}</button>}
          </article>
        );})}
      </div>
    </section>
  );
}

function contractSourceLabel(source: PreflightReport["release_contract"]["results"][number]["evidence_source"]): string {
  return { SUPPLIED_CAPTIONS: "Supplied captions", PUBLISHING_METADATA: "Publishing metadata", MEDIA_MEASUREMENT: "Media measurement", LOCAL_MACHINE_TRANSCRIPT: "Local transcription suggestion", HUMAN_CONFIRMED_AUDIO_EVIDENCE: "Human-confirmed audio evidence", AI_SEMANTIC: "Semantic review", NONE: "No evidence available" }[source];
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
      {viewer.summary && viewer.status === "needs_review" && <p>{viewer.summary}</p>}
      {viewer.status === "not_evaluable" && <p>Continuity could not be evaluated confidently from this video.</p>}
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
        {report.checks.map((check) => {
          const claimInconclusive = check.check_id === "ai.claim_review" && report.claim_review.status === "inconclusive";
          return (
            <li key={check.check_id} className={claimInconclusive ? "is-neutral" : check.passed ? "is-pass" : "is-flagged"}>
              {claimInconclusive ? <Circle aria-hidden="true" /> : check.passed ? <Check aria-hidden="true" /> : <AlertTriangle aria-hidden="true" />}
              <span>{humanizeCheck(check.check_id)}</span>
              <small>{claimInconclusive ? "Completed" : check.passed ? "Passed" : check.finding_codes.length ? "Review" : "Incomplete"}</small>
            </li>
          );
        })}
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
