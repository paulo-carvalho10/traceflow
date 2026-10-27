import { describe, expect, it } from "vitest";

import { errorMessage } from "./api";
import { PERCENTILE_COLORS } from "./colors";
import { formatAgo, formatDuration, shortId } from "./format";
import { MIN_BAR_PERCENT, barPosition, ticks } from "./waterfall";

describe("formatDuration", () => {
  it.each([
    [0.42, "0,4 ms"],
    [87.4, "87 ms"],
    [1234, "1,2 s"],
    [125_000, "2 min 5 s"],
    [120_000, "2 min"],
  ])("%s ms -> %s", (ms, text) => {
    expect(formatDuration(ms).replace(/ /g, " ")).toBe(text);
  });
});

describe("formatAgo", () => {
  const now = Date.parse("2026-10-20T12:00:00Z");
  it("conta para trás em s, min e h", () => {
    expect(formatAgo("2026-10-20T11:59:58Z", now)).toBe("agora");
    expect(formatAgo("2026-10-20T11:59:30Z", now)).toBe("há 30 s");
    expect(formatAgo("2026-10-20T11:57:00Z", now)).toBe("há 3 min");
    expect(formatAgo("2026-10-20T09:00:00Z", now)).toBe("há 3 h");
  });
});

describe("shortId", () => {
  it("encurta só o que é comprido", () => {
    expect(shortId("5b8efff798038103d269b633813fc60c")).toBe("5b8efff7…");
    expect(shortId("abc")).toBe("abc");
  });
});

describe("PERCENTILE_COLORS", () => {
  it("são uma rampa de um tom só, do claro (p50) ao escuro (p99)", () => {
    const light = (hex: string) => parseInt(hex.slice(1, 3), 16) + parseInt(hex.slice(3, 5), 16) + parseInt(hex.slice(5, 7), 16);
    const { p50, p95, p99 } = PERCENTILE_COLORS;
    expect(light(p50)).toBeGreaterThan(light(p95));
    expect(light(p95)).toBeGreaterThan(light(p99));
  });
});

describe("barPosition", () => {
  it("posiciona pelo começo e pela duração", () => {
    expect(barPosition(100, 200, 400)).toEqual({ left: 25, width: 50 });
  });
  it("span minúsculo ainda aparece", () => {
    expect(barPosition(10, 0.01, 2000).width).toBe(MIN_BAR_PERCENT);
  });
  it("nunca passa do fim da linha", () => {
    const bar = barPosition(390, 50, 400);
    expect(bar.left + bar.width).toBeLessThanOrEqual(100);
  });
});

describe("ticks", () => {
  it("usa passos redondos", () => {
    expect(ticks(420)).toEqual([0, 100, 200, 300, 400]);
    expect(ticks(9)).toEqual([0, 2, 4, 6, 8]);
    expect(ticks(2500)).toEqual([0, 500, 1000, 1500, 2000, 2500]);
  });
});

describe("errorMessage", () => {
  it("entende as duas formas de erro do FastAPI", () => {
    expect(errorMessage({ detail: "e-mail ou senha incorretos" }, 401)).toBe("e-mail ou senha incorretos");
    expect(errorMessage({ detail: [{ loc: ["body", "password"], msg: "String should have at least 10 characters" }] }, 422))
      .toBe("password: String should have at least 10 characters");
    expect(errorMessage(null, 500)).toBe("erro 500");
  });
});
