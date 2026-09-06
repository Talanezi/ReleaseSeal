import type { Finding } from "../types/preflight";

export function formatTimecode(seconds: number): string {
  const totalHundredths = Math.max(0, Math.round(seconds * 100));
  const hours = Math.floor(totalHundredths / 360000);
  const afterHours = totalHundredths % 360000;
  const minutes = Math.floor(afterHours / 6000);
  const afterMinutes = afterHours % 6000;
  const wholeSeconds = Math.floor(afterMinutes / 100);
  const hundredths = afterMinutes % 100;
  const base = `${minutes.toString().padStart(2, "0")}:${wholeSeconds.toString().padStart(2, "0")}.${hundredths.toString().padStart(2, "0")}`;
  return hours > 0 ? `${hours}:${base}` : base;
}

export function formatInterval(finding: Finding): string | null {
  if (finding.timestamp_start_seconds === null) return null;
  const start = formatTimecode(finding.timestamp_start_seconds);
  if (finding.timestamp_end_seconds === null) return start;
  return `${start}–${formatTimecode(finding.timestamp_end_seconds)}`;
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "Unknown";
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  return hours > 0
    ? `${hours}:${minutes.toString().padStart(2, "0")}:${remainder
        .toString()
        .padStart(2, "0")}`
    : `${minutes}:${remainder.toString().padStart(2, "0")}`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && value >= 1024; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${unit}`;
}

export function findingCategory(finding: Finding): string {
  const category = finding.details?.category;
  if (typeof category === "string") return category;
  return finding.source.split(".")[0] || "package";
}

export function findingTitle(finding: Finding): string {
  const title = finding.details?.title;
  return typeof title === "string" ? title : finding.message;
}
