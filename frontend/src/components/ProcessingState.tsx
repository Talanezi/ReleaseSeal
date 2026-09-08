import { useEffect, useRef, useState } from "react";
import type { ScanUploadProgress } from "../api/preflight";
import type { ScanProgress, ScanProgressTask } from "../types/preflight";

interface ProcessingStateProps {
  filename: string;
  reviewMode: "full" | "local";
  progress: ScanProgress | null;
  uploadProgress?: ScanUploadProgress | null;
}

export function ProcessingState({ filename, reviewMode, progress, uploadProgress = null }: ProcessingStateProps) {
  const mountedAt = useRef(Date.now() / 1000);
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(interval);
  }, []);

  const startedAt = progress?.created_at_epoch_seconds ?? mountedAt.current;
  const elapsed = Math.max(0, now - startedAt);
  const staleFor = progress ? Math.max(0, now - progress.updated_at_epoch_seconds) : elapsed;
  const backendHasAdvanced = Boolean(progress && progress.stage !== "receiving_media" && progress.stage !== "preparing_media");
  const showUpload = uploadProgress !== null && !backendHasAdvanced;
  const uploadComplete = showUpload && uploadProgress.complete;
  const percent = showUpload ? uploadProgress.percent : (progress?.percent ?? 1);
  const message = uploadComplete ? "Preparing video…" : showUpload ? "Uploading video" : (progress?.message ?? "Getting the video ready");
  const tasks = progress?.tasks.length ? progress.tasks : initialTasks(reviewMode);

  return (
    <main className="processing page-frame" data-testid="processing-state">
      <section className="processing-surface">
        <h1>{showUpload && !uploadComplete ? "Uploading video" : "Checking your video"}</h1>
        <p className="processing-file" title={filename}>Checking <strong>{filename}</strong></p>
        <p className="processing-lead">{message}</p>
        <div className="processing-progress" role="progressbar" aria-label={showUpload ? "Upload in progress" : "Scan in progress"} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent ?? undefined} aria-valuetext={uploadComplete ? "Upload complete; preparing video" : undefined}>
          <span className={`${percent === null ? "is-indeterminate" : "is-determinate"} is-active`} style={percent === null ? undefined : { width: `${percent}%` }} />
        </div>
        <p className="processing-measure">
          {uploadComplete ? <strong>Upload complete</strong> : percent !== null ? <strong>{percent}%</strong> : <strong>Uploading…</strong>}
          {showUpload && !uploadComplete && uploadProgress.totalBytes !== null && <><span>·</span>{formatBytes(uploadProgress.loadedBytes)} of {formatBytes(uploadProgress.totalBytes)}</>}
          <span>·</span>{formatElapsed(elapsed)} elapsed
        </p>
        <p className="processing-friendly">{showUpload ? (uploadComplete ? "Upload complete · Preparing video…" : "Sending your video securely…") : friendlyLine(progress?.stage, percent ?? 1)}</p>
        {staleFor >= 20 && <p className="processing-stale" role="status">Still working… Last update {formatElapsed(staleFor)} ago.</p>}
        <details className="processing-details">
          <summary>What’s happening?</summary>
          <ul>{tasks.map((task) => <li key={task.task_id}><span>{task.label}</span><small data-status={task.status}>{task.status}</small></li>)}</ul>
        </details>
        <p className="processing-explanation">Longer videos can take a little while. You can leave this tab open while the review runs.</p>
      </section>
    </main>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1_000_000) return `${Math.max(0, Math.round(bytes / 1_000))} KB`;
  return `${Math.max(0, Math.round(bytes / 1_000_000))} MB`;
}

function formatElapsed(seconds: number): string {
  const whole = Math.floor(seconds);
  const minutes = Math.floor(whole / 60);
  return `${minutes}:${String(whole % 60).padStart(2, "0")}`;
}

function friendlyLine(stage: ScanProgress["stage"] | undefined, percent: number): string {
  if (percent >= 89 || stage === "final_report") return "Making your review clear and useful…";
  if (stage === "opening_review" || stage === "continuity_review" || stage === "factual_review") return "Looking for anything worth your attention…";
  return "Making sure nothing obvious slipped through…";
}

function initialTasks(reviewMode: "full" | "local"): ScanProgressTask[] {
  return reviewMode === "full" ? [
    { task_id: "technical", label: "Picture and sound", status: "Waiting" },
    { task_id: "opening", label: "Opening review", status: "Waiting" },
    { task_id: "continuity", label: "Edit continuity", status: "Waiting" },
    { task_id: "factual", label: "Content and claims", status: "Waiting" },
    { task_id: "summary", label: "Preparing your review", status: "Waiting" },
  ] : [
    { task_id: "technical", label: "Picture, sound, captions, and publishing details", status: "Waiting" },
    { task_id: "summary", label: "Preparing your review", status: "Waiting" },
  ];
}
