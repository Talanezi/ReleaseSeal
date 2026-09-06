import { useEffect, useRef, useState } from "react";

export function RevisionProcessingState({ previousFilename, revisedFilename, onCancel }: {
  previousFilename: string;
  revisedFilename: string;
  onCancel: () => void;
}) {
  const started = useRef(Date.now());
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started.current) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <main className="processing page-frame" data-testid="revision-processing-state">
      <section className="processing-surface revision-processing">
        <h1>Comparing revisions</h1>
        <div className="revision-processing-files">
          <p><span>Previous</span><strong title={previousFilename}>{previousFilename}</strong></p>
          <p><span>Revised</span><strong title={revisedFilename}>{revisedFilename}</strong></p>
        </div>
        <p className="processing-lead">Matching the two timelines and checking where they differ.</p>
        <div className="processing-progress" role="progressbar" aria-label="Revision comparison in progress"><span className="is-indeterminate" /></div>
        <p className="processing-measure">{formatElapsed(elapsed)} elapsed</p>
        <button className="secondary-button" type="button" onClick={onCancel}>Cancel comparison</button>
      </section>
    </main>
  );
}

function formatElapsed(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
