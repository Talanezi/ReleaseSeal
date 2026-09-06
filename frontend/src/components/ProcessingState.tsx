import { useEffect, useRef, useState } from "react";
import type { ScanProgress, ScanProgressTask } from "../types/preflight";

interface ProcessingStateProps {
  filename: string;
  reviewMode: "full" | "local";
  progress: ScanProgress | null;
}

export function ProcessingState({ filename, reviewMode, progress }: ProcessingStateProps) {
  const mountedAt = useRef(Date.now() / 1000);
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(interval);
  }, []);

  const startedAt = progress?.created_at_epoch_seconds ?? mountedAt.current;
  const elapsed = Math.max(0, now - startedAt);
  const staleFor = progress ? Math.max(0, now - progress.updated_at_epoch_seconds) : elapsed;
  const percent = progress?.percent ?? 1;
  const message = progress?.message ?? "Getting the video ready";
  const tasks = progress?.tasks.length ? progress.tasks : initialTasks(reviewMode);

  return (
    <main className="processing page-frame" data-testid="processing-state">
      <section className="processing-surface">
        <h1>Checking your video</h1>
        <p className="processing-file" title={filename}>Checking <strong>{filename}</strong></p>
        <p className="processing-lead">{message}</p>
        <div className="processing-progress" role="progressbar" aria-label="Scan in progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
          <span className={progress ? "is-determinate" : "is-indeterminate"} style={progress ? { width: `${percent}%` } : undefined} />
        </div>
        <p className="processing-measure"><strong>{percent}%</strong><span>·</span>{formatElapsed(elapsed)} elapsed</p>
        <p className="processing-friendly">{friendlyLine(progress?.stage, percent)}</p>
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
