import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Download, Film, Play, RotateCcw, Scissors, X } from "lucide-react";
import { applyRepairs, createFinalExportReceipt, errorPresentation, isAbortError, previewRepair, renderReviewReel, verifyRepair } from "../api/preflight";
import type { FinalExportReceipt, PreflightReport, RepairOperation, RepairProposal, ReviewMode, VerificationReport } from "../types/preflight";
import { formatDuration, formatTimecode } from "../utils/format";

interface RepairPanelProps {
  report: PreflightReport;
  sourceFile: File | null;
  originalPreviewUrl?: string | null;
  onSeek: (seconds: number) => void;
  onRepairedMedia: (file: File | null, duration: number | null) => void;
  onReviewReelMedia: (file: File | null) => void;
  onSelectMedia: (mode: "original" | "repaired" | "reel", seconds?: number) => void;
  packageInput?: { title: string; description: string; captions?: File | null; thumbnail?: File | null; reviewMode: ReviewMode };
}

type HumanDisposition = "PENDING" | "ACCEPTED_INTENTIONAL" | "NEEDS_CHANGE";

export function RepairPanel({ report, sourceFile, originalPreviewUrl, onSeek, onRepairedMedia, onReviewReelMedia, onSelectMedia, packageInput }: RepairPanelProps) {
  const [activeProposal, setActiveProposal] = useState<RepairProposal | null>(null);
  const [approvedIds, setApprovedIds] = useState<Set<string>>(new Set());
  const [previewBlob, setPreviewBlob] = useState<Blob | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [repairedFile, setRepairedFile] = useState<File | null>(null);
  const [repairedDuration, setRepairedDuration] = useState<number | null>(null);
  const [appliedCount, setAppliedCount] = useState(0);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [verification, setVerification] = useState<VerificationReport | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verificationError, setVerificationError] = useState<string | null>(null);
  const [reviewReel, setReviewReel] = useState<File | null>(null);
  const [humanDispositions, setHumanDispositions] = useState<Record<string, HumanDisposition>>({});
  const [showAccepted, setShowAccepted] = useState(false);
  const [appliedSignature, setAppliedSignature] = useState<string | null>(null);
  const [activeReviewId, setActiveReviewId] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<FinalExportReceipt | null>(null);
  const [receiptLoading, setReceiptLoading] = useState(false);
  const [receiptError, setReceiptError] = useState<string | null>(null);
  const originalContextRef = useRef<HTMLVideoElement>(null);
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!previewBlob || typeof URL.createObjectURL !== "function") {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(previewBlob);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [previewBlob]);

  useEffect(() => () => requestRef.current?.abort(), []);

  useEffect(() => {
    setHumanDispositions({});
    setReceipt(null);
  }, [report]);

  const approvedOperations = useMemo(
    () => report.repair_plan.proposals
      .filter((proposal) => approvedIds.has(proposal.proposal_id) && proposal.operation)
      .map((proposal) => proposal.operation as RepairOperation)
      .sort((left, right) => left.start_seconds - right.start_seconds),
    [approvedIds, report.repair_plan.proposals],
  );

  const humanReview = useMemo(() => {
    const proposals = report.repair_plan.proposals.filter((proposal) => proposal.repairability === "HUMAN_ONLY");
    const accepted = proposals.filter((proposal) => humanDispositions[proposal.proposal_id] === "ACCEPTED_INTENTIONAL").length;
    const needsChange = proposals.filter((proposal) => humanDispositions[proposal.proposal_id] === "NEEDS_CHANGE").length;
    return { total: proposals.length, accepted, needsChange, pending: proposals.length - accepted - needsChange };
  }, [humanDispositions, report.repair_plan.proposals]);
  const humanProposals = useMemo(
    () => report.repair_plan.proposals.filter((proposal) => proposal.repairability === "HUMAN_ONLY"),
    [report.repair_plan.proposals],
  );
  const openHumanReview = (proposal: RepairProposal) => {
    setActiveReviewId(proposal.proposal_id);
    if (proposal.start_seconds !== null) onSeek(proposal.start_seconds);
  };
  const reviewNext = () => {
    const next = humanProposals.find((proposal) => (humanDispositions[proposal.proposal_id] ?? "PENDING") === "PENDING");
    if (next) openHumanReview(next);
  };
  const approvedSignature = approvedOperations.map((operation) => `${operation.start_seconds}:${operation.end_seconds}`).join("|");
  const hasUnappliedApprovals = approvedOperations.length > 0 && approvedSignature !== appliedSignature;
  const orderedProposals = useMemo(() => report.repair_plan.proposals
    .filter((proposal) => showAccepted || humanDispositions[proposal.proposal_id] !== "ACCEPTED_INTENTIONAL")
    .sort((left, right) => proposalRank(left, humanDispositions) - proposalRank(right, humanDispositions)),
  [humanDispositions, report.repair_plan.proposals, showAccepted]);

  if (!report.repair_plan.proposals.length) return null;

  const openPreview = async (proposal: RepairProposal) => {
    if (!sourceFile || !proposal.operation) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setActiveProposal(proposal);
    setPreviewBlob(null);
    setPreviewError(null);
    setApplyError(null);
    setPreviewing(true);
    try {
      const result = await previewRepair(sourceFile, proposal.operation, { signal: controller.signal });
      if (!controller.signal.aborted) setPreviewBlob(result.blob);
    } catch (error) {
      if (!isAbortError(error) && !controller.signal.aborted) {
        setPreviewError(errorPresentation(error).message);
      }
    } finally {
      if (!controller.signal.aborted) setPreviewing(false);
      if (requestRef.current === controller) requestRef.current = null;
    }
  };

  const approveActive = () => {
    if (!activeProposal?.operation || !previewBlob) return;
    if (approvedOperations.some((operation) => rangesOverlap(operation, activeProposal.operation as RepairOperation))) {
      setPreviewError("This repair overlaps another approved range. Keep only one of the overlapping repairs.");
      return;
    }
    clearRenderedOutput();
    setApprovedIds((current) => new Set(current).add(activeProposal.proposal_id));
    closePreview();
  };

  const closePreview = () => {
    requestRef.current?.abort();
    requestRef.current = null;
    setActiveProposal(null);
    setPreviewBlob(null);
    setPreviewError(null);
    setPreviewing(false);
  };

  const applyApproved = async () => {
    if (!sourceFile || !approvedOperations.length) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setApplyError(null);
    setApplying(true);
    try {
      const result = await applyRepairs(sourceFile, approvedOperations, { signal: controller.signal });
      if (controller.signal.aborted) return;
      const name = repairedFilename(sourceFile.name);
      const repaired = new File([result.blob], name, { type: "video/mp4" });
      setRepairedFile(repaired);
      onRepairedMedia(repaired, result.outputDurationSeconds);
      setRepairedDuration(result.outputDurationSeconds);
      setAppliedCount(approvedOperations.length);
      setAppliedSignature(approvedSignature);
      setApplying(false);
      setVerifying(true);
      setVerification(null);
      setVerificationError(null);
      setReviewReel(null);
      onReviewReelMedia(null);
      try {
        const verified = await verifyRepair({
          originalVideo: sourceFile,
          repairedVideo: repaired,
          operations: approvedOperations,
          originalReport: report,
          title: packageInput?.title ?? "",
          description: packageInput?.description ?? "",
          reviewMode: packageInput?.reviewMode ?? report.review_mode,
          captions: packageInput?.captions,
          thumbnail: packageInput?.thumbnail,
        }, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setVerification(verified);
        if (verified.review_reel_available) {
          const reel = await renderReviewReel(repaired, verified.review_reel_manifest, { signal: controller.signal });
          if (!controller.signal.aborted) {
            const reelFile = new File([reel.blob], "creator-preflight.review-reel.mp4", { type: "video/mp4" });
            setReviewReel(reelFile);
            onReviewReelMedia(reelFile);
          }
        }
      } catch (error) {
        if (!isAbortError(error) && !controller.signal.aborted) setVerificationError(errorPresentation(error).message);
      } finally {
        if (!controller.signal.aborted) setVerifying(false);
      }
    } catch (error) {
      if (!isAbortError(error) && !controller.signal.aborted) {
        setApplyError(errorPresentation(error).message);
      }
    } finally {
      if (!controller.signal.aborted) setApplying(false);
      if (requestRef.current === controller) requestRef.current = null;
    }
  };

  const plan = report.repair_plan;
  function clearRenderedOutput() {
    setRepairedFile(null);
    onRepairedMedia(null, null);
    setRepairedDuration(null);
    setAppliedCount(0);
    setAppliedSignature(null);
    setVerification(null);
    setVerificationError(null);
    setReviewReel(null);
    onReviewReelMedia(null);
    setReceipt(null);
  }
  const downloadReceipt = async () => {
    if (!sourceFile || receiptLoading || (repairedFile && !verification)) return;
    setReceiptLoading(true);
    setReceiptError(null);
    try {
      const dispositions = Object.fromEntries(humanProposals.map((proposal) => [proposal.proposal_id, humanDispositions[proposal.proposal_id] ?? "PENDING"]));
      const next = await createFinalExportReceipt({
        originalVideo: sourceFile,
        repairedVideo: repairedFile,
        operations: repairedFile ? approvedOperations : undefined,
        verification: repairedFile ? verification : undefined,
        report,
        title: packageInput?.title ?? "",
        description: packageInput?.description ?? "",
        captions: packageInput?.captions,
        thumbnail: packageInput?.thumbnail,
        humanDispositions: dispositions,
      });
      setReceipt(next);
      downloadJson(next, "creator-preflight.release-receipt.json");
    } catch (error) {
      setReceiptError(errorPresentation(error).message);
    } finally {
      setReceiptLoading(false);
    }
  };
  return (
    <section className="repair-panel" aria-labelledby="repair-heading">
      <header className="repair-header">
        <div>
          <h2 id="repair-heading">Action queue</h2>
          <p>
            {plan.safe_count + plan.preview_required_count} can fix or preview · {humanReview.pending} waiting for review · {humanReview.needsChange} need change
          </p>
        </div>
        {hasUnappliedApprovals && (
          <button className="primary-button" type="button" disabled={applying || !sourceFile} onClick={() => void applyApproved()}>
            <Scissors aria-hidden="true" /> {applying ? "Rendering repaired video…" : `Apply ${approvedOperations.length} approved ${plural(approvedOperations.length, "repair")}`}
          </button>
        )}
      </header>

      {humanReview.total > 0 && (
        <section className="human-review-summary" aria-labelledby="human-review-heading">
          <div>
            <h3 id="human-review-heading">Human review</h3>
            <p>{humanReview.total} {plural(humanReview.total, "finding")} require your judgment.</p>
          </div>
          <p className="human-review-counts" aria-label="Human review counts">
            <strong>{humanReview.accepted}</strong> accepted · <strong>{humanReview.needsChange}</strong> {humanReview.needsChange === 1 ? "needs" : "need"} change · <strong>{humanReview.pending}</strong> pending
          </p>
          {humanReview.pending > 0 && (
            <button className="secondary-button review-next" type="button" onClick={reviewNext}>
              Review next · {humanReview.total - humanReview.pending} of {humanReview.total} reviewed
            </button>
          )}
          {humanReview.pending === 0 && (
            <p className="human-review-complete">
              <Check aria-hidden="true" /> Human review is complete.{humanReview.needsChange > 0 ? ` ${humanReview.needsChange} ${plural(humanReview.needsChange, "issue")} still ${humanReview.needsChange === 1 ? "needs" : "need"} editing.` : " No items are marked as needing a change."}
            </p>
          )}
          {humanReview.accepted > 0 && (
            <button className="text-button" type="button" aria-expanded={showAccepted} onClick={() => setShowAccepted((current) => !current)}>
              {showAccepted ? "Hide accepted items" : `Show ${humanReview.accepted} accepted ${plural(humanReview.accepted, "item")}`}
            </button>
          )}
        </section>
      )}

      <div className="repair-list">
        {orderedProposals.map((proposal) => {
          const approved = approvedIds.has(proposal.proposal_id);
          const humanDisposition = humanDispositions[proposal.proposal_id] ?? "PENDING";
          const setHumanDisposition = (disposition: HumanDisposition) => {
            setHumanDispositions((current) => ({ ...current, [proposal.proposal_id]: disposition }));
            setReceipt(null);
            const next = humanProposals.find((candidate) => (
              candidate.proposal_id !== proposal.proposal_id
              && (humanDispositions[candidate.proposal_id] ?? "PENDING") === "PENDING"
            ));
            setActiveReviewId(next?.proposal_id ?? null);
            if (next?.start_seconds !== null && next?.start_seconds !== undefined) onSeek(next.start_seconds);
          };
          return (
            <article className={`repair-item${proposal.repairability === "HUMAN_ONLY" ? ` human-${humanDisposition.toLowerCase()}` : ""}${activeReviewId === proposal.proposal_id ? " is-reviewing" : ""}`} key={proposal.proposal_id}>
              <div className={`repair-class repair-${proposal.repairability.toLowerCase()}`}>
                {proposal.repairability === "SAFE" ? "Can fix" : proposal.repairability === "PREVIEW_REQUIRED" ? "Preview" : humanDisposition === "ACCEPTED_INTENTIONAL" ? "Accepted" : humanDisposition === "NEEDS_CHANGE" ? "Needs change" : "Review"}
              </div>
              <div className="repair-copy">
                <h3>{proposal.finding_title}</h3>
                {proposal.start_seconds !== null && (
                  <button className="repair-timecode" type="button" onClick={() => onSeek(proposal.start_seconds as number)}>
                    {formatRange(proposal)}
                  </button>
                )}
                <p>{proposal.explanation}</p>
                {proposal.expected_duration_change_seconds !== null && (
                  <small>Video duration will be reduced by approximately {Math.abs(proposal.expected_duration_change_seconds).toFixed(1)} seconds.</small>
                )}
                {proposal.original_start_seconds !== null && proposal.original_end_seconds !== null && (
                  <small>Original/reference interval: {formatTimecode(proposal.original_start_seconds)}–{formatTimecode(proposal.original_end_seconds)}</small>
                )}
              </div>
              <div className="repair-actions">
                {proposal.operation ? (
                  approved ? (
                    <button className="secondary-button" type="button" onClick={() => {
                      clearRenderedOutput();
                      setApprovedIds((current) => {
                        const next = new Set(current);
                        next.delete(proposal.proposal_id);
                        return next;
                      });
                    }}>
                      <RotateCcw aria-hidden="true" /> Remove approval
                    </button>
                  ) : (
                    <button className="secondary-button" type="button" disabled={!sourceFile} onClick={() => void openPreview(proposal)}>
                      <Play aria-hidden="true" /> Preview repair
                    </button>
                  )
                ) : proposal.repairability === "HUMAN_ONLY" ? (
                  <>
                    {proposal.start_seconds !== null && humanDisposition !== "ACCEPTED_INTENTIONAL" && (
                      <button className="secondary-button" type="button" onClick={() => openHumanReview(proposal)}>
                        <Film aria-hidden="true" /> Review
                      </button>
                    )}
                    {humanDisposition === "PENDING" ? (
                      <>
                        <button className="secondary-button" type="button" onClick={() => setHumanDisposition("ACCEPTED_INTENTIONAL")}>Accept</button>
                        <button className="secondary-button" type="button" onClick={() => setHumanDisposition("NEEDS_CHANGE")}>Needs a change</button>
                      </>
                    ) : (
                      <button className="secondary-button" type="button" onClick={() => { setHumanDispositions((current) => ({ ...current, [proposal.proposal_id]: "PENDING" })); setReceipt(null); openHumanReview(proposal); }}>
                        <RotateCcw aria-hidden="true" /> Change decision
                      </button>
                    )}
                  </>
                ) : null}
                {approved && <span className="approved-label"><Check aria-hidden="true" /> Approved</span>}
              </div>
            </article>
          );
        })}
      </div>

      {activeProposal?.operation && (
        <section className="repair-preview" aria-labelledby="repair-preview-title">
          <header>
            <div>
              <h3 id="repair-preview-title">Preview proposed repair</h3>
              <p>Remove {formatRange(activeProposal)} before rendering the full corrected video.</p>
            </div>
            <button className="icon-button" type="button" aria-label="Close repair preview" onClick={closePreview}><X aria-hidden="true" /></button>
          </header>
          <div className="repair-comparison">
            <div>
              <strong>Original context</strong>
              {originalPreviewUrl ? (
                <video
                  ref={originalContextRef}
                  src={originalPreviewUrl}
                  controls
                  preload="metadata"
                  onLoadedMetadata={() => {
                    if (originalContextRef.current) originalContextRef.current.currentTime = Math.max(0, activeProposal.operation!.start_seconds - 4);
                  }}
                />
              ) : <p>Local preview is unavailable.</p>}
            </div>
            <div>
              <strong>Proposed repair</strong>
              {previewing && <p role="status">Rendering a short repaired context…</p>}
              {previewError && <p className="repair-error" role="alert">{previewError}</p>}
              {previewUrl && <video data-testid="repair-preview-video" src={previewUrl} controls preload="metadata" />}
            </div>
          </div>
          <div className="repair-preview-actions">
            <button className="primary-button" type="button" disabled={!previewBlob || previewing} onClick={approveActive}>Approve repair</button>
            <button className="secondary-button" type="button" onClick={closePreview}>Keep original</button>
          </div>
        </section>
      )}

      {applyError && <p className="repair-error apply-error" role="alert">{applyError}</p>}
      {verifying && <p className="verification-progress" role="status">Verifying repair… Re-scanning the repaired export and checking for unexpected visual changes.</p>}
      {verificationError && <p className="repair-error apply-error" role="alert">Verification could not finish: {verificationError} The repaired video remains available.</p>}
      {repairedFile && (
        <section className="repaired-output" aria-labelledby="repaired-output-title">
          <div>
            <h3 id="repaired-output-title">Repair result</h3>
            <p>{verification ? `${verification.resolved.length} fixed · ${verification.remaining.length} still need attention · ${verification.new.length} ${plural(verification.new.length, "new finding")} · ${verification.unexpected_changes.length} unexpected media changes` : `Repaired export created with ${appliedCount} ${plural(appliedCount, "repair")} applied.`}</p>
            <small>
              Original: {formatDuration(report.media.duration_seconds)} · Repaired: {formatDuration(repairedDuration)}
            </small>
          </div>
          <div className="repair-result-actions">
            <button className="secondary-button" type="button" onClick={() => onSelectMedia("repaired")}>Play repaired</button>
            {reviewReel && <button className="secondary-button" type="button" onClick={() => onSelectMedia("reel")}>Play Review Reel</button>}
          </div>
          {verification && <>
            <div className="post-repair-brief">
              <strong>{verification.repaired_preflight_report.release_brief.headline}</strong>
              <p>{verification.repaired_preflight_report.release_brief.summary}</p>
            </div>
            <VerificationItems report={verification} onSeek={(seconds) => onSelectMedia("repaired", seconds)} />
          </>}
        </section>
      )}
      <div className="report-export" aria-label="Export report">
        <span>Export report</span>
        {(["csv", "markdown", "json"] as const).map((format) => <button key={format} className="text-button" type="button" onClick={() => exportReport(format, report, humanDispositions, verification)}>{format === "markdown" ? "Markdown" : format.toUpperCase()}</button>)}
      </div>
      <section className="release-receipt" aria-labelledby="release-receipt-heading">
        <div>
          <strong id="release-receipt-heading">Release receipt</strong>
          <span>{receipt ? `Exact ${receipt.package.shipping_role === "REPAIRED" ? "repaired " : ""}artifact recorded · SHA-256 ${shortDigest(receipt.package.shipping_video.sha256)} · Verdict ${receipt.verdict.replace("_", " ")}` : "Bind this result to the exact artifact and release package."}</span>
          <small>The receipt digest detects accidental modification; it is not a digital signature.</small>
        </div>
        <button className="secondary-button" type="button" disabled={!sourceFile || receiptLoading || Boolean(repairedFile && !verification)} onClick={() => void downloadReceipt()}>
          <Download aria-hidden="true" /> {receiptLoading ? "Creating receipt…" : "Download release receipt"}
        </button>
        {receiptError && <p role="alert">{receiptError}</p>}
      </section>
    </section>
  );
}

function shortDigest(value: string): string { return `${value.slice(0, 8)}…${value.slice(-4)}`; }

function downloadJson(value: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url);
}

function VerificationItems({ report, onSeek }: { report: VerificationReport; onSeek: (seconds: number) => void }) {
  return <div className="verification-items">
    {!report.unexpected_changes.length && <p><Check aria-hidden="true" /> No deterministic unexpected media changes found.</p>}
    {[...report.remaining, ...report.new].map((item, index) => {
      const finding = item.repaired_finding ?? item.original_finding;
      const time = item.repaired_finding?.timestamp_start_seconds ?? item.expected_repaired_start_seconds;
      return <article key={`${item.status}-${finding?.code ?? index}-${index}`}>
        <strong>{item.status === "RESOLVED" ? "Resolved" : item.status === "REMAINING" ? "Still needs attention" : "Detected on repaired scan"}: {finding?.details?.title ? String(finding.details.title) : finding?.code}</strong>
        <p>{item.explanation}</p>
        {time !== null && time !== undefined && <button className="repair-timecode" type="button" onClick={() => onSeek(time)}>{formatTimecode(time)}</button>}
      </article>;
    })}
    {report.unexpected_changes.map((change) => <article key={`${change.start_seconds}-${change.end_seconds}`}><strong>Unexpected media change</strong><p>Deterministic comparison found that this region changed materially outside the approved edit.</p><button className="repair-timecode" type="button" onClick={() => onSeek(change.start_seconds)}>{formatTimecode(change.start_seconds)}–{formatTimecode(change.end_seconds)}</button></article>)}
    {report.resolved.length > 0 && <details><summary>Show {report.resolved.length} fixed {plural(report.resolved.length, "item")}</summary>{report.resolved.map((item, index) => <p key={`${item.original_finding?.code ?? index}-fixed`}>{item.original_finding?.details?.title ? String(item.original_finding.details.title) : item.original_finding?.code}</p>)}</details>}
  </div>;
}

function proposalRank(proposal: RepairProposal, dispositions: Record<string, HumanDisposition>): number {
  const disposition = dispositions[proposal.proposal_id] ?? "PENDING";
  if (disposition === "NEEDS_CHANGE") return 0;
  if (proposal.repairability === "HUMAN_ONLY" && disposition === "PENDING") return 1;
  if (proposal.operation) return 2;
  return 3;
}

function exportReport(format: "csv" | "markdown" | "json", report: PreflightReport, dispositions: Record<string, HumanDisposition>, verification: VerificationReport | null) {
  const rows = report.findings.map((finding) => {
    const proposal = report.repair_plan.proposals.find((candidate) => (
      candidate.finding_code === finding.code
      && candidate.start_seconds === finding.timestamp_start_seconds
      && candidate.end_seconds === finding.timestamp_end_seconds
    ));
    return {
      status: finding.status,
      severity: finding.severity,
      category: String(finding.details?.category ?? "other"),
      start: finding.timestamp_start_seconds,
      end: finding.timestamp_end_seconds,
      start_timecode: finding.timestamp_start_seconds === null ? null : formatTimecode(finding.timestamp_start_seconds),
      end_timecode: finding.timestamp_end_seconds === null ? null : formatTimecode(finding.timestamp_end_seconds),
      title: String(finding.details?.title ?? finding.code),
      evidence: finding.message,
      suggested_action: finding.suggestion,
      repair_state: proposal?.operation ? "available" : "review",
      human_decision: proposal ? dispositions[proposal.proposal_id] ?? "PENDING" : null,
      verification_state: verification?.resolved.some((item) => item.original_finding?.code === finding.code) ? "FIXED" : verification?.remaining.some((item) => item.original_finding?.code === finding.code) ? "REMAINING" : null,
    };
  });
  const contractRows = report.release_contract.results.map((result) => ({
    status: result.status, evaluation_class: result.evaluation_class, requirement: result.instruction,
    expected: result.expected, evidence: result.evidence, evidence_source: result.evidence_source,
    timestamp: result.timestamp_seconds === null ? null : formatTimecode(result.timestamp_seconds),
    gate_effect: result.status === "FAIL" && result.evaluation_class === "DETERMINISTIC" ? "BLOCKED" : result.status === "NEEDS_REVIEW" ? "NEEDS_REVIEW" : "NONE",
  }));
  const packageRows = Object.entries(report.release_package).filter(([key, value]) => key === "video" || key === "thumbnail" || key === "captions" || key === "title" || key === "description" || key === "chapters" || key === "release_contract").map(([name, value]) => ({ name, ...(value as { state: string; detail: string }) }));
  const thumbnailRows = report.release_package.thumbnail_checks.map((item) => ({ name: item.label, state: item.status, detail: `${item.measured} (${item.expected})` }));
  const assurance = report.release_package.thumbnail_assurance;
  const assuranceRows = assurance ? [
    { name: "Thumbnail delivery assurance", state: assurance.status, detail: assurance.reason },
    ...assurance.surfaces.map((surface) => ({
      name: `Thumbnail ${surface.label}`,
      state: surface.detail_status,
      detail: `${Math.round(surface.detail_retention_ratio * 100)}% structural detail retained${surface.unreadable_text_area_share === null ? "; text size not evaluated" : `; ${Math.round(surface.unreadable_text_area_share * 100)}% detected text-like area below the delivered-height floor`}`,
    })),
  ] : [];
  const content = format === "json" ? JSON.stringify({ verdict: report.verdict, completeness: report.scan_completeness, release_package: report.release_package, release_contract: { ...report.release_contract, gate_effects: contractRows.map(({ requirement, gate_effect }) => ({ requirement, gate_effect })) }, findings: rows }, null, 2)
    : format === "markdown" ? ["# Review report", "", `Status: ${report.verdict}`, "", "## Release package", "", "| Component | State | Detail |", "| --- | --- | --- |", ...[...packageRows, ...thumbnailRows, ...assuranceRows].map((row) => `| ${row.name.replaceAll("_", " ")} | ${row.state} | ${escapeCell(row.detail)} |`), "", ...(contractRows.length ? ["## Release requirements", "", "| Status | Gate effect | Class | Requirement | Evidence |", "| --- | --- | --- | --- | --- |", ...contractRows.map((row) => `| ${row.status} | ${row.gate_effect} | ${row.evaluation_class} | ${escapeCell(row.requirement)} | ${escapeCell(row.evidence)} |`), ""] : []), "## Findings", "", "| Status | Start | Finding | Decision |", "| --- | --- | --- | --- |", ...rows.map((row) => `| ${row.status} | ${row.start_timecode ?? "Global"} | ${escapeCell(row.title)} | ${row.human_decision ?? ""} |`)].join("\n")
    : ["row_type,status,class_or_severity,category_or_source,start,end,title,evidence,suggested_action,repair_state,human_decision,verification_state,gate_effect", ...[...packageRows, ...thumbnailRows, ...assuranceRows].map((row) => ["package", row.state, "", row.name, "", "", row.name.replaceAll("_", " "), row.detail, "", "", "", "", ""].map(csvCell).join(",")), ...contractRows.map((row) => ["contract", row.status, row.evaluation_class, row.evidence_source, row.timestamp ?? "", "", row.requirement, row.evidence, "", "", "", "", row.gate_effect].map(csvCell).join(",")), ...rows.map((row) => ["finding", row.status, row.severity, row.category, row.start_timecode ?? "", row.end_timecode ?? "", row.title, row.evidence, row.suggested_action ?? "", row.repair_state, row.human_decision ?? "", row.verification_state ?? "", ""].map(csvCell).join(","))].join("\n");
  downloadText(`creator-preflight-report.${format === "markdown" ? "md" : format}`, content, format === "json" ? "application/json" : "text/plain");
}

function downloadText(filename: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function csvCell(value: unknown): string {
  return `"${String(value).replaceAll('"', '""')}"`;
}

function escapeCell(value: string): string {
  return value.replaceAll("|", "\\|").replaceAll("\n", " ");
}

function rangesOverlap(left: RepairOperation, right: RepairOperation): boolean {
  return left.start_seconds < right.end_seconds && right.start_seconds < left.end_seconds;
}

function repairedFilename(original: string): string {
  const stem = original.replace(/\.[^.]+$/, "") || "video";
  return `${stem}.repaired.mp4`;
}

function formatRange(proposal: RepairProposal): string {
  if (proposal.start_seconds === null) return "";
  return proposal.end_seconds === null
    ? formatTimecode(proposal.start_seconds)
    : `${formatTimecode(proposal.start_seconds)}–${formatTimecode(proposal.end_seconds)}`;
}

function plural(count: number, singular: string): string {
  return count === 1 ? singular : `${singular}s`;
}
