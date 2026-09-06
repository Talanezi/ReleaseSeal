import { CheckCircle2, Download, FileVideo2, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import { reviewRevisionSemantics } from "../api/preflight";
import type { AdditionalRevisionChange, RevisionCheckReport, RevisionRequest, RevisionSegment, RevisionSemanticReviewReport, RevisionSemanticResult } from "../types/preflight";
import { formatTimecode } from "../utils/format";
import { PRODUCT_NAME } from "../brand";

type Version = "previous" | "revised";

export function RevisionResultsView({ report, previousUrl, revisedUrl, previousFile = null, revisedFile = null, semanticReviewAvailable = false }: {
  report: RevisionCheckReport;
  previousUrl: string | null;
  revisedUrl: string | null;
  previousFile?: File | null;
  revisedFile?: File | null;
  semanticReviewAvailable?: boolean;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [version, setVersion] = useState<Version>("revised");
  const [selected, setSelected] = useState<RevisionSegment | null>(null);
  const [semanticReport, setSemanticReport] = useState<RevisionSemanticReviewReport | null>(null);
  const [semanticLoading, setSemanticLoading] = useState(false);
  const [semanticError, setSemanticError] = useState<string | null>(null);
  const semanticAbort = useRef<AbortController | null>(null);
  const meaningful = report.revision_map.segments.filter((segment) => segment.kind !== "UNCHANGED");
  const unchangedPercent = (report.revision_map.unchanged_ratio * 100).toFixed(1);
  const noChanges = meaningful.length === 0;
  const segmentById = useMemo(() => new Map(report.revision_map.segments.map((segment) => [segment.segment_id, segment])), [report]);
  const semanticByRequest = useMemo(() => new Map(semanticReport?.results.map((item) => [item.request_id, item]) ?? []), [semanticReport]);
  const eligibleCount = report.revision_requests.filter((item) => item.status === "CHANGE_DETECTED" && item.previous_start_seconds !== null).length;

  useEffect(() => () => semanticAbort.current?.abort(), []);

  const runSemanticReview = async () => {
    if (!previousFile || !revisedFile || semanticLoading) return;
    const controller = new AbortController();
    semanticAbort.current = controller;
    setSemanticLoading(true);
    setSemanticError(null);
    try {
      setSemanticReport(await reviewRevisionSemantics({ previousVideo: previousFile, revisedVideo: revisedFile, revisionCheck: report }, { signal: controller.signal }));
    } catch (error) {
      if (!controller.signal.aborted) setSemanticError(error instanceof Error ? error.message : "AI revision review is unavailable.");
    } finally {
      if (semanticAbort.current === controller) semanticAbort.current = null;
      setSemanticLoading(false);
    }
  };

  useEffect(() => {
    if (!selected || !video.current) return;
    const start = version === "previous" ? selected.previous_start_seconds : selected.revised_start_seconds;
    if (start !== null) video.current.currentTime = start;
  }, [selected, version]);

  const inspectSegment = (segment: RevisionSegment) => {
    const nextVersion: Version = segment.kind === "REMOVED" ? "previous" : "revised";
    setVersion(nextVersion);
    setSelected(segment);
    window.setTimeout(() => {
      const start = nextVersion === "previous" ? segment.previous_start_seconds : segment.revised_start_seconds;
      if (video.current && start !== null) video.current.currentTime = start;
    }, 0);
  };

  const inspectRequest = (request: RevisionRequest) => {
    const match = request.matched_segment_ids.map((id) => segmentById.get(id)).find(Boolean);
    if (match) inspectSegment(match);
    else if (request.previous_start_seconds !== null) {
      setVersion("previous");
      setSelected(null);
      window.setTimeout(() => { if (video.current) video.current.currentTime = request.previous_start_seconds ?? 0; }, 0);
    }
  };

  return (
    <main className="revision-results page-frame" data-testid="revision-result-state">
      <header className="revision-overview">
        <div><span>Revision Check</span><h1>{noChanges ? "No changes found" : `${unchangedPercent}% unchanged`}</h1><p>{noChanges ? "These two versions match across the analyzed timeline." : `${meaningful.length} physical change${meaningful.length === 1 ? "" : "s"} found across the two cuts.`}</p></div>
        {!noChanges && report.requested_change_count > 0 && (
          <dl className="revision-counts">
            <div><dt>Requested areas changed</dt><dd>{report.requested_changes_detected_count}</dd></div>
            <div><dt>Requested areas unchanged</dt><dd>{report.requested_changes_not_detected_count}</dd></div>
            <div><dt>Need a timecode</dt><dd>{report.requests_needing_location_count}</dd></div>
            <div><dt>Additional changes</dt><dd>{report.additional_change_count}</dd></div>
          </dl>
        )}
      </header>

      {report.revision_requests.length > 0 && (
        <section className="revision-section" aria-labelledby="requested-changes-heading">
          <header><h2 id="requested-changes-heading">Requested changes</h2><p>Timecodes refer to the previous cut.</p></header>
          <div className="revision-change-list">
            {report.revision_requests.map((request) => {
              const semantic = semanticByRequest.get(request.request_id);
              return <div className="revision-request-item" key={request.request_id}>
                <button className="revision-request-row" type="button" onClick={() => inspectRequest(request)}>
                  <span className={`revision-status status-${request.status.toLowerCase()}`}>{requestStatusLabel(request.status)}</span>
                  <span className="revision-row-copy"><strong>{request.text}</strong><small>{requestTime(request)}</small><span>{request.evidence}</span></span>
                  <span className="revision-evidence">{requestEvidence(request, segmentById)}</span>
                </button>
                {semantic && <SemanticResult result={semantic} onInspect={() => inspectRequest(request)} />}
              </div>;
            })}
          </div>
          {!semanticReport && eligibleCount > 0 && semanticReviewAvailable && previousFile && revisedFile && (
            <div className="revision-semantic-action">
              <div><strong>Review the requested changes</strong><span>AI review sends only short clips around the requested changes.</span></div>
              <button className="secondary-button" type="button" disabled={semanticLoading} onClick={() => void runSemanticReview()}><Sparkles aria-hidden="true" />{semanticLoading ? "Reviewing short clips…" : "Review requested changes with AI"}</button>
              {semanticLoading && <button className="text-button" type="button" onClick={() => semanticAbort.current?.abort()}>Cancel</button>}
              {semanticError && <p role="alert">{semanticError}</p>}
            </div>
          )}
          {semanticReport && <div className="revision-semantic-summary"><strong>AI review</strong><span>{semanticReport.appears_satisfied_count} appear satisfied · {semanticReport.appears_unresolved_count} appear unresolved · {semanticReport.inconclusive_count} inconclusive{semanticReport.not_reviewed_count ? ` · ${semanticReport.not_reviewed_count} not reviewed` : ""}</span><small>Probabilistic review of bounded evidence clips. The physical comparison above remains the source of truth for where media changed.</small></div>}
        </section>
      )}

      {report.additional_changes.length > 0 && (
        <section className="revision-section" aria-labelledby="additional-changes-heading">
          <header><h2 id="additional-changes-heading">{report.revision_requests.length ? "Additional changes" : "Changes"}</h2>{report.revision_requests.length > 0 && <p>Physical changes not mentioned by the supplied notes.</p>}</header>
          <div className="revision-change-list">
            {report.additional_changes.map((change) => {
              const segment = segmentById.get(change.segment_id);
              return <button className="revision-request-row" type="button" key={change.segment_id} onClick={() => { if (segment) inspectSegment(segment); }}>
                <span className="revision-status">{kindLabel(change.kind)}</span>
                <span className="revision-row-copy"><strong>{changeRange(change)}</strong><span>{changeEvidence(change)}</span></span>
                <span className="revision-evidence">{change.boundary_confidence === "high" ? "Exact boundary" : "Approximate boundary"}</span>
              </button>;
            })}
          </div>
        </section>
      )}

      <section className="revision-comparison" aria-labelledby="comparison-heading">
        <header><div><h2 id="comparison-heading">Video comparison</h2><p>Select a change above or use the timeline overview.</p></div><div className="version-tabs" role="tablist" aria-label="Video version"><button role="tab" aria-selected={version === "previous"} onClick={() => setVersionAndSeek("previous", selected, setVersion, video)}>Previous</button><button role="tab" aria-selected={version === "revised"} onClick={() => setVersionAndSeek("revised", selected, setVersion, video)}>Revised</button></div></header>
        <div className="revision-player">
          {(version === "previous" ? previousUrl : revisedUrl) ? <video ref={video} key={version} controls src={(version === "previous" ? previousUrl : revisedUrl) ?? undefined} aria-label={`${version} cut video`} /> : <div className="video-placeholder"><FileVideo2 aria-hidden="true" /><strong>Video preview unavailable</strong></div>}
        </div>
        <TimelineStrip label="Previous cut timeline" duration={report.revision_map.previous_duration_seconds} version="previous" segments={meaningful} onSelect={inspectSegment} />
        <TimelineStrip label="Revised cut timeline" duration={report.revision_map.revised_duration_seconds} version="revised" segments={meaningful} onSelect={inspectSegment} />
        {selected?.kind === "CHANGED" && <p className="revision-inspect-note">This region exists in both cuts. Switch versions to inspect each position.</p>}
      </section>

      {report.revision_map.ambiguity_notes.length > 0 && <p className="revision-ambiguity">One or more boundaries are approximate because the media contains repeated or static imagery.</p>}

      <details className="revision-technical">
        <summary>Technical details</summary>
        <dl>
          <div><dt>Previous SHA-256</dt><dd>{report.revision_map.previous_sha256}</dd></div>
          <div><dt>Revised SHA-256</dt><dd>{report.revision_map.revised_sha256}</dd></div>
          <div><dt>Previous duration</dt><dd>{formatTimecode(report.revision_map.previous_duration_seconds)}</dd></div>
          <div><dt>Revised duration</dt><dd>{formatTimecode(report.revision_map.revised_duration_seconds)}</dd></div>
          <div><dt>Samples</dt><dd>{report.revision_map.previous_sample_count} previous, {report.revision_map.revised_sample_count} revised</dd></div>
          <div><dt>Analysis runtime</dt><dd>{report.analysis_runtime_seconds.toFixed(2)} seconds</dd></div>
        </dl>
      </details>

      <div className="revision-export">
        <span><CheckCircle2 aria-hidden="true" /> Physical change report ready</span>
        <button className="secondary-button" type="button" onClick={() => downloadReport(report, semanticReport, "json")}><Download aria-hidden="true" /> JSON</button>
        <button className="secondary-button" type="button" onClick={() => downloadReport(report, semanticReport, "md")}><Download aria-hidden="true" /> Markdown</button>
      </div>
    </main>
  );
}

function TimelineStrip({ label, duration, version, segments, onSelect }: { label: string; duration: number; version: Version; segments: RevisionSegment[]; onSelect: (segment: RevisionSegment) => void }) {
  return <div className="revision-timeline"><span>{label}</span><div className="revision-timeline-track">{segments.map((segment) => {
    const start = version === "previous" ? segment.previous_start_seconds : segment.revised_start_seconds;
    const end = version === "previous" ? segment.previous_end_seconds : segment.revised_end_seconds;
    if (start === null || end === null) return null;
    return <button key={segment.segment_id} type="button" className={`revision-timeline-segment kind-${segment.kind.toLowerCase()}`} style={{ left: `${start / duration * 100}%`, width: `${Math.max((end - start) / duration * 100, 0.5)}%` }} aria-label={`${kindLabel(segment.kind)} on ${label}, ${formatTimecode(start)} to ${formatTimecode(end)}`} onClick={() => onSelect(segment)} />;
  })}</div></div>;
}

function setVersionAndSeek(next: Version, segment: RevisionSegment | null, setVersion: (version: Version) => void, video: RefObject<HTMLVideoElement | null>) {
  setVersion(next);
  const start = next === "previous" ? segment?.previous_start_seconds : segment?.revised_start_seconds;
  window.setTimeout(() => { if (video.current && start !== null && start !== undefined) video.current.currentTime = start; }, 0);
}

function requestStatusLabel(status: RevisionRequest["status"]): string {
  return { CHANGE_DETECTED: "Change detected", NO_CHANGE_DETECTED: "No change found", NEEDS_LOCATION: "Needs a timecode" }[status];
}
function requestTime(request: RevisionRequest): string { return request.previous_start_seconds === null ? "No timecode supplied" : request.previous_end_seconds === request.previous_start_seconds ? formatTimecode(request.previous_start_seconds) : `${formatTimecode(request.previous_start_seconds)}–${formatTimecode(request.previous_end_seconds ?? request.previous_start_seconds)}`; }
function kindLabel(kind: RevisionSegment["kind"]): string { return { UNCHANGED: "Unchanged", REMOVED: "Removed", INSERTED: "Inserted", CHANGED: "Changed" }[kind]; }
function changeEvidence(change: Pick<AdditionalRevisionChange, "visual_changed" | "audio_changed">): string { return change.visual_changed && change.audio_changed ? "Visual + audio" : change.visual_changed ? "Visual" : change.audio_changed ? "Audio" : "Physical change"; }
function requestEvidence(request: RevisionRequest, segments: Map<string, RevisionSegment>): string { const matched = request.matched_segment_ids.map((id) => segments.get(id)).filter((item): item is RevisionSegment => Boolean(item)); return matched.length ? [...new Set(matched.map((item) => `${kindLabel(item.kind)} · ${changeEvidence(item)}`))].join(", ") : ""; }
function changeRange(change: AdditionalRevisionChange): string { if (change.kind === "INSERTED") return `Revised ${range(change.revised_start_seconds, change.revised_end_seconds)}`; if (change.kind === "REMOVED") return `Previous ${range(change.previous_start_seconds, change.previous_end_seconds)}`; return `Previous ${range(change.previous_start_seconds, change.previous_end_seconds)} · Revised ${range(change.revised_start_seconds, change.revised_end_seconds)}`; }
function range(start: number | null, end: number | null): string { return start === null || end === null ? "location unavailable" : `${formatTimecode(start)}–${formatTimecode(end)}`; }

function SemanticResult({ result, onInspect }: { result: RevisionSemanticResult; onInspect: () => void }) {
  return <div className={`revision-semantic-result semantic-${result.status.toLowerCase()}`}>
    <span>AI review</span><strong>{semanticStatusLabel(result.status)}</strong><p>{result.rationale}</p>
    {result.limitation && <small>{result.limitation}</small>}
    {result.reviewed_previous_range && <button className="text-button" type="button" onClick={onInspect}>Review evidence</button>}
  </div>;
}
function semanticStatusLabel(status: RevisionSemanticResult["status"]): string { return { APPEARS_SATISFIED: "Appears satisfied", APPEARS_UNRESOLVED: "Appears unresolved", INCONCLUSIVE: "Inconclusive", NOT_REVIEWED: "Review unavailable" }[status]; }

function downloadReport(report: RevisionCheckReport, semantic: RevisionSemanticReviewReport | null, kind: "json" | "md") {
  const content = kind === "json" ? JSON.stringify(semantic ? { revision_check: report, semantic_review: semantic } : report, null, 2) : markdownReport(report, semantic);
  const url = URL.createObjectURL(new Blob([content], { type: kind === "json" ? "application/json" : "text/markdown" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = `creator-preflight-revision-report.${kind}`; anchor.click(); URL.revokeObjectURL(url);
}
function markdownReport(report: RevisionCheckReport, semantic: RevisionSemanticReviewReport | null = null): string {
  const lines = [`# ${PRODUCT_NAME} Revision Check`, "", `- Previous: ${report.previous_filename}`, `- Revised: ${report.revised_filename}`, `- Unchanged: ${(report.revision_map.unchanged_ratio * 100).toFixed(1)}%`, ""];
  if (report.revision_requests.length) { lines.push("## Requested changes", ""); report.revision_requests.forEach((item) => lines.push(`- ${requestTime(item)}: ${item.text}: ${requestStatusLabel(item.status)}`)); lines.push(""); }
  lines.push("## Physical change regions", ""); report.revision_map.segments.filter((item) => item.kind !== "UNCHANGED").forEach((item) => lines.push(`- ${kindLabel(item.kind)}: ${item.previous_start_seconds === null ? "previous n/a" : `previous ${range(item.previous_start_seconds, item.previous_end_seconds)}`}; ${item.revised_start_seconds === null ? "revised n/a" : `revised ${range(item.revised_start_seconds, item.revised_end_seconds)}`}`));
  if (semantic) { lines.push("", "## AI semantic review", ""); semantic.results.forEach((item) => lines.push(`- ${item.request_id}: ${semanticStatusLabel(item.status)}. ${item.rationale}`)); lines.push("", "These results are probabilistic reviews of short evidence clips and do not replace the deterministic physical comparison."); }
  lines.push("", "## Limitation", "", "This report detects physical picture and sound changes. Optional AI review only indicates whether a requested change appears satisfied in bounded evidence."); return `${lines.join("\n")}\n`;
}
