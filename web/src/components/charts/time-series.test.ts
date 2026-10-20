import { describe, expect, it } from "vitest";

import { labelsCollide } from "./time-series";

const series = [
  { key: "p50", label: "p50", color: "#000" },
  { key: "p95", label: "p95", color: "#000" },
  { key: "p99", label: "p99", color: "#000" },
];

describe("labelsCollide", () => {
  it("linhas que terminam longe umas das outras ganham rótulo", () => {
    expect(labelsCollide([{ t: 1, p50: 20, p95: 200, p99: 600 }], series, 200)).toBe(false);
  });
  it("linhas que terminam coladas não ganham (a legenda e a dica identificam)", () => {
    expect(labelsCollide([{ t: 1, p50: 470, p95: 480, p99: 577 }], series, 200)).toBe(true);
  });
  it("linha sem valor no fim também desliga os rótulos", () => {
    expect(labelsCollide([{ t: 1, p50: 20, p95: null, p99: 600 }], series, 200)).toBe(true);
  });
});
