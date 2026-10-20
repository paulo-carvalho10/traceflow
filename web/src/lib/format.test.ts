import { describe, expect, it } from "vitest";

import { reconnectDelay } from "./live";
import { formatPercent, formatRate } from "./format";

describe("formatRate e formatPercent", () => {
  it("formata taxa e porcentagem em português", () => {
    expect(formatRate(20.14)).toBe("20,1/s");
    expect(formatRate(0)).toBe("0/s");
    expect(formatPercent(0.0525)).toBe("5,3%");
    expect(formatPercent(1)).toBe("100%");
    expect(formatPercent(null)).toBe("–");
  });
});

describe("reconnectDelay", () => {
  it("espera cada vez mais, até 15 s", () => {
    expect([0, 1, 2, 3, 4, 10].map(reconnectDelay)).toEqual([1000, 2000, 4000, 8000, 15000, 15000]);
  });
});
