import { afterEach, describe, expect, it, vi } from "vitest";
import { needsReviewReport, revisionCheckReport } from "../mocks/reports";
import { applyRepairs, assistMetadata, checkRevision, fetchCapabilities, PreflightApiError, previewRepair, renderReviewReel, reviewRevisionSemantics, scanPreflight, verifyRepair } from "./preflight";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("preflight API client", () => {
  it("loads typed non-secret backend capabilities", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(capabilitiesFixture())));
    const capabilities = await fetchCapabilities();
    expect(capabilities.full_review_available).toBe(true);
    expect(capabilities.supported_review_modes).toEqual(["full", "local"]);
    expect(capabilities.maximum_video_upload_size_bytes).toBe(2_147_483_648);
  });

  it("constructs the exact multipart scan request without overriding Content-Type", async () => {
    let requestUrl: RequestInfo | URL | undefined;
    let requestInit: RequestInit | undefined;
    vi.stubGlobal("fetch", vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      requestUrl = url;
      requestInit = init;
      return Promise.resolve(jsonResponse(needsReviewReport));
    }));
    const video = new File(["video"], "real video.mp4", { type: "video/mp4" });
    const captions = new File(["WEBVTT"], "captions.vtt", { type: "text/vtt" });
    const thumbnail = new File(["png"], "thumbnail.png", { type: "image/png" });

    const report = await scanPreflight({
      video,
      title: "Exact title",
      description: "First line\nSecond line",
      captions,
      thumbnail,
      reviewMode: "full",
    }, { progressId: "67e55044-10b1-426f-9247-bb680e5fe0c8" });

    expect(requestUrl).toBe("/api/v1/preflight/scan");
    expect(requestInit?.method).toBe("POST");
    expect(requestInit?.headers).toBeUndefined();
    expect(requestInit?.body).toBeInstanceOf(FormData);
    const form = requestInit?.body as FormData;
    const uploadedVideo = form.get("file");
    const uploadedCaptions = form.get("captions");
    const uploadedThumbnail = form.get("thumbnail");
    expect(uploadedVideo).toBeInstanceOf(File);
    expect((uploadedVideo as File).name).toBe("real video.mp4");
    expect((uploadedVideo as File).size).toBe(video.size);
    expect(form.get("title")).toBe("Exact title");
    expect(form.get("description")).toBe("First line\nSecond line");
    expect(form.get("review_mode")).toBe("full");
    expect(form.get("progress_id")).toBe("67e55044-10b1-426f-9247-bb680e5fe0c8");
    expect(uploadedCaptions).toBeInstanceOf(File);
    expect((uploadedCaptions as File).name).toBe("captions.vtt");
    expect((uploadedCaptions as File).size).toBe(captions.size);
    expect(uploadedThumbnail).toBeInstanceOf(File);
    expect((uploadedThumbnail as File).name).toBe("thumbnail.png");
    expect(report).toEqual(needsReviewReport);
  });

  it("constructs and validates the revision multipart request", async () => {
    let body: FormData | undefined;
    vi.stubGlobal("fetch", vi.fn((_url: RequestInfo | URL, init?: RequestInit) => {
      body = init?.body as FormData;
      return Promise.resolve(jsonResponse(revisionCheckReport));
    }));
    const previous = new File(["previous"], "previous cut.mp4", { type: "video/mp4" });
    const revised = new File(["revised"], "revised cut.mp4", { type: "video/mp4" });
    const report = await checkRevision({ previousVideo: previous, revisedVideo: revised, notes: "00:12 Remove old section" });
    expect((body?.get("previous_file") as File).name).toBe("previous cut.mp4");
    expect((body?.get("revised_file") as File).name).toBe("revised cut.mp4");
    expect(body?.get("notes")).toBe("00:12 Remove old section");
    expect(report.additional_change_count).toBe(2);
  });

  it("rejects a malformed revision response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ ...revisionCheckReport, revision_map: { unchanged_ratio: 2 } })));
    await expect(checkRevision({
      previousVideo: new File(["a"], "a.mp4"), revisedVideo: new File(["b"], "b.mp4"), notes: "",
    })).rejects.toMatchObject({ code: "revision_invalid_response" });
  });

  it("constructs and validates the explicit semantic revision request", async () => {
    let body: FormData | undefined;
    vi.stubGlobal("fetch", vi.fn((_url: RequestInfo | URL, init?: RequestInit) => {
      body = init?.body as FormData;
      return Promise.resolve(jsonResponse(semanticReviewFixture));
    }));
    const previous = new File(["previous"], "previous.mp4");
    const revised = new File(["revised"], "revised.mp4");
    const result = await reviewRevisionSemantics({ previousVideo: previous, revisedVideo: revised, revisionCheck: revisionCheckReport });
    expect((body?.get("previous_file") as File).name).toBe("previous.mp4");
    expect(JSON.parse(String(body?.get("revision_check_json"))).schema_version).toBe("1.0");
    expect(result.results[0].status).toBe("APPEARS_SATISFIED");
  });

  it("omits optional captions and thumbnail when none were selected", async () => {
    let body: FormData | undefined;
    vi.stubGlobal("fetch", vi.fn((_url: RequestInfo | URL, init?: RequestInit) => {
      body = init?.body as FormData;
      return Promise.resolve(jsonResponse(needsReviewReport));
    }));

    await scanPreflight({
      video: new File(["video"], "video.mp4", { type: "video/mp4" }),
      title: "Title",
      description: "Description",
      reviewMode: "local",
    });

    expect(body?.has("captions")).toBe(false);
    expect(body?.has("thumbnail")).toBe(false);
  });

  it("submits one explicit metadata-assist upload and validates both suggestions", async () => {
    let requestUrl: RequestInfo | URL | undefined;
    let body: FormData | undefined;
    vi.stubGlobal("fetch", vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      requestUrl = url;
      body = init?.body as FormData;
      return Promise.resolve(jsonResponse({
        title_suggestions: ["One", "Two", "Three", "Four", "Five"],
        description_draft: "A concise description based on the selected video.",
        cleanup_succeeded: true,
      }));
    }));
    const video = new File(["video"], "metadata source.mp4", { type: "video/mp4" });
    const captions = new File(["1\n00:00:00,000 --> 00:00:01,000\nOpening\n"], "captions.srt", { type: "text/plain" });

    const result = await assistMetadata(video, { captions });

    expect(requestUrl).toBe("/api/v1/metadata/assist");
    expect((body?.get("file") as File).name).toBe("metadata source.mp4");
    expect((body?.get("captions") as File).name).toBe("captions.srt");
    expect(result.title_suggestions).toHaveLength(5);
    expect(result.description_draft).toMatch(/selected video/);
  });

  it("surfaces a safe structured invalid-media error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      error: {
        code: "invalid_media",
        message: "FFprobe could not parse the supplied media file.",
        details: { ffprobe_exit_code: 1 },
      },
    }, 400)));

    await expect(scanPreflight({
      video: new File(["bad"], "bad.mp4", { type: "video/mp4" }),
      title: "",
      description: "",
      reviewMode: "local",
    })).rejects.toMatchObject({
      code: "invalid_media",
      message: "FFprobe could not parse the supplied media file.",
      status: 400,
    });
  });

  it("rejects a malformed successful response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ verdict: "READY" })));

    await expect(scanPreflight({
      video: new File(["video"], "video.mp4", { type: "video/mp4" }),
      title: "Title",
      description: "Description",
      reviewMode: "local",
    })).rejects.toBeInstanceOf(PreflightApiError);
  });

  it("accepts the real caption summary contract", async () => {
    const captionReport = {
      ...needsReviewReport,
      caption_summary: {
        source_format: "vtt",
        cue_count: 3,
        first_caption_seconds: 0,
        last_caption_seconds: 12,
        covered_duration_seconds: 10.5,
        timeline_coverage_percent: 87.5,
      },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(captionReport)));

    const report = await scanPreflight({
      video: new File(["video"], "video.mp4", { type: "video/mp4" }),
      title: "Title",
      description: "Description",
      reviewMode: "local",
    });

    expect(report.caption_summary).toEqual(captionReport.caption_summary);
  });

  it("rejects a malformed Promise Check summary", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      ...needsReviewReport,
      promise_check: { ...needsReviewReport.promise_check, status: "pretend_aligned" },
    })));
    await expect(scanPreflight({
      video: new File(["video"], "video.mp4", { type: "video/mp4" }),
      title: "Title",
      description: "Description",
      reviewMode: "local",
    })).rejects.toMatchObject({ code: "invalid_response" });
  });

  it("constructs narrow preview and apply multipart repair requests", async () => {
    const requests: Array<{ url: string; form: FormData }> = [];
    vi.stubGlobal("fetch", vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      requests.push({ url: String(url), form: init?.body as FormData });
      return Promise.resolve(videoResponse());
    }));
    const source = new File(["source"], "original.mp4", { type: "video/mp4" });
    const operation = { operation_type: "REMOVE_RANGE" as const, start_seconds: 2, end_seconds: 5 };

    const preview = await previewRepair(source, operation);
    const applied = await applyRepairs(source, [operation]);

    expect(requests.map((item) => item.url)).toEqual([
      "/api/v1/repairs/preview",
      "/api/v1/repairs/apply",
    ]);
    expect(JSON.parse(String(requests[0].form.get("operation_json")))).toEqual(operation);
    expect(JSON.parse(String(requests[1].form.get("operations_json")))).toEqual({ operations: [operation] });
    expect((requests[0].form.get("file") as File).name).toBe("original.mp4");
    expect(preview.outputDurationSeconds).toBe(6);
    expect(applied.removedDurationSeconds).toBe(3);
  });

  it("surfaces structured repair-render failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      error: { code: "repair_ranges_overlap", message: "Approved repair ranges must not overlap.", details: null },
    }, 400)));
    await expect(applyRepairs(
      new File(["source"], "source.mp4", { type: "video/mp4" }),
      [
        { operation_type: "REMOVE_RANGE", start_seconds: 1, end_seconds: 3 },
        { operation_type: "REMOVE_RANGE", start_seconds: 2, end_seconds: 4 },
      ],
    )).rejects.toMatchObject({ code: "repair_ranges_overlap", status: 400 });
  });

  it("submits repaired verification and Review Reel multipart requests", async () => {
    const requests: Array<{ url: string; form: FormData }> = [];
    vi.stubGlobal("fetch", vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      requests.push({ url: String(url), form: init?.body as FormData });
      return Promise.resolve(String(url).endsWith("review-reel") ? videoResponse() : jsonResponse(verificationResponse()));
    }));
    const original = new File(["original"], "original.mp4", { type: "video/mp4" });
    const repaired = new File(["repaired"], "original.repaired.mp4", { type: "video/mp4" });
    const operation = { operation_type: "REMOVE_RANGE" as const, start_seconds: 2, end_seconds: 5 };
    const verification = await verifyRepair({ originalVideo: original, repairedVideo: repaired, operations: [operation], originalReport: needsReviewReport, title: "Title", description: "Description", reviewMode: "local" });
    await renderReviewReel(repaired, verification.review_reel_manifest);
    expect(requests.map((item) => item.url)).toEqual(["/api/v1/repairs/verify", "/api/v1/repairs/review-reel"]);
    expect((requests[0].form.get("original_file") as File).name).toBe("original.mp4");
    expect((requests[0].form.get("repaired_file") as File).name).toBe("original.repaired.mp4");
    expect(JSON.parse(String(requests[0].form.get("operations_json")))).toEqual({ operations: [operation] });
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function capabilitiesFixture() {
  return {
    ffprobe_available: true,
    ffmpeg_available: true,
    gemini_dependency_available: true,
    gemini_api_key_configured: true,
      full_review_available: true,
      metadata_assist_available: true,
    local_checks_available: true,
    revision_check_available: true,
    revision_semantic_review_available: true,
    transcription_dependency_available: true,
    transcription_enabled: false,
    supported_review_modes: ["full", "local"],
    maximum_video_upload_size_bytes: 2_147_483_648,
    full_review_unavailable_reasons: [],
  };
}

const semanticReviewFixture = {
  schema_version: "1.0", provider: "gemini", model: "fake-flash", eligible_count: 1, requested_count: 1,
  reviewed_count: 1, appears_satisfied_count: 1, appears_unresolved_count: 0, inconclusive_count: 0, not_reviewed_count: 0,
  results: [{ request_id: "request-0001", status: "APPEARS_SATISFIED", confidence: .95, rationale: "The revised graphic appears to show 2025.", observed_previous: "2024", observed_revised: "2025", reviewed_previous_range: { start_seconds: 8, end_seconds: 16 }, reviewed_revised_range: { start_seconds: 3, end_seconds: 11 }, partial_evidence: false, limitation: null, reason_code: null }],
  evidence_render_seconds: .2, provider_seconds: 1.2, total_seconds: 1.4, upload_count: 2, generation_count: 1, delete_count: 2,
};

function videoResponse(): Response {
  return new Response(new Blob(["repaired-video"], { type: "video/mp4" }), {
    status: 200,
    headers: {
      "Content-Type": "video/mp4",
      "X-Repair-Original-Duration": "9",
      "X-Repair-Output-Duration": "6",
      "X-Repair-Removed-Duration": "3",
    },
  });
}

function verificationResponse() {
  return {
    schema_version: "1.0", status: "VERIFIED", approved_repair_count: 1,
    resolved: [], remaining: [], new: [], unexpected_changes: [],
    original_duration_seconds: 9, repaired_duration_seconds: 6, expected_duration_seconds: 6,
    integrity: { passed: true, duration_matches: true, streams_match: true, resolution_matches: true, operations_verified: 1, reference_intervals_survived: true, explanation: "Passed." },
    repaired_preflight_report: { ...needsReviewReport, media: { ...needsReviewReport.media, duration_seconds: 6 } },
    regression_analysis_completeness: "COMPLETE",
    review_reel_manifest: { entries: [{ reel_start_seconds: 0, reel_end_seconds: 2, source_start_seconds: 0, source_end_seconds: 2, reason: "Repair", category: "repair", source_id: "repair-1" }], total_duration_seconds: 2 },
    review_reel_available: true, limitations: [],
  };
}
