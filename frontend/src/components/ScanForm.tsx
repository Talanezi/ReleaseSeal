import { useEffect, useRef, useState } from "react";
import { Captions, FileImage, FileVideo2, Lightbulb, Play, RefreshCw, Upload, X } from "lucide-react";
import { assistMetadata, errorPresentation, isAbortError } from "../api/preflight";
import { formatBytes } from "../utils/format";
import type { MetadataAssistResult, PreflightCapabilities, ReviewMode } from "../types/preflight";
import { loadFinalExportDemo } from "../demoAssets";
import { PRODUCT_NAME } from "../brand";

export interface ScanInputs {
  video: File | null;
  title: string;
  description: string;
  captions: File | null;
  thumbnail: File | null;
  reviewMode: ReviewMode;
}

interface ScanFormProps {
  inputs: ScanInputs;
  capabilities: PreflightCapabilities | null;
  capabilityError: boolean;
  onChange: (inputs: ScanInputs) => void;
  onRun: () => void;
}

const TITLE_GUIDANCE = 100;

export function ScanForm({ inputs, capabilities, capabilityError, onChange, onRun }: ScanFormProps) {
  const videoInput = useRef<HTMLInputElement>(null);
  const captionInput = useRef<HTMLInputElement>(null);
  const thumbnailInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [thumbnailPreview, setThumbnailPreview] = useState<string | null>(null);
  const [assistResult, setAssistResult] = useState<MetadataAssistResult | null>(null);
  const [assistView, setAssistView] = useState<"titles" | "description" | null>(null);
  const [assistLoading, setAssistLoading] = useState(false);
  const [assistError, setAssistError] = useState<string | null>(null);
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);
  const assistRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!inputs.thumbnail || typeof URL.createObjectURL !== "function") {
      setThumbnailPreview(null);
      return;
    }
    const url = URL.createObjectURL(inputs.thumbnail);
    setThumbnailPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [inputs.thumbnail]);

  useEffect(() => {
    assistRequest.current?.abort();
    assistRequest.current = null;
    setAssistResult(null);
    setAssistView(null);
    setAssistLoading(false);
    setAssistError(null);
  }, [inputs.video, inputs.captions]);

  useEffect(() => () => assistRequest.current?.abort(), []);

  const showAssist = async (view: "titles" | "description") => {
    if (!inputs.video) return;
    setAssistView(view);
    setAssistError(null);
    if (assistResult) return;
    const controller = new AbortController();
    assistRequest.current?.abort();
    assistRequest.current = controller;
    setAssistLoading(true);
    try {
      const result = await assistMetadata(inputs.video, { signal: controller.signal, captions: inputs.captions });
      if (!controller.signal.aborted) setAssistResult(result);
    } catch (error) {
      if (!controller.signal.aborted && !isAbortError(error)) setAssistError(errorPresentation(error).message);
    } finally {
      if (!controller.signal.aborted) setAssistLoading(false);
      if (assistRequest.current === controller) assistRequest.current = null;
    }
  };

  const selectVideo = (file?: File) => {
    if (file) onChange({ ...inputs, video: file });
  };
  const loadDemo = async () => {
    setDemoLoading(true);
    setDemoError(null);
    try {
      const demo = await loadFinalExportDemo();
      onChange({
        ...demo,
        reviewMode: capabilities?.full_review_available ? "full" : "local",
      });
    } catch {
      setDemoError("The sample package could not be loaded. You can still choose your own files.");
    } finally {
      setDemoLoading(false);
    }
  };
  const uploadTooLarge = Boolean(
    inputs.video && capabilities
    && inputs.video.size > capabilities.maximum_video_upload_size_bytes,
  );
  const canRun = Boolean(
    inputs.video
    && !uploadTooLarge
    && (inputs.reviewMode === "local"
      ? capabilities?.local_checks_available !== false
      : capabilities?.full_review_available),
  );

  return (
    <main className="new-scan page-frame" data-testid="input-state">
      <header className="page-intro">
        <div>
          <h1>Check a finished video</h1>
          <p>Add the package you plan to publish. {PRODUCT_NAME} reviews the media and its publishing details together.</p>
        </div>
        <button className="secondary-button demo-button" type="button" onClick={() => void loadDemo()} disabled={demoLoading}>
          <Play aria-hidden="true" /> {demoLoading ? "Loading demo…" : "Load demo"}
        </button>
      </header>
      {demoError && <p className="demo-error" role="alert">{demoError}</p>}

      <form className="scan-surface" onSubmit={(event) => { event.preventDefault(); if (inputs.video) onRun(); }}>
        <section className="video-input-section" aria-labelledby="video-heading">
          <h2 id="video-heading">Video</h2>

          <input
            ref={videoInput}
            className="visually-hidden"
            type="file"
            accept="video/*,.mp4,.mov,.mkv,.webm"
            aria-label="Select video file"
            onChange={(event) => selectVideo(event.target.files?.[0])}
          />

          {inputs.video ? (
            <div className="selected-file" data-testid="selected-video">
              <FileVideo2 className="file-icon" aria-hidden="true" />
              <div className="file-copy">
                <strong title={inputs.video.name}>{inputs.video.name}</strong>
                <span>{formatBytes(inputs.video.size)} · ready to preview locally</span>
              </div>
              <button
                className="icon-button"
                type="button"
                aria-label="Remove selected video"
                onClick={() => {
                  if (videoInput.current) videoInput.current.value = "";
                  onChange({ ...inputs, video: null });
                }}
              >
                <X aria-hidden="true" />
              </button>
              <button
                className="secondary-button compact"
                type="button"
                onClick={() => {
                  if (videoInput.current) videoInput.current.value = "";
                  videoInput.current?.click();
                }}
              >
                <RefreshCw aria-hidden="true" /> Change
              </button>
            </div>
          ) : (
            <button
              type="button"
              className={`drop-zone${dragging ? " is-dragging" : ""}`}
              onClick={() => videoInput.current?.click()}
              onDragEnter={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                selectVideo(event.dataTransfer.files[0]);
              }}
            >
              <Upload className="drop-icon" aria-hidden="true" />
              <strong>Choose a video or drop it here</strong>
              <span>MP4, MOV, MKV, or WebM</span>
              <small>Uploaded to your {PRODUCT_NAME} backend for this scan.</small>
            </button>
          )}
        </section>

        <section className="package-section" aria-labelledby="package-heading">
          <h2 id="package-heading">Publishing details</h2>

          <fieldset className="review-mode-field">
            <legend>Review mode</legend>
            <ReviewModeOption
              value="full"
              selected={inputs.reviewMode === "full"}
              disabled={!capabilities?.full_review_available}
              title="Full Review"
              description="Technical checks plus content, promise, and factual review. Temporarily sends the video and thumbnail for AI review."
              onSelect={() => onChange({ ...inputs, reviewMode: "full" })}
            />
            <ReviewModeOption
              value="local"
              selected={inputs.reviewMode === "local"}
              disabled={capabilities !== null && !capabilities.local_checks_available}
              title="Local Checks Only"
              description="Technical, publishing, and caption checks. No AI media upload."
              onSelect={() => onChange({ ...inputs, reviewMode: "local" })}
            />
            {capabilityError && <p className="mode-note">Backend capabilities are unavailable. Local checks can still be attempted.</p>}
            {capabilities && !capabilities.full_review_available && (
              <p className="mode-note">Full Review unavailable: {capabilities.full_review_unavailable_reasons.map((reason) => capabilityReasonCopy(reason.code)).join(" ")}</p>
            )}
          </fieldset>

          <div className="field-group">
            <div className="field-label-row">
              <label htmlFor="scan-title">Title</label>
              <span className={inputs.title.length > 85 ? "count is-near-limit" : "count"}>
                {inputs.title.length} / {TITLE_GUIDANCE}
              </span>
            </div>
            <input
              id="scan-title"
              value={inputs.title}
              placeholder="The title viewers will see"
              onChange={(event) => onChange({ ...inputs, title: event.target.value })}
            />
            <p className="field-hint">The configured scan profile determines the final limit.</p>
            {inputs.video && capabilities?.metadata_assist_available && (
              <button className="text-button assist-trigger" type="button" onClick={() => void showAssist("titles")}>
                <Lightbulb aria-hidden="true" /> Suggest titles
              </button>
            )}
            {assistView === "titles" && (
              <div className="metadata-assist" aria-live="polite">
                {assistLoading && <p>Generating suggestions…</p>}
                {assistError && <p role="alert">{assistError}</p>}
                {assistResult && <ul>{assistResult.title_suggestions.map((title) => <li key={title}><span>{title}</span><button type="button" className="text-button" onClick={() => onChange({ ...inputs, title })}>Use</button></li>)}</ul>}
              </div>
            )}
          </div>

          <div className="field-group">
            <div className="field-label-row">
              <label htmlFor="scan-description">Description</label>
              <span className="count">{inputs.description.length} characters</span>
            </div>
            <textarea
              id="scan-description"
              rows={8}
              value={inputs.description}
              placeholder={"Describe the video, add links, and list chapters…\n\n00:00 Introduction"}
              onChange={(event) =>
                onChange({ ...inputs, description: event.target.value })
              }
            />
            {inputs.video && capabilities?.metadata_assist_available && (
              <button className="text-button assist-trigger" type="button" onClick={() => void showAssist("description")}>
                <Lightbulb aria-hidden="true" /> Draft description
              </button>
            )}
            {assistView === "description" && (
              <div className="metadata-assist" aria-live="polite">
                {assistLoading && <p>Generating suggestions…</p>}
                {assistError && <p role="alert">{assistError}</p>}
                {assistResult && <><p>{assistResult.description_draft}</p><button type="button" className="text-button" onClick={() => onChange({ ...inputs, description: assistResult.description_draft })}>Use description</button></>}
              </div>
            )}
          </div>

          <div className="field-group captions-field">
            <div>
              <span className="field-label"><Captions aria-hidden="true" /> Captions <em>Optional</em></span>
              <p>Add an SRT or VTT file for timing, structure, and coverage checks.</p>
            </div>
            <input
              ref={captionInput}
              className="visually-hidden"
              type="file"
              accept=".srt,.vtt"
              aria-label="Select optional captions file"
              onChange={(event) =>
                onChange({ ...inputs, captions: event.target.files?.[0] ?? null })
              }
            />
            {inputs.captions ? (
              <div className="caption-selection">
                <span title={inputs.captions.name}>{inputs.captions.name}</span>
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Remove captions file"
                  onClick={() => {
                    if (captionInput.current) captionInput.current.value = "";
                    onChange({ ...inputs, captions: null });
                  }}
                >
                  <X aria-hidden="true" />
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="secondary-button compact"
                onClick={() => captionInput.current?.click()}
              >
                Add captions
              </button>
            )}
          </div>

          <div className="field-group captions-field">
            <div>
              <span className="field-label"><FileImage aria-hidden="true" /> Thumbnail <em>Optional</em></span>
              <p>Add a PNG or JPEG for opening alignment review when Full Review is selected.</p>
            </div>
            <input
              ref={thumbnailInput}
              className="visually-hidden"
              type="file"
              accept="image/png,image/jpeg,.png,.jpg,.jpeg"
              aria-label="Select optional thumbnail file"
              onChange={(event) =>
                onChange({ ...inputs, thumbnail: event.target.files?.[0] ?? null })
              }
            />
            {inputs.thumbnail ? (
              <div className="caption-selection thumbnail-selection">
                {thumbnailPreview && <img src={thumbnailPreview} alt="Selected thumbnail preview" />}
                <span title={inputs.thumbnail.name}>{inputs.thumbnail.name}</span>
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Remove thumbnail file"
                  onClick={() => {
                    if (thumbnailInput.current) thumbnailInput.current.value = "";
                    onChange({ ...inputs, thumbnail: null });
                  }}
                >
                  <X aria-hidden="true" />
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="secondary-button compact"
                onClick={() => thumbnailInput.current?.click()}
              >
                Add thumbnail
              </button>
            )}
          </div>

          <button
            type="submit"
            className="primary-button run-button"
            disabled={!canRun}
          >
            <Play aria-hidden="true" fill="currentColor" /> Run Preflight
          </button>
          {uploadTooLarge && capabilities && (
            <p className="upload-limit-message" role="alert">
              This video exceeds the {formatBytes(capabilities.maximum_video_upload_size_bytes)} upload limit.
            </p>
          )}
        </section>
      </form>
    </main>
  );
}

function ReviewModeOption({ value, selected, disabled, title, description, onSelect }: {
  value: ReviewMode;
  selected: boolean;
  disabled: boolean;
  title: string;
  description: string;
  onSelect: () => void;
}) {
  return (
    <label className={`review-mode-option${selected ? " is-selected" : ""}${disabled ? " is-disabled" : ""}`}>
      <input type="radio" name="review-mode" value={value} checked={selected} disabled={disabled} onChange={onSelect} />
      <span><strong>{title}</strong><small>{description}</small></span>
    </label>
  );
}

function capabilityReasonCopy(code: string): string {
  if (code === "media_tools_unavailable") return "Required local media tools are unavailable.";
  if (code === "gemini_dependency_unavailable") return "The optional AI review package is not installed on the backend.";
  if (code === "gemini_api_key_missing") return "The backend is not configured for AI review.";
  return "AI review is not currently available.";
}
