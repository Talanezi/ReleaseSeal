import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import { HardDrive } from "lucide-react";
import { checkRevision, discardScanProgress, errorPresentation, fetchCapabilities, fetchScanProgress, isAbortError, scanPreflight } from "./api/preflight";
import { ErrorState } from "./components/ErrorState";
import { ProcessingState } from "./components/ProcessingState";
import { ResultsView } from "./components/ResultsView";
import { ScanForm, type ScanInputs } from "./components/ScanForm";
import { RevisionForm, type RevisionInputs } from "./components/RevisionForm";
import { RevisionProcessingState } from "./components/RevisionProcessingState";
import { RevisionResultsView } from "./components/RevisionResultsView";
import type { PreflightCapabilities, PreflightReport, RevisionCheckReport, ScanProgress } from "./types/preflight";
import { PRODUCT_NAME } from "./brand";

type ViewState = "input" | "processing" | "result" | "error";
type Workflow = "final" | "revision";

const emptyInputs: ScanInputs = {
  video: null,
  title: "",
  description: "",
  captions: null,
  thumbnail: null,
  reviewMode: "local",
  releaseContract: null,
};
const emptyRevisionInputs: RevisionInputs = { previousVideo: null, revisedVideo: null, notes: "" };

export function App() {
  const [view, setView] = useState<ViewState>("input");
  const [workflow, setWorkflow] = useState<Workflow>("final");
  const [inputs, setInputs] = useState<ScanInputs>(emptyInputs);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [report, setReport] = useState<PreflightReport | null>(null);
  const [revisionInputs, setRevisionInputs] = useState<RevisionInputs>(emptyRevisionInputs);
  const [revisionReport, setRevisionReport] = useState<RevisionCheckReport | null>(null);
  const [previousUrl, setPreviousUrl] = useState<string | null>(null);
  const [revisedUrl, setRevisedUrl] = useState<string | null>(null);
  const [error, setError] = useState<ReturnType<typeof errorPresentation> | null>(null);
  const [capabilities, setCapabilities] = useState<PreflightCapabilities | null>(null);
  const [capabilityError, setCapabilityError] = useState(false);
  const [progress, setProgress] = useState<ScanProgress | null>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const activeProgressId = useRef<string | null>(null);
  const requestSequence = useRef(0);
  const modeChosen = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    void fetchCapabilities({ signal: controller.signal }).then((next) => {
      setCapabilities(next);
      setCapabilityError(false);
      if (next.full_review_available && !modeChosen.current) {
        setInputs((current) => ({ ...current, reviewMode: "full" }));
      }
    }).catch((loadError) => {
      if (!isAbortError(loadError)) setCapabilityError(true);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!inputs.video || typeof URL.createObjectURL !== "function") {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(inputs.video);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [inputs.video]);

  useEffect(() => objectUrlEffect(revisionInputs.previousVideo, setPreviousUrl), [revisionInputs.previousVideo]);
  useEffect(() => objectUrlEffect(revisionInputs.revisedVideo, setRevisedUrl), [revisionInputs.revisedVideo]);

  useEffect(() => () => {
    requestSequence.current += 1;
    activeRequest.current?.abort();
  }, []);

  const reset = useCallback(() => {
    requestSequence.current += 1;
    activeRequest.current?.abort();
    activeRequest.current = null;
    if (activeProgressId.current) void discardScanProgress(activeProgressId.current);
    activeProgressId.current = null;
    modeChosen.current = false;
    if (workflow === "final") setInputs({ ...emptyInputs, reviewMode: capabilities?.full_review_available ? "full" : "local" });
    else setRevisionInputs(emptyRevisionInputs);
    setReport(null);
    setRevisionReport(null);
    setError(null);
    setProgress(null);
    setView("input");
  }, [capabilities, workflow]);

  const returnToForm = useCallback(() => {
    setReport(null);
    setError(null);
    setProgress(null);
    setView("input");
  }, []);

  const runScan = useCallback(async () => {
    if (!inputs.video) return;

    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    setReport(null);
    setError(null);
    setView("processing");

    try {
      const progressId = newProgressId();
      activeProgressId.current = progressId;
      setProgress(initialProgress(progressId, inputs.reviewMode));
      void pollScanProgress(progressId, controller.signal, sequence, requestSequence, setProgress);
      const nextReport = await scanPreflight(
        {
          video: inputs.video,
          title: inputs.title,
          description: inputs.description,
          captions: inputs.captions,
          thumbnail: inputs.thumbnail,
          reviewMode: inputs.reviewMode,
          releaseContract: inputs.releaseContract,
        },
        { signal: controller.signal, progressId },
      );
      if (controller.signal.aborted || requestSequence.current !== sequence) return;
      setReport(nextReport);
      setView("result");
    } catch (scanError) {
      if (controller.signal.aborted || isAbortError(scanError) || requestSequence.current !== sequence) return;
      setError(errorPresentation(scanError));
      setView("error");
    } finally {
      const finishedProgressId = activeProgressId.current;
      if (finishedProgressId) void discardScanProgress(finishedProgressId);
      activeProgressId.current = null;
      if (activeRequest.current === controller) activeRequest.current = null;
    }
  }, [inputs]);

  const runRevision = useCallback(async () => {
    if (!revisionInputs.previousVideo || !revisionInputs.revisedVideo) return;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    setRevisionReport(null);
    setError(null);
    setView("processing");
    try {
      const next = await checkRevision({
        previousVideo: revisionInputs.previousVideo,
        revisedVideo: revisionInputs.revisedVideo,
        notes: revisionInputs.notes,
      }, { signal: controller.signal });
      if (controller.signal.aborted || requestSequence.current !== sequence) return;
      setRevisionReport(next);
      setView("result");
    } catch (revisionError) {
      if (controller.signal.aborted || isAbortError(revisionError) || requestSequence.current !== sequence) return;
      setError(errorPresentation(revisionError));
      setView("error");
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
    }
  }, [revisionInputs]);

  const cancelRevision = useCallback(() => {
    requestSequence.current += 1;
    activeRequest.current?.abort();
    activeRequest.current = null;
    setView("input");
  }, []);

  const updateInputs = useCallback((next: ScanInputs) => {
    if (next.reviewMode !== inputs.reviewMode) modeChosen.current = true;
    setInputs(next);
  }, [inputs.reviewMode]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <strong className="brand-name">{PRODUCT_NAME}</strong>
        <div className="header-actions">
          <span className="local-indicator"><HardDrive aria-hidden="true" /> Local workspace</span>
          {view !== "input" && (
            <button className="header-action" type="button" onClick={reset}>{workflow === "revision" ? "New comparison" : "New scan"}</button>
          )}
        </div>
      </header>

      {view === "input" && (
        <>
          <div className="workflow-selector" aria-label="Workflow">
            <button type="button" className={workflow === "final" ? "is-selected" : ""} aria-pressed={workflow === "final"} onClick={() => setWorkflow("final")}><strong>Final export</strong><span>Review one finished video before it ships.</span></button>
            <button type="button" className={workflow === "revision" ? "is-selected" : ""} aria-pressed={workflow === "revision"} onClick={() => setWorkflow("revision")}><strong>Revision</strong><span>Compare a previous cut with the revised cut.</span></button>
          </div>
          {workflow === "final" ? <ScanForm
          inputs={inputs}
          capabilities={capabilities}
          capabilityError={capabilityError}
          onChange={updateInputs}
          onRun={() => void runScan()}
          /> : <RevisionForm inputs={revisionInputs} capabilities={capabilities} onChange={setRevisionInputs} onCompare={() => void runRevision()} />}
        </>
      )}
      {view === "processing" && (
        workflow === "final"
          ? <ProcessingState filename={inputs.video?.name ?? "selected video"} reviewMode={inputs.reviewMode} progress={progress} />
          : <RevisionProcessingState previousFilename={revisionInputs.previousVideo?.name ?? "previous cut"} revisedFilename={revisionInputs.revisedVideo?.name ?? "revised cut"} onCancel={cancelRevision} />
      )}
      {view === "result" && workflow === "final" && report && (
        <ResultsView
          key={requestSequence.current}
          report={report}
          filename={inputs.video?.name ?? "selected video"}
          previewUrl={previewUrl}
          sourceFile={inputs.video}
          packageInput={{ title: inputs.title, description: inputs.description, captions: inputs.captions, thumbnail: inputs.thumbnail, reviewMode: inputs.reviewMode }}
        />
      )}
      {view === "result" && workflow === "revision" && revisionReport && <RevisionResultsView
        report={revisionReport}
        previousUrl={previousUrl}
        revisedUrl={revisedUrl}
        previousFile={revisionInputs.previousVideo}
        revisedFile={revisionInputs.revisedVideo}
        notes={revisionInputs.notes}
        semanticReviewAvailable={capabilities?.revision_semantic_review_available ?? false}
      />}
      {view === "error" && error && <ErrorState {...error} onRetry={returnToForm} />}
    </div>
  );
}

function objectUrlEffect(file: File | null, update: (url: string | null) => void): (() => void) | undefined {
  if (!file || typeof URL.createObjectURL !== "function") { update(null); return undefined; }
  const url = URL.createObjectURL(file);
  update(url);
  return () => URL.revokeObjectURL(url);
}

function newProgressId(): string {
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : "00000000-0000-4000-8000-000000000000";
}

function initialProgress(progressId: string, reviewMode: "full" | "local"): ScanProgress {
  const now = Date.now() / 1000;
  return {
    progress_id: progressId,
    review_mode: reviewMode,
    state: "RUNNING",
    stage: "receiving_media",
    percent: 1,
    message: "Getting the video ready",
    created_at_epoch_seconds: now,
    updated_at_epoch_seconds: now,
    tasks: [],
  };
}

async function pollScanProgress(
  progressId: string,
  signal: AbortSignal,
  sequence: number,
  requestSequence: MutableRefObject<number>,
  update: Dispatch<SetStateAction<ScanProgress | null>>,
) {
  while (!signal.aborted && requestSequence.current === sequence) {
    await new Promise((resolve) => window.setTimeout(resolve, 750));
    if (signal.aborted || requestSequence.current !== sequence) return;
    try {
      const next = await fetchScanProgress(progressId, { signal });
      update((current) => {
        if (!current) return next;
        if (next.percent < current.percent) return current;
        return {
          ...next,
          created_at_epoch_seconds: Math.min(current.created_at_epoch_seconds, next.created_at_epoch_seconds),
        };
      });
      if (next.state !== "RUNNING") return;
    } catch (error) {
      if (isAbortError(error)) return;
    }
  }
}
