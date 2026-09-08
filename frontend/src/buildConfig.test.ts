import { describe, expect, it } from "vitest";
import { baseForMode } from "../buildConfig";

describe("Vite deployment base", () => {
  it("uses the site root for normal and local builds", () => {
    expect(baseForMode("development")).toBe("/");
    expect(baseForMode("production")).toBe("/");
  });

  it("uses the repository path for GitHub Pages builds", () => {
    expect(baseForMode("github-pages")).toBe("/ReleaseSeal/");
  });
});
