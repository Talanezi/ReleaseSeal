import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ErrorState } from "./components/ErrorState";
import { ResultsView } from "./components/ResultsView";
import { ProcessingState } from "./components/ProcessingState";
import { RevisionResultsView } from "./components/RevisionResultsView";
import { blockedReport, needsReviewReport, readyReport, revisionCheckReport } from "./mocks/reports";
import type { PreflightReport, ScanProgress, VerificationReport } from "./types/preflight";
import { formatTimecode } from "./utils/format";

const createObjectURL = vi.fn(() => "blob:creator-preflight-local-preview");
const revokeObjectURL = vi.fn();
const NativeURL = URL;

class TestURL extends NativeURL {
  static createObjectURL = createObjectURL;
  static revokeObjectURL = revokeObjectURL;
}

beforeEach(() => {
  vi.stubGlobal("URL", TestURL);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(capabilitiesFixture())));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("Creator Preflight frontend", () => {
  it("offers Final export and Revision as first-class workflows without disturbing the scan form", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(screen.getByRole("button", { name: /Final export/i })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Select video file")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Revision Compare/i }));
    expect(screen.getByLabelText("Select previous cut")).toBeInTheDocument();
    expect(screen.getByLabelText("Select revised cut")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Compare revision" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Final export Review/i }));
    expect(screen.getByLabelText("Select video file")).toBeInTheDocument();
  });

  it("submits two revision files and notes, with truthful processing and reset", async () => {
    let resolveRevision: ((response: Response) => void) | undefined;
    const fetchMock = vi.fn((url: RequestInfo | URL) => {
      if (String(url).endsWith("/capabilities")) return Promise.resolve(jsonResponse(capabilitiesFixture()));
      return new Promise<Response>((resolve) => { resolveRevision = resolve; });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /Revision Compare/i }));
    await user.upload(screen.getByLabelText("Select previous cut"), new File(["old"], "old cut.mp4", { type: "video/mp4" }));
    await user.upload(screen.getByLabelText("Select revised cut"), new File(["new"], "new cut.mp4", { type: "video/mp4" }));
    await user.type(screen.getByLabelText(/Revision notes/), "00:12 Remove old section");
    await user.click(screen.getByRole("button", { name: "Compare revision" }));
    expect(screen.getByTestId("revision-processing-state")).toHaveTextContent("old cut.mp4");
    expect(screen.getByTestId("revision-processing-state")).toHaveTextContent("new cut.mp4");
    expect(screen.queryByText(/%|ETA/i)).not.toBeInTheDocument();
    resolveRevision?.(jsonResponse(revisionCheckReport));
    expect(await screen.findByTestId("revision-result-state")).toHaveTextContent("83.3% unchanged");
    await user.click(screen.getByRole("button", { name: "New comparison" }));
    expect(screen.getByRole("button", { name: "Compare revision" })).toBeDisabled();
    expect(screen.getByLabelText(/Revision notes/)).toHaveValue("");
  });

  it("renders revision statuses, evidence, additional changes, and canonical timecodes", () => {
    render(<RevisionResultsView report={revisionCheckReport} previousUrl="blob:previous" revisedUrl="blob:revised" />);
    expect(screen.getByText("Change detected")).toBeInTheDocument();
    expect(screen.getByText("No change found")).toBeInTheDocument();
    expect(screen.getByText("Needs a timecode")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Additional changes" })).toBeInTheDocument();
    expect(screen.getAllByText("Visual + audio").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Visual").length).toBeGreaterThan(0);
    expect(screen.getByText("Technical details").parentElement).not.toHaveAttribute("open");
    expect(screen.queryByText(/\d+\.\d{4,}\s+seconds/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Removed on Previous cut timeline, 00:10.00 to 00:15.00/)).toBeInTheDocument();
  });

  it("keeps deterministic revision evidence primary and adds explicit bounded AI review", async () => {
    const semantic = {
      schema_version: "1.0", provider: "gemini", model: "fake", eligible_count: 1, requested_count: 1, reviewed_count: 1,
      appears_satisfied_count: 1, appears_unresolved_count: 0, inconclusive_count: 0, not_reviewed_count: 0,
      results: [{ request_id: "request-0001", status: "APPEARS_SATISFIED", confidence: .94, rationale: "The revised evidence appears to satisfy the requested removal.", observed_previous: "Old section present", observed_revised: "Old section absent", reviewed_previous_range: { start_seconds: 8, end_seconds: 17 }, reviewed_revised_range: { start_seconds: 8, end_seconds: 13 }, partial_evidence: false, limitation: null, reason_code: null }],
      evidence_render_seconds: .2, provider_seconds: 1, total_seconds: 1.2, upload_count: 2, generation_count: 1, delete_count: 2,
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(semantic)));
    const user = userEvent.setup();
    render(<RevisionResultsView report={revisionCheckReport} previousUrl="blob:previous" revisedUrl="blob:revised" previousFile={new File(["p"], "p.mp4")} revisedFile={new File(["r"], "r.mp4")} semanticReviewAvailable />);
    expect(screen.getByText("Change detected")).toBeInTheDocument();
    expect(screen.getByText(/AI review sends only short clips/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Review requested changes with AI" }));
    expect(await screen.findByText("Appears satisfied")).toBeInTheDocument();
    expect(screen.getByText(/physical comparison above remains the source of truth/i)).toBeInTheDocument();
    expect(screen.queryByText(/Verified|Passed|Failed/)).not.toBeInTheDocument();
  });

  it("shows semantic review as unavailable without disturbing deterministic results", () => {
    render(<RevisionResultsView report={revisionCheckReport} previousUrl="blob:previous" revisedUrl="blob:revised" />);
    expect(screen.getByText("Change detected")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review requested changes with AI" })).not.toBeInTheDocument();
  });

  it("seeks removed, inserted, and changed evidence in the appropriate version", async () => {
    const user = userEvent.setup();
    render(<RevisionResultsView report={revisionCheckReport} previousUrl="blob:previous" revisedUrl="blob:revised" />);
    await user.click(screen.getByRole("button", { name: /Change detected Remove old section/ }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Previous" })).toHaveAttribute("aria-selected", "true"));
    expect((screen.getByLabelText("previous cut video") as HTMLVideoElement).currentTime).toBe(10);
    await user.click(screen.getByRole("button", { name: /Inserted Revised 00:25.00/ }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Revised" })).toHaveAttribute("aria-selected", "true"));
    expect((screen.getByLabelText("revised cut video") as HTMLVideoElement).currentTime).toBe(25);
    await user.click(screen.getByRole("button", { name: /Changed Previous 00:41.00/ }));
    expect((screen.getByLabelText("revised cut video") as HTMLVideoElement).currentTime).toBe(40);
    await user.click(screen.getByRole("tab", { name: "Previous" }));
    await waitFor(() => expect((screen.getByLabelText("previous cut video") as HTMLVideoElement).currentTime).toBe(41));
  });

  it("enforces the configured upload limit independently for revision files", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ ...capabilitiesFixture(), maximum_video_upload_size_bytes: 3 })));
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /Revision Compare/i }));
    await user.upload(screen.getByLabelText("Select previous cut"), new File(["four"], "large.mp4", { type: "video/mp4" }));
    await user.upload(screen.getByLabelText("Select revised cut"), new File(["ok"], "small.mp4", { type: "video/mp4" }));
    expect(screen.getByText("This file exceeds the configured upload limit.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Compare revision" })).toBeDisabled();
  });

  it("shows a calm identical no-notes revision result", () => {
    const identical = {
      ...revisionCheckReport,
      revision_map: { ...revisionCheckReport.revision_map, previous_sha256: "a".repeat(64), revised_sha256: "a".repeat(64), unchanged_ratio: 1, estimated_unchanged_duration_seconds: 60, revised_duration_seconds: 60, segments: [], ambiguity_notes: [], identical_file_fast_path: true },
      revision_requests: [], requested_change_count: 0, requested_changes_detected_count: 0, requested_changes_not_detected_count: 0, requests_needing_location_count: 0, additional_changes: [], additional_change_count: 0,
    };
    render(<RevisionResultsView report={identical} previousUrl="blob:previous" revisedUrl="blob:revised" />);
    expect(screen.getByText("No changes found")).toBeInTheDocument();
    expect(screen.getByText("These two versions match across the analyzed timeline.")).toBeInTheDocument();
    expect(screen.queryByText("Requested changes")).not.toBeInTheDocument();
  });

  it("exports revision reports as JSON and Markdown", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(<RevisionResultsView report={revisionCheckReport} previousUrl="blob:previous" revisedUrl="blob:revised" />);
    await user.click(screen.getByRole("button", { name: "JSON" }));
    await user.click(screen.getByRole("button", { name: "Markdown" }));
    expect(createObjectURL).toHaveBeenCalledTimes(2);
    expect(revokeObjectURL).toHaveBeenCalledTimes(2);
    expect(click).toHaveBeenCalledTimes(2);
  });

  it("disables Run Preflight until a video is selected", () => {
    render(<App />);
    expect(screen.getByRole("button", { name: /run preflight/i })).toBeDisabled();
    expect(screen.getByText(/timing, structure, and coverage checks/i)).toBeInTheDocument();
    expect(screen.queryByText(/caption contents are not inspected/i)).not.toBeInTheDocument();
  });

  it("offers explicit Full Review and Local Checks modes from backend capabilities", async () => {
    render(<App />);
    const full = await screen.findByRole("radio", { name: /Full Review/i });
    const local = screen.getByRole("radio", { name: /Local Checks Only/i });
    expect(full).toBeChecked();
    expect(local).not.toBeChecked();
    expect(screen.getByText(/Temporarily sends the video and thumbnail for AI review/i)).toBeInTheDocument();
    expect(screen.getByText(/No AI media upload/i)).toBeInTheDocument();
  });

  it("loads the official demo package into the real scan form", async () => {
    vi.stubGlobal("fetch", vi.fn((url: RequestInfo | URL) => {
      const path = String(url);
      if (path.endsWith("/capabilities")) return Promise.resolve(jsonResponse(capabilitiesFixture()));
      if (path.endsWith("-title.txt")) return Promise.resolve(new Response("Why Night Trains Are Returning to Europe\n"));
      if (path.endsWith("-description.txt")) return Promise.resolve(new Response("A concise sample description."));
      if (path.endsWith("-captions.srt")) return Promise.resolve(new Response("1\n00:00:00,000 --> 00:00:02,000\nNight trains\n"));
      if (path.endsWith("-thumbnail.png")) return Promise.resolve(new Response(new Blob(["png"], { type: "image/png" })));
      if (path.endsWith("-demo.mp4")) return Promise.resolve(new Response(new Blob(["video"], { type: "video/mp4" })));
      return Promise.reject(new Error(`Unexpected URL: ${path}`));
    }));
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: "Load demo" }));
    expect(await screen.findByTestId("selected-video")).toHaveTextContent("creator-preflight-official-demo.mp4");
    expect(screen.getByLabelText("Title")).toHaveValue("Why Night Trains Are Returning to Europe");
    expect(screen.getByLabelText("Description")).toHaveValue("A concise sample description.");
    expect(screen.getByText("creator-preflight-official-captions.srt")).toBeInTheDocument();
    expect(screen.getByText("creator-preflight-official-thumbnail.png")).toBeInTheDocument();
  });

  it("renders real elapsed progress, stale reassurance, and task disclosure", async () => {
    const now = Date.now() / 1000;
    render(<ProcessingState filename="long-video.mp4" reviewMode="full" progress={{
      ...progressFixture(), percent: 48, stage: "opening_review", message: "Reviewing the opening",
      created_at_epoch_seconds: now - 67,
      updated_at_epoch_seconds: now - 24,
    }} />);
    expect(screen.getByRole("progressbar", { name: "Scan in progress" })).toHaveAttribute("aria-valuenow", "48");
    expect(screen.getByText(/48%/).parentElement).toHaveTextContent("48%·1:07 elapsed");
    expect(screen.getByText(/Still working… Last update 0:24 ago/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("What’s happening?"));
    expect(screen.getByText("Picture and sound").parentElement).toHaveTextContent("Working");
  });

  it("disables Full Review when backend capabilities say it is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(capabilitiesFixture(false))));
    render(<App />);
    expect(await screen.findByRole("radio", { name: /Full Review/i })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /Local Checks Only/i })).toBeChecked();
    expect(screen.getByText(/Full Review unavailable/i)).toBeInTheDocument();
  });

  it("clears native file inputs when selections are removed", async () => {
    const user = userEvent.setup();
    render(<App />);
    const videoInput = screen.getByLabelText("Select video file") as HTMLInputElement;
    const captionInput = screen.getByLabelText("Select optional captions file") as HTMLInputElement;
    const thumbnailInput = screen.getByLabelText("Select optional thumbnail file") as HTMLInputElement;
    await user.upload(videoInput, new File(["video"], "same video.mp4", { type: "video/mp4" }));
    await user.upload(captionInput, new File(["captions"], "same captions.srt", { type: "text/plain" }));
    await user.upload(thumbnailInput, new File(["image"], "same thumbnail.png", { type: "image/png" }));

    await user.click(screen.getByRole("button", { name: "Remove thumbnail file" }));
    await user.click(screen.getByRole("button", { name: "Remove captions file" }));
    await user.click(screen.getByRole("button", { name: "Remove selected video" }));

    expect(videoInput.value).toBe("");
    expect(captionInput.value).toBe("");
    expect(thumbnailInput.value).toBe("");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:creator-preflight-local-preview");
    expect(screen.getByRole("button", { name: /run preflight/i })).toBeDisabled();
  });

  it("generates metadata only on request and reuses one result for title and description", async () => {
    const metadata = {
      title_suggestions: ["First title", "Second title", "Third title", "Fourth title", "Fifth title"],
      description_draft: "A concise description grounded in the selected video.",
      cleanup_succeeded: true,
    };
    const fetchMock = vi.fn((url: RequestInfo | URL) => Promise.resolve(
      String(url).endsWith("/capabilities") ? jsonResponse(capabilitiesFixture()) : jsonResponse(metadata),
    ));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("radio", { name: /Full Review/i });
    await user.upload(screen.getByLabelText("Select video file"), new File(["video"], "assist.mp4", { type: "video/mp4" }));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Suggest titles" }));
    expect(await screen.findByText("First title")).toBeInTheDocument();
    await user.click(within(screen.getByText("First title").closest("li") as HTMLElement).getByRole("button", { name: "Use" }));
    expect(screen.getByLabelText("Title")).toHaveValue("First title");

    await user.click(screen.getByRole("button", { name: "Draft description" }));
    expect(await screen.findByText(metadata.description_draft)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Use description" }));
    expect(screen.getByLabelText("Description")).toHaveValue(metadata.description_draft);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/metadata/assist"))).toHaveLength(1);
  });

  it("renders the report verdict, counts, and typed findings", () => {
    render(<ResultsView report={needsReviewReport} />);
    const findings = within(screen.getByRole("region", { name: "Findings" }));

    expect(screen.getByRole("heading", { name: "Needs review" })).toBeInTheDocument();
    expect(findings.getByText("Sustained near-black section")).toBeInTheDocument();
    expect(findings.getByText("Long silent section")).toBeInTheDocument();
    expect(screen.getByLabelText("Scan counts")).toHaveTextContent("9 passed·5 warnings·0 critical");
    expect(screen.getByText("AI review")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "5 items need attention" })).toBeInTheDocument();
  });

  it("separates a partial scan from the content verdict", () => {
    render(<ResultsView report={{
      ...readyReport,
      review_mode: "full",
      scan_completeness: "PARTIAL",
      execution_issues: [{
        component: "ai.provider",
        reason_code: "ai_provider_quota_exhausted",
        message: "Gemini quota was reached.",
        retryable: true,
      }],
      ai_review: { ...readyReport.ai_review, enabled: true, status: "unavailable", reason_code: "ai_provider_quota_exhausted" },
      promise_check: { ...readyReport.promise_check, status: "unavailable", explanation: "Gemini quota was reached." },
      viewer_pass: { ...readyReport.viewer_pass, status: "unavailable", summary: "Gemini quota was reached." },
      claim_review: { ...readyReport.claim_review, status: "unavailable", explanation: "Gemini quota was reached." },
    }} />);
    expect(screen.getByRole("heading", { name: "Ready" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Scan incomplete" })).toBeInTheDocument();
    expect(screen.getByText(/Completed content checks found no release issue/i)).toBeInTheDocument();
    expect(screen.getByText(/AI review could not finish/i)).toBeInTheDocument();
    expect(screen.queryByText(/Gemini quota was reached/i)).not.toBeInTheDocument();
  });

  it("keeps Ready while disclosing an inconclusive factual check", () => {
    render(<ResultsView report={{
      ...readyReport,
      review_mode: "full",
      claim_review: { ...readyReport.claim_review, status: "inconclusive", claims_checked: 1, insufficient_evidence_count: 1 },
      release_brief: {
        ...readyReport.release_brief,
        headline: "No release issues found",
        summary: "No issues were found. One factual claim could not be verified with enough evidence.",
        positive_note: "No release issue was detected in the completed checks.",
      },
    }} />);
    expect(screen.getByRole("heading", { name: "Ready" })).toBeInTheDocument();
    expect(screen.getByText(/One factual claim could not be verified with enough evidence/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/everything verified|all claims supported/i);
  });

  it("does not present remote review cards for Local Checks Only", () => {
    render(<ResultsView report={readyReport} />);
    expect(screen.queryByRole("heading", { name: "Promise Check" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Continuity review" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Claim Review" })).not.toBeInTheDocument();
  });

  it("filters the visible findings by real report category", async () => {
    const user = userEvent.setup();
    render(<ResultsView report={needsReviewReport} />);

    await user.click(screen.getByRole("button", { name: "Audio 2" }));
    const findings = within(screen.getByRole("region", { name: "Findings" }));

    expect(findings.getByText("Long silent section")).toBeInTheDocument();
    expect(findings.getByText("Audio peak near full scale")).toBeInTheDocument();
    expect(findings.queryByText("Sustained near-black section")).not.toBeInTheDocument();
    expect(findings.queryByText("Title exceeds recommended length")).not.toBeInTheDocument();
  });

  it("renders global findings without inventing a timestamp", () => {
    render(<ResultsView report={needsReviewReport} />);
    const title = within(screen.getByRole("region", { name: "Findings" })).getByText("Title exceeds recommended length");
    const item = title.closest("article");

    expect(item).not.toBeNull();
    expect(within(item as HTMLElement).getByText("Package")).toBeInTheDocument();
    expect(within(item as HTMLElement).queryByRole("button", { name: /00:/ })).not.toBeInTheDocument();
  });

  it("formats numeric timestamps as stable timecodes", () => {
    expect(formatTimecode(2)).toBe("00:02.00");
    expect(formatTimecode(78.041667)).toBe("01:18.04");
    expect(formatTimecode(46.208333)).toBe("00:46.21");
    expect(formatTimecode(126.034625)).toBe("02:06.03");
    expect(formatTimecode(3723.5)).toBe("1:02:03.50");
  });

  it("does not show rejected provider commentary beneath a clean continuity result", async () => {
    const report = {
      ...readyReport,
      viewer_pass: {
        status: "clean" as const,
        summary: "The video contains visible placeholder and template text.",
        issue_count: 0,
      },
      review_mode: "full" as const,
    };
    render(<ResultsView report={report} />);
    await userEvent.setup().click(screen.getByText("Review details"));
    expect(screen.getByText("No high-confidence inconsistencies found")).toBeInTheDocument();
    expect(screen.queryByText(/visible placeholder and template/i)).not.toBeInTheDocument();
  });

  it("seeks the local video when a timestamp action is clicked", async () => {
    const user = userEvent.setup();
    render(<ResultsView report={needsReviewReport} previewUrl="blob:creator-preflight-test" />);
    const video = screen.getByTestId("preview-video") as HTMLVideoElement;
    fireEvent.loadedMetadata(video);
    video.currentTime = 0;

    await user.click(within(screen.getByRole("region", { name: "Findings" })).getByRole("button", { name: "00:02.00–00:05.00" }));

    expect(video.currentTime).toBe(2);
  });

  it("seeks the local video when a timeline marker is clicked", async () => {
    const user = userEvent.setup();
    render(<ResultsView report={needsReviewReport} previewUrl="blob:creator-preflight-test" />);
    const video = screen.getByTestId("preview-video") as HTMLVideoElement;
    video.currentTime = 0;

    await user.click(screen.getByRole("button", {
      name: "Seek to Sustained static-frame section at 00:07.00–00:10.00",
    }));

    expect(video.currentTime).toBe(7);
  });

  it("renders real caption findings and seeks a timestamped caption gap", async () => {
    const user = userEvent.setup();
    const report = captionFindingReport();
    render(<ResultsView report={report} previewUrl="blob:caption-preview" />);
    const video = screen.getByTestId("preview-video") as HTMLVideoElement;

    expect(screen.getByRole("button", { name: "Captions 2" })).toBeInTheDocument();
    expect(screen.getByText("Possible caption gap")).toBeInTheDocument();
    await user.click(within(screen.getByRole("region", { name: "Findings" })).getByRole("button", { name: "00:07.00–00:10.00" }));
    expect(video.currentTime).toBe(7);
  });

  it("keeps a global caption parse finding off the video timeline", () => {
    render(<ResultsView report={captionFindingReport()} />);

    expect(screen.queryByRole("button", { name: /Seek to Caption file could not be parsed/ })).not.toBeInTheDocument();
    expect(screen.getByText("Caption file could not be parsed cleanly")).toBeInTheDocument();
    expect(screen.getByText("1 timed finding")).toBeInTheDocument();
  });

  it("renders AI-sourced review evidence without a separate UI contract", () => {
    const report: PreflightReport = {
      ...needsReviewReport,
      findings: [{
        code: "AI_REVIEW_VISUAL_CHANGE",
        severity: "warning",
        status: "NEEDS_REVIEW",
        message: "The background changes from blue to green.",
        source: "ai.gemini",
        timestamp_start_seconds: 4,
        timestamp_end_seconds: 4.5,
        details: {
          category: "ai",
          title: "Background changes",
          confidence: 0.95,
          provider: "gemini",
          model: "gemini-3.7-flash",
        },
        suggestion: null,
      }],
      warning_count: 1,
      ai_review: {
        enabled: true,
        provider: "gemini",
        model: "gemini-3.7-flash",
        status: "succeeded",
        observation_count: 1,
        runtime_seconds: 2.4,
        cleanup_succeeded: true,
        reason_code: null,
      },
    };

    render(<ResultsView report={report} />);

    expect(screen.getByRole("button", { name: "AI 1" })).toBeInTheDocument();
    expect(screen.getByText("Background changes")).toBeInTheDocument();
    expect(screen.getByText("The background changes from blue to green.")).toBeInTheDocument();
  });

  it("renders aligned Promise Check evidence without inventing a finding", () => {
    const report: PreflightReport = {
      ...readyReport,
      review_mode: "full",
      promise_check: {
        status: "aligned",
        inferred_promise: "Explain why blue light can disrupt sleep.",
        first_substantive_address_seconds: 8,
        first_substantive_address_evidence: "The explanation begins.",
        opening_alignment: "relevant_hook",
        overall_delivery: "aligned",
        explanation: "The video delivers the title.",
        confidence: 0.95,
        thumbnail_alignment: "aligned",
      },
    };
    render(<ResultsView report={report} />);
    expect(screen.getByRole("heading", { name: "Opening review" })).toBeInTheDocument();
    expect(screen.getByText("Explain why blue light can disrupt sleep.")).toBeInTheDocument();
    expect(screen.getByText("00:08.00")).toBeInTheDocument();
    expect(screen.getByText("Aligned", { selector: ".promise-summary strong" })).toBeInTheDocument();
  });

  it("renders a warning Promise finding and keeps it seekable", async () => {
    const user = userEvent.setup();
    const finding = {
      code: "AI_TITLE_CONTENT_MISMATCH",
      severity: "warning" as const,
      status: "NEEDS_REVIEW" as const,
      message: "Substantive delivery begins after the configured window.",
      source: "ai.gemini.promise",
      timestamp_start_seconds: 12,
      timestamp_end_seconds: 24,
      details: { category: "editorial", title: "Title and video may not align", confidence: 0.94 },
      suggestion: "Review whether the opening should reach the subject sooner.",
    };
    const report: PreflightReport = {
      ...needsReviewReport,
      review_mode: "full",
      findings: [finding],
      warning_count: 1,
      promise_check: {
        status: "needs_review",
        inferred_promise: "Explain the promised subject.",
        first_substantive_address_seconds: 24,
        first_substantive_address_evidence: "The explanation begins.",
        opening_alignment: "unrelated_delay",
        overall_delivery: "aligned",
        explanation: "The promise is ultimately delivered.",
        confidence: 0.94,
        thumbnail_alignment: null,
      },
    };
    render(<ResultsView report={report} previewUrl="blob:promise-preview" />);
    const video = screen.getByTestId("preview-video") as HTMLVideoElement;
    expect(screen.getByRole("button", { name: "Editorial 1" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "00:12.00–00:24.00" }));
    expect(video.currentTime).toBe(12);
  });

  it("renders a clean Final Viewer Pass summary without inventing a finding", () => {
    const report: PreflightReport = {
      ...readyReport,
      review_mode: "full",
      viewer_pass: {
        status: "clean",
        summary: "No high-confidence internal inconsistencies were found.",
        issue_count: 0,
      },
    };
    render(<ResultsView report={report} />);
    expect(screen.getByRole("heading", { name: "Continuity review" })).toBeInTheDocument();
    expect(screen.getByText("No high-confidence inconsistencies found")).toBeInTheDocument();
    expect(screen.queryByText("No high-confidence internal inconsistencies were found.")).not.toBeInTheDocument();
  });

  it("renders and seeks a Viewer Pass editorial finding", async () => {
    const user = userEvent.setup();
    const finding = {
      code: "AI_NARRATION_VISUAL_CONFLICT",
      severity: "warning" as const,
      status: "NEEDS_REVIEW" as const,
      message: "Narration says 2021 while the graphic says 2020.",
      source: "ai.gemini.viewer",
      timestamp_start_seconds: 4,
      timestamp_end_seconds: 8,
      details: {
        category: "editorial",
        title: "Possible narration / graphic conflict",
        confidence: 0.95,
      },
      suggestion: "Review which value was intended before publishing.",
    };
    const report: PreflightReport = {
      ...needsReviewReport,
      review_mode: "full",
      findings: [finding],
      warning_count: 1,
      viewer_pass: {
        status: "needs_review",
        summary: "One internal inconsistency needs review.",
        issue_count: 1,
      },
    };
    render(<ResultsView report={report} previewUrl="blob:viewer-preview" />);
    const video = screen.getByTestId("preview-video") as HTMLVideoElement;
    expect(screen.getByText("1 item to review")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "00:04.00–00:08.00" }));
    expect(video.currentTime).toBe(4);
  });

  it("renders backend-owned repair classes, previews, approvals, multiple apply, and download", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: RequestInfo | URL) => {
      const path = String(url);
      if (path.endsWith("/repairs/verify")) return Promise.resolve(jsonResponse(verificationFixture("VERIFIED")));
      return Promise.resolve(repairVideoResponse());
    }));
    const user = userEvent.setup();
    const report = repairWorkflowReport();
    const source = new File(["original-video"], "original cut.mp4", { type: "video/mp4" });
    render(<ResultsView report={report} previewUrl="blob:original" sourceFile={source} />);

    expect(screen.getByText("2 can fix or preview · 1 waiting for review · 0 need change")).toBeInTheDocument();
    expect(screen.getByText("Can fix")).toBeInTheDocument();
    expect(screen.getAllByText("Preview").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Review").length).toBeGreaterThan(0);

    await user.click(screen.getAllByRole("button", { name: "Preview repair" })[0]);
    expect(await screen.findByTestId("repair-preview-video")).toBeInTheDocument();
    expect(screen.getByText("Original context")).toBeInTheDocument();
    expect(screen.getByText("Proposed repair")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve repair" }));
    expect(screen.getByRole("button", { name: /Apply 1 approved repair/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Remove approval" }));
    expect(screen.queryByRole("button", { name: /Apply approved/ })).not.toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Preview repair" })[0]);
    await screen.findByTestId("repair-preview-video");
    await user.click(screen.getByRole("button", { name: "Approve repair" }));
    await user.click(screen.getByRole("button", { name: "Preview repair" }));
    await screen.findByTestId("repair-preview-video");
    await user.click(screen.getByRole("button", { name: "Approve repair" }));

    await user.click(screen.getByRole("button", { name: /Apply 2 approved repairs/ }));
    expect(await screen.findByRole("heading", { name: "Repair result" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Repaired" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Review Reel" })).toBeInTheDocument();
    expect(screen.getAllByText(/2 fixed/).length).toBeGreaterThan(0);
    expect(screen.getByText(/No deterministic unexpected media changes found/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Apply 2 approved repairs/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download repaired video" })).toHaveAttribute(
      "download", "original cut.repaired.mp4",
    );
    expect(screen.getByRole("link", { name: "Download Review Reel" })).toBeInTheDocument();
  });

  it("separates repaired-scan finding variance from deterministic unexpected changes", async () => {
    const user = userEvent.setup();
    const report = repairWorkflowReport();
    const source = new File(["original-video"], "original cut.mp4", { type: "video/mp4" });
    const verification = verificationFixture("NEEDS_REVIEW");
    verification.new = [{
      status: "NEW",
      original_finding: null,
      repaired_finding: { ...report.findings[2], code: "AI_VISIBLE_PLACEHOLDER", source: "ai.gemini.viewer" },
      expected_repaired_start_seconds: 7,
      expected_repaired_end_seconds: 10,
      deterministically_verified: false,
      explanation: "This content finding appears only in the repaired export.",
    }];
    verification.unexpected_changes = [];
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: RequestInfo | URL) => {
      const path = String(url);
      if (path.endsWith("/repairs/preview")) return Promise.resolve(new Response(new Blob(["preview"]), { headers: { "Content-Type": "video/mp4", "X-Output-Duration-Seconds": "3" } }));
      if (path.endsWith("/repairs/apply")) return Promise.resolve(new Response(new Blob(["repaired"]), { headers: { "Content-Type": "video/mp4", "X-Output-Duration-Seconds": "6" } }));
      if (path.endsWith("/repairs/verify")) return Promise.resolve(jsonResponse(verification));
      if (path.endsWith("/repairs/review-reel")) return Promise.resolve(new Response(new Blob(["reel"]), { headers: { "Content-Type": "video/mp4", "X-Output-Duration-Seconds": "4" } }));
      throw new Error(`Unexpected URL ${path}`);
    }));
    render(<ResultsView report={report} previewUrl="blob:original" sourceFile={source} />);
    await user.click(screen.getAllByRole("button", { name: "Preview repair" })[0]);
    await screen.findByTestId("repair-preview-video");
    await user.click(screen.getByRole("button", { name: "Approve repair" }));
    await user.click(screen.getByRole("button", { name: /Apply 1 approved repair/ }));

    expect(await screen.findByText(/Detected on repaired scan:/)).toBeInTheDocument();
    expect(screen.getByText(/No deterministic unexpected media changes found/)).toBeInTheDocument();
    expect(screen.queryByText(/New after repair/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Unexpected change$/)).not.toBeInTheDocument();
  });

  it("tracks timestamped and global human-review decisions without calling accepted items resolved", async () => {
    const user = userEvent.setup();
    render(<ResultsView report={needsReviewReport} previewUrl="blob:original" />);
    const video = screen.getByTestId("preview-video") as HTMLVideoElement;

    expect(screen.getByText("4 findings require your judgment.")).toBeInTheDocument();
    expect(screen.getByLabelText("Human review counts")).toHaveTextContent("0 accepted · 0 need change · 4 pending");

    const silence = repairItem("Long silent section");
    await user.click(within(silence).getByRole("button", { name: "Review" }));
    expect(video.currentTime).toBe(3);
    await user.click(within(silence).getByRole("button", { name: "Accept" }));
    expect(within(screen.getByRole("region", { name: "Action queue" })).queryByRole("heading", { name: "Long silent section" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show 1 accepted item" })).toBeInTheDocument();

    const peak = repairItem("Audio peak near full scale");
    expect(within(peak).queryByRole("button", { name: "Review" })).not.toBeInTheDocument();
    await user.click(within(peak).getByRole("button", { name: "Needs a change" }));
    expect(within(peak).getByText("Needs change")).toBeInTheDocument();

    await user.click(within(peak).getByRole("button", { name: "Change decision" }));
    expect(within(peak).getByText("Review")).toBeInTheDocument();
    expect(screen.getByLabelText("Human review counts")).toHaveTextContent("1 accepted · 0 need change · 3 pending");

    await user.click(within(repairItem("Sustained static-frame section")).getByRole("button", { name: "Accept" }));
    await user.click(within(repairItem("Audio peak near full scale")).getByRole("button", { name: "Needs a change" }));
    await user.click(within(repairItem("Title exceeds recommended length")).getByRole("button", { name: "Accept" }));
    expect(screen.getByLabelText("Human review counts")).toHaveTextContent("3 accepted · 1 needs change · 0 pending");
    expect(screen.getByText("Human review is complete. 1 issue still needs editing.")).toBeInTheDocument();

    await user.click(within(repairItem("Audio peak near full scale")).getByRole("button", { name: "Change decision" }));
    expect(screen.getByLabelText("Human review counts")).toHaveTextContent("3 accepted · 0 need change · 1 pending");
    expect(screen.queryByText(/Human review is complete/)).not.toBeInTheDocument();
  });

  it("does not carry human-review decisions into a new scan", async () => {
    vi.stubGlobal("fetch", appFetch([
      () => Promise.resolve(jsonResponse(needsReviewReport)),
      () => Promise.resolve(jsonResponse(needsReviewReport)),
    ]));
    const user = userEvent.setup();
    render(<App />);

    await selectVideoAndRun(user, "first.mp4");
    await user.click(within(repairItem("Audio peak near full scale")).getByRole("button", { name: "Accept" }));
    expect(screen.getByLabelText("Human review counts")).toHaveTextContent("1 accepted");

    await user.click(screen.getByRole("button", { name: "New scan" }));
    await selectVideoAndRun(user, "second.mp4");
    expect(await screen.findByLabelText("Human review counts")).toHaveTextContent("0 accepted · 0 need change · 4 pending");
    expect(within(repairItem("Audio peak near full scale")).getByText("Review")).toBeInTheDocument();
  });

  it("keeps the original report usable when repair preview rendering fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      error: { code: "repair_render_failed", message: "FFmpeg could not render the proposed repair.", details: null },
    }, 400)));
    const user = userEvent.setup();
    render(<ResultsView
      report={needsReviewReport}
      previewUrl="blob:original"
      sourceFile={new File(["video"], "source.mp4", { type: "video/mp4" })}
    />);

    await user.click(screen.getByRole("button", { name: "Preview repair" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("FFmpeg could not render the proposed repair.");
    expect(screen.getByRole("heading", { name: "Needs review" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Findings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve repair" })).toBeDisabled();
  });

  it.each(["NEEDS_REVIEW", "INCOMPLETE"] as const)("renders %s repaired verification without losing the repaired export", async (status) => {
    let repairCall = 0;
    vi.stubGlobal("fetch", vi.fn((url: RequestInfo | URL) => {
      if (String(url).endsWith("/repairs/verify")) return Promise.resolve(jsonResponse(verificationFixture(status)));
      repairCall += 1;
      return Promise.resolve(repairVideoResponse());
    }));
    const user = userEvent.setup();
    render(<ResultsView report={needsReviewReport} previewUrl="blob:original" sourceFile={new File(["video"], "source.mp4", { type: "video/mp4" })} />);
    await user.click(screen.getByRole("button", { name: "Preview repair" }));
    await screen.findByTestId("repair-preview-video");
    await user.click(screen.getByRole("button", { name: "Approve repair" }));
    await user.click(screen.getByRole("button", { name: /Apply 1 approved repair/ }));
    expect(await screen.findByRole("heading", { name: "Repair result" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Repaired" })).toBeInTheDocument();
    if (status === "NEEDS_REVIEW") {
      expect(screen.getByText("Unexpected media change")).toBeInTheDocument();
      await user.click(screen.getByRole("tab", { name: "Repaired" }));
      const repairedVideo = screen.getByTestId("preview-video") as HTMLVideoElement;
      await user.click(screen.getByRole("button", { name: "00:01.00–00:02.00" }));
      expect(repairedVideo.currentTime).toBe(1);
    }
    expect(repairCall).toBeGreaterThanOrEqual(2);
  });

  it("preserves the repaired video when automatic verification fails", async () => {
    vi.stubGlobal("fetch", vi.fn((url: RequestInfo | URL) => {
      if (String(url).endsWith("/repairs/verify")) return Promise.resolve(jsonResponse({ error: { code: "verification_regression_failed", message: "Visual verification could not complete.", details: null } }, 500));
      return Promise.resolve(repairVideoResponse());
    }));
    const user = userEvent.setup();
    render(<ResultsView report={needsReviewReport} previewUrl="blob:original" sourceFile={new File(["video"], "source.mp4", { type: "video/mp4" })} />);
    await user.click(screen.getByRole("button", { name: "Preview repair" }));
    await screen.findByTestId("repair-preview-video");
    await user.click(screen.getByRole("button", { name: "Approve repair" }));
    await user.click(screen.getByRole("button", { name: /Apply 1 approved repair/ }));
    expect(await screen.findByText(/Verification could not finish/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Repaired" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Needs review" })).toBeInTheDocument();
  });

  it("automatically enters a verifying state after the repaired render", async () => {
    vi.stubGlobal("fetch", vi.fn((url: RequestInfo | URL) => {
      if (String(url).endsWith("/repairs/verify")) return new Promise<Response>(() => undefined);
      return Promise.resolve(repairVideoResponse());
    }));
    const user = userEvent.setup();
    render(<ResultsView report={needsReviewReport} previewUrl="blob:original" sourceFile={new File(["video"], "source.mp4", { type: "video/mp4" })} />);
    await user.click(screen.getByRole("button", { name: "Preview repair" }));
    await screen.findByTestId("repair-preview-video");
    await user.click(screen.getByRole("button", { name: "Approve repair" }));
    await user.click(screen.getByRole("button", { name: /Apply 1 approved repair/ }));
    expect(await screen.findByText(/Verifying repair/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Repaired" })).toBeInTheDocument();
  });

  it("New scan clears approvals, repaired media, and repair object URLs", async () => {
    const fetchMock = vi.fn((url: RequestInfo | URL) => {
      const path = String(url);
      if (path.endsWith("/capabilities")) return Promise.resolve(jsonResponse(capabilitiesFixture()));
      if (path.endsWith("/preflight/scan")) return Promise.resolve(jsonResponse(needsReviewReport));
      if (path.endsWith("/repairs/verify")) return Promise.resolve(jsonResponse(verificationFixture("VERIFIED")));
      return Promise.resolve(repairVideoResponse());
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);
    await selectVideoAndRun(user, "repair-source.mp4");

    await user.click(await screen.findByRole("button", { name: "Preview repair" }));
    await screen.findByTestId("repair-preview-video");
    await user.click(screen.getByRole("button", { name: "Approve repair" }));
    await user.click(screen.getByRole("button", { name: /Apply 1 approved repair/ }));
    expect(await screen.findByRole("heading", { name: "Repair result" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New scan" }));
    expect(screen.getByTestId("input-state")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Action queue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Repaired video" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Review Reel" })).not.toBeInTheDocument();
    expect(revokeObjectURL).toHaveBeenCalled();
  });

  it("renders grounded Claim Review sources and seeks the claim timestamp", async () => {
    const user = userEvent.setup();
    const report: PreflightReport = {
      ...needsReviewReport,
      review_mode: "full",
      findings: [{
        code: "AI_CLAIM_POSSIBLE_CONFLICT",
        severity: "warning",
        status: "NEEDS_REVIEW",
        message: "The video states 1968; grounded evidence may conflict with that date.",
        source: "ai.gemini.claims",
        timestamp_start_seconds: 14,
        timestamp_end_seconds: null,
        details: {
          category: "claims",
          title: "Possible factual conflict",
          confidence: 0.98,
          sources: [{ title: "NASA", url: "https://www.nasa.gov/history/apollo-11" }],
        },
        suggestion: "Review the claim against the cited source.",
      }],
      warning_count: 1,
      claim_review: {
        status: "needs_review",
        claims_checked: 2,
        supported_count: 1,
        conflict_count: 1,
        insufficient_evidence_count: 0,
        explanation: "Only grounded conflicts become findings.",
      },
    };
    render(<ResultsView report={report} previewUrl="blob:claims-preview" />);
    const video = screen.getByTestId("preview-video") as HTMLVideoElement;
    expect(screen.getByRole("heading", { name: "Factual review" })).toBeInTheDocument();
    expect(screen.getByText("2 checked · 1 to review")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Claims 1" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "NASA" })).toHaveAttribute(
      "href", "https://www.nasa.gov/history/apollo-11",
    );
    await user.click(screen.getByRole("button", { name: "00:14.00" }));
    expect(video.currentTime).toBe(14);
  });

  it("exports trusted review state as CSV, Markdown, and JSON", async () => {
    const user = userEvent.setup();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    render(<ResultsView report={needsReviewReport} />);

    await user.click(screen.getByRole("button", { name: "CSV" }));
    await user.click(screen.getByRole("button", { name: "Markdown" }));
    await user.click(screen.getByRole("button", { name: "JSON" }));

    expect(click).toHaveBeenCalledTimes(3);
    const objectUrlCalls = createObjectURL.mock.calls as unknown[][];
    expect(objectUrlCalls.filter(([value]) => value instanceof Blob)).toHaveLength(3);
    click.mockRestore();
  });

  it.each([
    [readyReport, "Ready"],
    [needsReviewReport, "Needs review"],
    [blockedReport, "Blocked"],
  ] as const)("renders a successful backend %s report as %s", async (report, heading) => {
    vi.stubGlobal("fetch", appFetch([() => Promise.resolve(jsonResponse(report))]));
    const user = userEvent.setup();
    render(<App />);

    await selectVideoAndRun(user, `${heading}.mp4`);

    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.queryByTestId("error-state")).not.toBeInTheDocument();
  });

  it("keeps primary consumer result copy free of em dashes", () => {
    render(<ResultsView report={needsReviewReport} previewUrl="blob:copy-audit" />);
    expect(document.body.textContent).not.toContain("—");
  });

  it("renders a backend/network failure through the application error state", async () => {
    vi.stubGlobal("fetch", appFetch([
      () => Promise.reject(new TypeError("network failed")),
      () => Promise.resolve(jsonResponse(readyReport)),
    ]));
    const user = userEvent.setup();
    render(<App />);

    await selectVideoAndRun(user, "unreachable.mp4");

    expect(await screen.findByTestId("error-state")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Creator Preflight is unavailable" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Return to new scan" }));
    expect(screen.getByTestId("selected-video")).toHaveTextContent("unreachable.mp4");
    await user.click(screen.getByRole("button", { name: "Run Preflight" }));
    expect(await screen.findByRole("heading", { name: "Ready" })).toBeInTheDocument();
  });

  it("aborts an obsolete request and ignores it even if it later resolves", async () => {
    let requestSignal: AbortSignal | undefined;
    let resolveObsolete: ((response: Response) => void) | undefined;
    let scanCall = 0;
    const fetchMock = vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).endsWith("/capabilities")) return Promise.resolve(jsonResponse(capabilitiesFixture()));
      scanCall += 1;
      if (scanCall === 1) {
        requestSignal = init?.signal ?? undefined;
        return new Promise<Response>((resolve) => { resolveObsolete = resolve; });
      }
      return Promise.resolve(jsonResponse(readyReport));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    await selectVideoAndRun(user, "obsolete.mp4");
    expect(await screen.findByTestId("processing-state")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "New scan" }));
    await selectVideoAndRun(user, "current.mp4");
    expect(await screen.findByRole("heading", { name: "Ready" })).toBeInTheDocument();
    resolveObsolete?.(jsonResponse(blockedReport));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Ready" })).toBeInTheDocument());

    expect(requestSignal?.aborted).toBe(true);
    expect(screen.queryByTestId("error-state")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Blocked" })).not.toBeInTheDocument();
  });

  it("replaces the first scan cleanly with a second real response", async () => {
    const fetchMock = appFetch([
      () => Promise.resolve(jsonResponse(readyReport)),
      () => Promise.resolve(jsonResponse(blockedReport)),
    ]);
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    await selectVideoAndRun(user, "video-a.mp4");
    expect(await screen.findByRole("heading", { name: "Ready" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "video-a.mp4" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "New scan" }));
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:creator-preflight-local-preview");

    await selectVideoAndRun(user, "video-b.mp4");
    expect(await screen.findByRole("heading", { name: "Blocked" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "video-b.mp4" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "video-a.mp4" })).not.toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Findings" })).getByText("Video height below minimum")).toBeInTheDocument();
  });

  it("keeps a pending real request in an honest indeterminate state", async () => {
    vi.stubGlobal("fetch", vi.fn((url: RequestInfo | URL) => (
      String(url).endsWith("/capabilities")
        ? Promise.resolve(jsonResponse(capabilitiesFixture()))
        : new Promise<Response>(() => undefined)
    )));
    const user = userEvent.setup();
    render(<App />);

    await selectVideoAndRun(user, "pending.mp4");

    expect(await screen.findByRole("heading", { name: "Checking your video" })).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Scan in progress" })).toBeInTheDocument();
    expect(screen.getByText(/Picture and sound/)).toBeInTheDocument();
    expect(screen.queryByText("Full Review")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Preview application state")).not.toBeInTheDocument();
    expect(screen.queryByText("Inspecting media")).not.toBeInTheDocument();
    expect(screen.queryByTestId("result-state")).not.toBeInTheDocument();
  });

  it("guides a long human-review queue to the next pending item", async () => {
    const user = userEvent.setup();
    render(<ResultsView report={needsReviewReport} previewUrl="blob:original" />);
    const video = screen.getByTestId("preview-video") as HTMLVideoElement;
    await user.click(screen.getByRole("button", { name: "Review next · 0 of 4 reviewed" }));
    expect(video.currentTime).toBe(3);
    await user.click(within(repairItem("Long silent section")).getByRole("button", { name: "Accept" }));
    expect(screen.getByRole("button", { name: "Review next · 1 of 4 reviewed" })).toBeInTheDocument();
  });

  it("renders a separate reusable application error state", () => {
    render(
      <ErrorState
        title="Analysis could not start"
        message="The local backend failed."
        onRetry={() => undefined}
      />,
    );
    expect(screen.getByTestId("error-state")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Analysis could not start" })).toBeInTheDocument();
    expect(screen.getByText(/different from a blocked publishing result/i)).toBeInTheDocument();
  });

  it("handles unusually long finding content without crashing", () => {
    const longReport: PreflightReport = {
      ...needsReviewReport,
      findings: [{
        ...needsReviewReport.findings[0],
        message: `Long diagnostic ${"detail ".repeat(180)}`,
        details: {
          ...needsReviewReport.findings[0].details,
          title: `Long title ${"segment ".repeat(40)}`,
        },
      }],
      warning_count: 1,
    };

    render(<ResultsView report={longReport} />);
    expect(screen.getByText(/Long diagnostic/)).toBeInTheDocument();
  });
});

async function selectVideoAndRun(user: ReturnType<typeof userEvent.setup>, filename: string) {
  const video = new File(["synthetic video bytes"], filename, { type: "video/mp4" });
  await user.upload(screen.getByLabelText("Select video file"), video);
  await user.click(screen.getByRole("button", { name: "Run Preflight" }));
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function capabilitiesFixture(fullReviewAvailable = true) {
  return {
    ffprobe_available: true,
    ffmpeg_available: true,
    gemini_dependency_available: fullReviewAvailable,
    gemini_api_key_configured: fullReviewAvailable,
    full_review_available: fullReviewAvailable,
    metadata_assist_available: fullReviewAvailable,
    local_checks_available: true,
    revision_check_available: true,
    revision_semantic_review_available: true,
    transcription_dependency_available: true,
    transcription_enabled: false,
    supported_review_modes: ["full", "local"],
    maximum_video_upload_size_bytes: 2_147_483_648,
    full_review_unavailable_reasons: fullReviewAvailable ? [] : [{
      code: "gemini_api_key_missing",
      message: "The backend does not have a Gemini API key configured.",
    }],
  };
}

function appFetch(
  scanResponses: Array<() => Promise<Response>>,
): ReturnType<typeof vi.fn> {
  let scanIndex = 0;
  return vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    if (path.endsWith("/capabilities")) {
      return Promise.resolve(jsonResponse(capabilitiesFixture()));
    }
    if (path.endsWith("/preflight/progress") && init?.method === "POST") {
      return Promise.resolve(jsonResponse(progressFixture()));
    }
    if (path.includes("/preflight/progress/") && init?.method === "DELETE") {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    if (path.includes("/preflight/progress/")) {
      return Promise.resolve(jsonResponse(progressFixture()));
    }
    const response = scanResponses[scanIndex++];
    return response ? response() : Promise.reject(new Error("Unexpected scan request"));
  });
}

function progressFixture(): ScanProgress {
  const now = Date.now() / 1000;
  return {
    progress_id: "67e55044-10b1-426f-9247-bb680e5fe0c8",
    review_mode: "full",
    state: "RUNNING",
    stage: "technical_checks",
    percent: 12,
    message: "Checking picture and sound",
    created_at_epoch_seconds: now,
    updated_at_epoch_seconds: now,
    tasks: [
      { task_id: "technical", label: "Picture and sound", status: "Working" },
      { task_id: "opening", label: "Opening review", status: "Waiting" },
      { task_id: "continuity", label: "Edit continuity", status: "Waiting" },
      { task_id: "factual", label: "Content and claims", status: "Waiting" },
      { task_id: "summary", label: "Preparing your review", status: "Waiting" },
    ],
  };
}

function captionFindingReport(): PreflightReport {
  return {
    ...needsReviewReport,
    findings: [
      {
        code: "CAPTION_SPEECH_GAP",
        severity: "warning",
        status: "NEEDS_REVIEW",
        message: "Speech was detected here with little or no caption coverage.",
        source: "captions.speech",
        timestamp_start_seconds: 7,
        timestamp_end_seconds: 10,
        details: {
          category: "captions",
          title: "Possible caption gap",
          duration_seconds: 3,
        },
        suggestion: "Review this section and confirm that spoken content is captioned.",
      },
      {
        code: "CAPTION_PARSE_ERROR",
        severity: "warning",
        status: "NEEDS_REVIEW",
        message: "The supplied caption file contains malformed cue syntax.",
        source: "captions.validation",
        timestamp_start_seconds: null,
        timestamp_end_seconds: null,
        details: {
          category: "captions",
          title: "Caption file could not be parsed cleanly",
        },
        suggestion: "Correct the caption syntax.",
      },
    ],
    caption_summary: {
      source_format: "srt",
      cue_count: 2,
      first_caption_seconds: 0,
      last_caption_seconds: 5,
      covered_duration_seconds: 4,
      timeline_coverage_percent: 33.333,
    },
    warning_count: 2,
  };
}

function repairWorkflowReport(): PreflightReport {
  const duplicate = {
    code: "AI_ACCIDENTAL_REPETITION",
    severity: "warning" as const,
    status: "NEEDS_REVIEW" as const,
    message: "A substantial sequence appears twice.",
    source: "ai.gemini.viewer",
    timestamp_start_seconds: 7,
    timestamp_end_seconds: 10,
    details: {
      category: "editorial",
      title: "Possible duplicated segment",
      original_start_seconds: 4,
      original_end_seconds: 7,
    },
    suggestion: "Review whether the repetition is intentional.",
  };
  const human = needsReviewReport.findings.find((finding) => finding.code === "AUDIO_LONG_SILENCE")!;
  const black = needsReviewReport.findings.find((finding) => finding.code === "VIDEO_BLACK_SEGMENT")!;
  return {
    ...needsReviewReport,
    findings: [black, duplicate, human],
    warning_count: 3,
    repair_plan: {
      proposals: [
        {
          proposal_id: "duplicate-repair",
          finding_code: duplicate.code,
          finding_title: "Possible duplicated segment",
          explanation: "Remove the repeated occurrence while retaining the original reference interval.",
          source: duplicate.source,
          repairability: "SAFE",
          operation: { operation_type: "REMOVE_RANGE", start_seconds: 7, end_seconds: 10 },
          start_seconds: 7,
          end_seconds: 10,
          expected_duration_change_seconds: -3,
          original_start_seconds: 4,
          original_end_seconds: 7,
          evidence: duplicate.details,
        },
        {
          proposal_id: "black-repair",
          finding_code: black.code,
          finding_title: "Sustained near-black section",
          explanation: "Remove the black interval and ripple the remaining video and audio together.",
          source: black.source,
          repairability: "PREVIEW_REQUIRED",
          operation: { operation_type: "REMOVE_RANGE", start_seconds: 2, end_seconds: 5 },
          start_seconds: 2,
          end_seconds: 5,
          expected_duration_change_seconds: -3,
          original_start_seconds: null,
          original_end_seconds: null,
          evidence: black.details,
        },
        {
          proposal_id: "human-review",
          finding_code: human.code,
          finding_title: "Long silent section",
          explanation: "Creator Preflight cannot make this edit without your judgment.",
          source: human.source,
          repairability: "HUMAN_ONLY",
          operation: null,
          start_seconds: human.timestamp_start_seconds,
          end_seconds: human.timestamp_end_seconds,
          expected_duration_change_seconds: null,
          original_start_seconds: null,
          original_end_seconds: null,
          evidence: human.details,
        },
      ],
      safe_count: 1,
      preview_required_count: 1,
      human_only_count: 1,
    },
  };
}

function repairItem(title: string): HTMLElement {
  const queue = screen.getByRole("region", { name: "Action queue" });
  const item = within(queue).getByRole("heading", { name: title }).closest("article");
  if (!item) throw new Error(`Repair item not found for ${title}`);
  return item;
}

function repairVideoResponse(): Response {
  return new Response(new Blob(["repaired-video"], { type: "video/mp4" }), {
    status: 200,
    headers: {
      "Content-Type": "video/mp4",
      "X-Repair-Original-Duration": "12",
      "X-Repair-Output-Duration": "6",
      "X-Repair-Removed-Duration": "3",
    },
  });
}

function verificationFixture(status: "VERIFIED" | "NEEDS_REVIEW" | "INCOMPLETE"): VerificationReport {
  const original = repairWorkflowReport().findings;
  return {
    schema_version: "1.0",
    status,
    approved_repair_count: 2,
    resolved: original.slice(0, 2).map((finding) => ({ status: "RESOLVED", original_finding: finding, repaired_finding: null, expected_repaired_start_seconds: null, expected_repaired_end_seconds: null, deterministically_verified: true, explanation: "The approved interval was removed." })),
    remaining: status === "NEEDS_REVIEW" ? [{ status: "REMAINING", original_finding: original[2], repaired_finding: original[2], expected_repaired_start_seconds: 2, expected_repaired_end_seconds: 3, deterministically_verified: false, explanation: "The finding remains." }] : [],
    new: [],
    unexpected_changes: status === "NEEDS_REVIEW" ? [{ start_seconds: 1, end_seconds: 2, maximum_mean_difference: 40, sample_count: 2 }] : [],
    original_duration_seconds: 12,
    repaired_duration_seconds: 6,
    expected_duration_seconds: 6,
    integrity: { passed: true, duration_matches: true, streams_match: true, resolution_matches: true, operations_verified: 2, reference_intervals_survived: true, explanation: "Integrity passed." },
    repaired_preflight_report: { ...readyReport, scan_completeness: status === "INCOMPLETE" ? "PARTIAL" : "COMPLETE", execution_issues: status === "INCOMPLETE" ? [{ component: "ai.provider", reason_code: "ai_provider_timeout", message: "Remote review timed out.", retryable: true }] : [], media: { ...readyReport.media, duration_seconds: 6 } },
    regression_analysis_completeness: "COMPLETE",
    review_reel_manifest: { entries: [{ reel_start_seconds: 0, reel_end_seconds: 4, source_start_seconds: 0, source_end_seconds: 4, reason: "Approved range removed", category: "repair", source_id: "repair-1" }], total_duration_seconds: 4 },
    review_reel_available: true,
    limitations: [],
  };
}
