import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

class FetchBackedXMLHttpRequest {
  readonly upload: { onprogress: ((event: ProgressEvent) => void) | null; onload: (() => void) | null } = {
    onprogress: null,
    onload: null,
  };
  status = 0;
  statusText = "";
  responseText = "";
  responseType: XMLHttpRequestResponseType = "";
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  private method = "GET";
  private url = "";
  private responseHeaders = "";
  private aborted = false;
  private controller: AbortController | null = null;

  open(method: string, url: string | URL) {
    this.method = method;
    this.url = String(url);
  }

  send(body?: Document | XMLHttpRequestBodyInit | null) {
    this.controller = new AbortController();
    const total = estimateFormSize(body);
    this.upload.onprogress?.(new ProgressEvent("progress", { lengthComputable: true, loaded: Math.floor(total / 2), total }));
    this.upload.onprogress?.(new ProgressEvent("progress", { lengthComputable: true, loaded: total, total }));
    this.upload.onload?.();
    void fetch(this.url, { method: this.method, body: body as BodyInit | null | undefined, signal: this.controller.signal }).then(async (response) => {
      if (this.aborted) return;
      this.status = response.status;
      this.statusText = response.statusText;
      this.responseText = await response.text();
      this.responseHeaders = [...response.headers.entries()].map(([key, value]) => `${key}: ${value}`).join("\r\n");
      this.onload?.();
    }).catch(() => {
      if (!this.aborted) this.onerror?.();
    });
  }

  abort() {
    if (this.aborted) return;
    this.aborted = true;
    this.controller?.abort();
    this.onabort?.();
  }

  getAllResponseHeaders() {
    return this.responseHeaders;
  }
}

function estimateFormSize(body: Document | XMLHttpRequestBodyInit | null | undefined): number {
  if (!(body instanceof FormData)) return 1;
  let total = 0;
  for (const value of body.values()) total += typeof value === "string" ? new Blob([value]).size : value.size;
  return Math.max(1, total);
}

Object.defineProperty(globalThis, "XMLHttpRequest", {
  configurable: true,
  writable: true,
  value: FetchBackedXMLHttpRequest,
});

afterEach(cleanup);
