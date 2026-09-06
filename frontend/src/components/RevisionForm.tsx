import { FileVideo2, RefreshCw, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import type { RefObject } from "react";
import type { PreflightCapabilities } from "../types/preflight";
import { formatBytes } from "../utils/format";

export interface RevisionInputs {
  previousVideo: File | null;
  revisedVideo: File | null;
  notes: string;
}

interface RevisionFormProps {
  inputs: RevisionInputs;
  capabilities: PreflightCapabilities | null;
  onChange: (inputs: RevisionInputs) => void;
  onCompare: () => void;
}

export function RevisionForm({ inputs, capabilities, onChange, onCompare }: RevisionFormProps) {
  const previousInput = useRef<HTMLInputElement>(null);
  const revisedInput = useRef<HTMLInputElement>(null);
  const maximum = capabilities?.maximum_video_upload_size_bytes;
  const previousTooLarge = Boolean(maximum && inputs.previousVideo && inputs.previousVideo.size > maximum);
  const revisedTooLarge = Boolean(maximum && inputs.revisedVideo && inputs.revisedVideo.size > maximum);
  const canCompare = Boolean(
    inputs.previousVideo && inputs.revisedVideo && !previousTooLarge && !revisedTooLarge
      && capabilities?.revision_check_available !== false,
  );

  return (
    <main className="revision-form page-frame" data-testid="revision-input-state">
      <header className="page-intro">
        <div>
          <h1>Compare a revision</h1>
          <p>See what changed between two finished cuts and match those changes to optional revision notes.</p>
        </div>
      </header>
      <form className="revision-surface" onSubmit={(event) => { event.preventDefault(); if (canCompare) onCompare(); }}>
        <div className="revision-files">
          <RevisionFilePicker
            label="Previous cut"
            file={inputs.previousVideo}
            inputRef={previousInput}
            tooLarge={previousTooLarge}
            onFile={(file) => onChange({ ...inputs, previousVideo: file })}
          />
          <RevisionFilePicker
            label="Revised cut"
            file={inputs.revisedVideo}
            inputRef={revisedInput}
            tooLarge={revisedTooLarge}
            onFile={(file) => onChange({ ...inputs, revisedVideo: file })}
          />
        </div>
        <div className="revision-notes field-group">
          <label htmlFor="revision-notes">Revision notes <em>Optional</em></label>
          <textarea
            id="revision-notes"
            value={inputs.notes}
            placeholder={"00:34 Remove the old logo\n01:12 Lower the music"}
            onChange={(event) => onChange({ ...inputs, notes: event.target.value })}
          />
          <p className="field-hint">Use one note per line. Timecodes refer to the previous cut. Untimed notes are kept for your review.</p>
        </div>
        {capabilities && !capabilities.revision_check_available && (
          <p className="upload-limit-message" role="alert">Revision Check needs FFmpeg and FFprobe on the backend.</p>
        )}
        <button className="primary-button" type="submit" disabled={!canCompare}>Compare revision</button>
      </form>
    </main>
  );
}

function RevisionFilePicker({ label, file, inputRef, tooLarge, onFile }: {
  label: string;
  file: File | null;
  inputRef: RefObject<HTMLInputElement | null>;
  tooLarge: boolean;
  onFile: (file: File | null) => void;
}) {
  const [dragging, setDragging] = useState(false);
  return (
    <section className="revision-file-field">
      <h2>{label}</h2>
      <input
        ref={inputRef}
        className="visually-hidden"
        type="file"
        accept="video/*,.mp4,.mov,.mkv,.webm"
        aria-label={`Select ${label.toLowerCase()}`}
        onChange={(event) => onFile(event.target.files?.[0] ?? null)}
      />
      {file ? (
        <div className="revision-selected-file">
          <FileVideo2 aria-hidden="true" />
          <div><strong title={file.name}>{file.name}</strong><span>{formatBytes(file.size)}</span></div>
          <button type="button" className="icon-button" aria-label={`Remove ${label.toLowerCase()}`} onClick={() => { if (inputRef.current) inputRef.current.value = ""; onFile(null); }}><X aria-hidden="true" /></button>
          <button type="button" className="secondary-button compact" onClick={() => { if (inputRef.current) inputRef.current.value = ""; inputRef.current?.click(); }}><RefreshCw aria-hidden="true" /> Change</button>
        </div>
      ) : (
        <button
          type="button"
          className={`revision-drop-zone${dragging ? " is-dragging" : ""}`}
          onClick={() => inputRef.current?.click()}
          onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => { event.preventDefault(); setDragging(false); onFile(event.dataTransfer.files[0] ?? null); }}
        >
          <Upload aria-hidden="true" /><strong>Choose {label.toLowerCase()}</strong><span>MP4, MOV, MKV, or WebM</span>
        </button>
      )}
      {tooLarge && <p className="upload-limit-message" role="alert">This file exceeds the configured upload limit.</p>}
    </section>
  );
}
