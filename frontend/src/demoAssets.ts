export interface FinalExportDemoPackage {
  video: File;
  title: string;
  description: string;
  captions: File | null;
  thumbnail: File | null;
}

export interface RevisionDemoPackage {
  previousVideo: File;
  revisedVideo: File;
  notes: string;
}

interface OwnerDemoManifest {
  schema_version: "1.0";
  assets: {
    final_export: { video: string; title: string; description: string; captions: string | null; thumbnail: string | null };
    revision: { previous: string; revised: string; notes: string };
  };
}

export function demoAssetLocations(baseUrl: string) {
  const appBase = baseUrl.replace(/\/$/, "");
  const ownerRoot = `${appBase}/demo/owner`;
  const proofRoot = `${appBase}/proof`;
  return {
    ownerRoot,
    ownerManifest: `${ownerRoot}/demo-manifest.json`,
    proofRoot,
    proofBundle: `${proofRoot}/judge-proof.json`,
  };
}

const locations = demoAssetLocations(import.meta.env.BASE_URL);
const OWNER_ROOT = locations.ownerRoot;
const OWNER_MANIFEST = locations.ownerManifest;
const PROOF_ROOT = locations.proofRoot;
const PROOF_BUNDLE = locations.proofBundle;

export async function loadFinalExportDemo(): Promise<FinalExportDemoPackage> {
  const owner = await loadOwnerManifest();
  if (owner) {
    const assets = owner.assets.final_export;
    return {
      video: await fetchFile(ownerAsset(assets.video), assets.video, "video/mp4"),
      title: (await fetchText(ownerAsset(assets.title))).trim(),
      description: (await fetchText(ownerAsset(assets.description))).trim(),
      captions: assets.captions ? await fetchFile(ownerAsset(assets.captions), assets.captions, captionType(assets.captions)) : null,
      thumbnail: assets.thumbnail ? await fetchFile(ownerAsset(assets.thumbnail), assets.thumbnail, imageType(assets.thumbnail)) : null,
    };
  }
  const proof = await loadProofBundle();
  if (!proof) throw new Error("Public demo package unavailable");
  return {
    video: await fetchProofFile(proof.final_export.original_video),
    thumbnail: await fetchProofFile(proof.final_export.thumbnail),
    captions: null,
    title: proof.final_export.title,
    description: proof.final_export.description,
  };
}

export async function revisionDemoAvailable(): Promise<boolean> {
  return (await loadOwnerManifest()) !== null || (await loadProofBundle()) !== null;
}

export async function loadRevisionDemo(): Promise<RevisionDemoPackage> {
  const owner = await loadOwnerManifest();
  if (owner) {
    const assets = owner.assets.revision;
    return {
      previousVideo: await fetchFile(ownerAsset(assets.previous), assets.previous, "video/mp4"),
      revisedVideo: await fetchFile(ownerAsset(assets.revised), assets.revised, "video/mp4"),
      notes: (await fetchText(ownerAsset(assets.notes))).trim(),
    };
  }
  const proof = await loadProofBundle();
  if (!proof) throw new Error("Public demo package unavailable");
  return {
    previousVideo: await fetchProofFile(proof.revision.previous_video),
    revisedVideo: await fetchProofFile(proof.revision.revised_video),
    notes: proof.revision.notes.trim(),
  };
}

async function loadOwnerManifest(): Promise<OwnerDemoManifest | null> {
  try {
    const response = await fetch(OWNER_MANIFEST);
    if (!response.ok) return null;
    const value: unknown = await response.json();
    return isOwnerManifest(value) ? value : null;
  } catch {
    return null;
  }
}

async function loadProofBundle(): Promise<JudgeProofBundle | null> {
  try {
    const response = await fetch(PROOF_BUNDLE);
    if (!response.ok) return null;
    return parseJudgeProofBundle(await response.json());
  } catch {
    return null;
  }
}

function isOwnerManifest(value: unknown): value is OwnerDemoManifest {
  if (!isRecord(value) || value.schema_version !== "1.0" || !isRecord(value.assets)) return false;
  const finalExport = value.assets.final_export;
  const revision = value.assets.revision;
  return isRecord(finalExport) && isAssetName(finalExport.video) && isAssetName(finalExport.title)
    && isAssetName(finalExport.description) && isOptionalAssetName(finalExport.captions) && isOptionalAssetName(finalExport.thumbnail)
    && isRecord(revision) && isAssetName(revision.previous) && isAssetName(revision.revised) && isAssetName(revision.notes);
}

function ownerAsset(name: string): string { return `${OWNER_ROOT}/${name}`; }
function proofAsset(item: ProofArtifact): string {
  if (!/^assets\/[A-Za-z0-9][A-Za-z0-9._-]{0,199}$/.test(item.relative_path)) throw new Error("Invalid proof asset path");
  return `${PROOF_ROOT}/${item.relative_path}`;
}
function artifactName(item: ProofArtifact): string { return item.relative_path.split("/").at(-1) ?? "demo.mp4"; }
function fetchProofFile(item: ProofArtifact): Promise<File> { return fetchFile(proofAsset(item), artifactName(item), item.mime_type); }
function isAssetName(value: unknown): value is string { return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$/.test(value); }
function isOptionalAssetName(value: unknown): value is string | null { return value === null || isAssetName(value); }
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function imageType(name: string): string { return name.toLowerCase().endsWith(".png") ? "image/png" : "image/jpeg"; }
function captionType(name: string): string { return name.toLowerCase().endsWith(".vtt") ? "text/vtt" : "application/x-subrip"; }

async function fetchText(url: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) throw new Error("Demo asset unavailable");
  return response.text();
}

async function fetchFile(url: string, name: string, type: string): Promise<File> {
  const response = await fetch(url);
  if (!response.ok) throw new Error("Demo asset unavailable");
  return new File([await response.blob()], name, { type });
}
import { parseJudgeProofBundle, type JudgeProofBundle, type ProofArtifact } from "./types/judgeProof";
