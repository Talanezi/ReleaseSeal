export function buildApiUrl(path: string, baseUrl = ""): string {
  if (!path.startsWith("/")) throw new Error("API paths must start with '/'.");
  const normalizedBase = baseUrl.trim().replace(/\/+$/, "");
  return normalizedBase ? `${normalizedBase}${path}` : path;
}

export function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(buildApiUrl(path, import.meta.env.VITE_API_BASE_URL ?? ""), init);
}
