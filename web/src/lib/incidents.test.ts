import { describe, expect, it } from "vitest";

import { describeRule, formatElapsed, recovery, tracesPeriodFor } from "./incidents";

describe("describeRule", () => {
  it("taxa de erro em porcentagem, para qualquer serviço", () => {
    expect(
      describeRule({ target: "*", metric: "error_rate", operator: ">=", threshold: 0.05, relative: false, min_requests: 20 }),
    ).toBe("Se a taxa de erro de qualquer serviço for ≥ 5%, com ao menos 20 requisições em 10 s");
  });
  it("latência relativa à linha de base", () => {
    expect(
      describeRule({ target: "payments", metric: "p95_ms", operator: ">=", threshold: 2, relative: true, min_requests: 20 }),
    ).toBe(
      "Se o p95 de payments for ≥ 2× a linha de base (e pelo menos 50 ms acima dela), com ao menos 20 requisições em 10 s",
    );
  });
  it("latência absoluta e disponibilidade", () => {
    expect(describeRule({ target: "*", metric: "p99_ms", operator: ">=", threshold: 1500, relative: false, min_requests: 5 })).toContain(
      "≥ 1.500 ms",
    );
    expect(describeRule({ target: "*", metric: "availability", operator: "<=", threshold: 0.995, relative: false, min_requests: 5 })).toContain(
      "≤ 99,5%",
    );
  });
});

describe("formatElapsed", () => {
  const t0 = Date.UTC(2026, 9, 22, 14, 0, 0);
  it("segundos, minutos e horas, como se fala", () => {
    expect(formatElapsed(t0, t0 + 45_000)).toBe("45 s");
    expect(formatElapsed(t0, t0 + 192_000)).toBe("3 min 12 s");
    expect(formatElapsed(t0, t0 + 180_000)).toBe("3 min");
    expect(formatElapsed(t0, t0 + 3_900_000)).toBe("1 h 5 min");
  });
});

describe("tracesPeriodFor", () => {
  it("o menor período pronto que cobre o incidente", () => {
    const now = Date.UTC(2026, 9, 22, 14, 0, 0);
    expect(tracesPeriodFor(new Date(now - 10 * 60_000).toISOString(), now)).toBe("1h");
    expect(tracesPeriodFor(new Date(now - 3 * 3_600_000).toISOString(), now)).toBe("6h");
    expect(tracesPeriodFor(new Date(now - 30 * 3_600_000).toISOString(), now)).toBe("3d");
  });
});

describe("recovery", () => {
  const now = Date.UTC(2026, 9, 22, 14, 0, 30);
  it("ainda doente: não está em recuperação", () => {
    expect(recovery({ healthy_since: null, resolve_after_s: 30 }, now)).toBeNull();
  });
  it("saudável há 12 s: resolve em 18 s", () => {
    const since = new Date(now - 12_000).toISOString();
    expect(recovery({ healthy_since: since, resolve_after_s: 30 }, now)).toEqual({ healthyFor: 12, resolvesIn: 18, progress: 0.4 });
  });
  it("passou do prazo (o retrato de resolvido ainda não chegou): não fica negativo", () => {
    const since = new Date(now - 40_000).toISOString();
    expect(recovery({ healthy_since: since, resolve_after_s: 30 }, now)).toMatchObject({ resolvesIn: 0, progress: 1 });
  });
});
