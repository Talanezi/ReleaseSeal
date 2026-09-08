import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { loadFinalExportDemo, loadRevisionDemo, revisionDemoAvailable } from "./demoAssets";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("demo asset manifest", () => {
  it("uses the tracked Final Export fallback as real File objects when no owner manifest exists", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("demo-manifest.json")) return Promise.resolve(new Response("", { status: 404 }));
      if (path.endsWith("-title.txt")) return Promise.resolve(new Response("Fallback title\n"));
      if (path.endsWith("-description.txt")) return Promise.resolve(new Response("Fallback description\n"));
      if (path.endsWith("-captions.srt")) return Promise.resolve(new Response("captions"));
      if (path.endsWith("-thumbnail.png")) return Promise.resolve(new Response("image"));
      if (path.endsWith("-demo.mp4")) return Promise.resolve(new Response("video"));
      return Promise.reject(new Error(`Unexpected path ${path}`));
    }));

    const demo = await loadFinalExportDemo();
    expect(demo.video).toBeInstanceOf(File);
    expect(demo.video.name).toBe("releaseseal-official-demo.mp4");
    expect(demo.title).toBe("Fallback title");
    expect(await revisionDemoAvailable()).toBe(false);
  });

  it("loads owner Final Export and Revision assets from one validated manifest", async () => {
    const manifest = ownerManifest();
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("demo-manifest.json")) return Promise.resolve(Response.json(manifest));
      if (path.endsWith(".txt")) return Promise.resolve(new Response(path.endsWith("notes.txt") ? "00:12 Remove aside\n" : "Owner copy\n"));
      if (path.endsWith(".mp4")) return Promise.resolve(new Response("video"));
      if (path.endsWith(".jpg")) return Promise.resolve(new Response("jpeg"));
      return Promise.reject(new Error(`Unexpected path ${path}`));
    }));

    const finalExport = await loadFinalExportDemo();
    const revision = await loadRevisionDemo();
    expect(finalExport.video.name).toBe("final-export-demo.mp4");
    expect(finalExport.captions).toBeNull();
    expect(finalExport.thumbnail).toBeInstanceOf(File);
    expect(finalExport.thumbnail?.name).toBe("final-export-thumbnail.jpg");
    expect(finalExport.thumbnail?.type).toBe("image/jpeg");
    expect(revision.previousVideo).toBeInstanceOf(File);
    expect(revision.previousVideo.name).toBe("revision-previous.mp4");
    expect(revision.revisedVideo.name).toBe("revision-revised.mp4");
    expect(revision.notes).toBe("00:12 Remove aside");
  });

  it("exposes the revision demo action only for an installed valid owner package", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/capabilities")) return Promise.resolve(Response.json(capabilities()));
      if (path.endsWith("demo-manifest.json")) return Promise.resolve(Response.json(ownerManifest()));
      if (path.endsWith("notes.txt")) return Promise.resolve(new Response("00:12 Remove aside"));
      if (path.endsWith(".mp4")) return Promise.resolve(new Response("video"));
      return Promise.reject(new Error(`Unexpected path ${path}`));
    }));

    render(<App />);
    await user.click(screen.getByRole("button", { name: /Revision Compare/i }));
    const load = await screen.findByRole("button", { name: "Load revision demo" });
    await user.click(load);
    expect(await screen.findByText("revision-previous.mp4")).toBeInTheDocument();
    expect(screen.getByText("revision-revised.mp4")).toBeInTheDocument();
    expect(screen.getByLabelText(/Revision notes/)).toHaveValue("00:12 Remove aside");
  });
});

function ownerManifest() {
  return {
    schema_version: "1.0",
    assets: {
      final_export: { video: "final-export-demo.mp4", title: "title.txt", description: "description.txt", captions: null, thumbnail: "final-export-thumbnail.jpg" },
      revision: { previous: "revision-previous.mp4", revised: "revision-revised.mp4", notes: "notes.txt" },
    },
  };
}

function capabilities() {
  return {
    ffmpeg_available: true, ffprobe_available: true, gemini_dependency_installed: false,
    gemini_api_key_configured: false, full_review_available: false, release_contract_extraction_available: false, transcription_dependency_installed: false,
    transcription_enabled: false, local_evidence_recovery_available: false, local_caption_generation_available: false, supported_review_modes: ["local", "full"], maximum_video_upload_size_bytes: 2147483648,
    maximum_thumbnail_upload_size_bytes: 5242880, maximum_thumbnail_pixels: 20000000, maximum_concurrent_scans: 2,
    revision_check_available: true, revision_semantic_review_available: false,
  };
}
