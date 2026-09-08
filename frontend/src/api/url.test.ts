import { describe, expect, it } from "vitest";
import { buildApiUrl } from "./url";

describe("API URL construction", () => {
  it("keeps local API requests relative by default", () => {
    expect(buildApiUrl("/api/v1/capabilities", "")).toBe("/api/v1/capabilities");
  });

  it("uses the configured hosted backend origin", () => {
    expect(buildApiUrl("/api/v1/preflight/scan", "https://releaseseal-api.onrender.com"))
      .toBe("https://releaseseal-api.onrender.com/api/v1/preflight/scan");
  });

  it("normalizes whitespace and trailing slashes", () => {
    expect(buildApiUrl("/api/v1/capabilities", "  https://api.example.test///  "))
      .toBe("https://api.example.test/api/v1/capabilities");
  });

  it("rejects a non-absolute API path", () => {
    expect(() => buildApiUrl("api/v1/capabilities", "https://api.example.test")).toThrow();
  });
});
