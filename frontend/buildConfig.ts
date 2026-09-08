export function baseForMode(mode: string): string {
  return mode === "github-pages" ? "/ReleaseSeal/" : "/";
}
