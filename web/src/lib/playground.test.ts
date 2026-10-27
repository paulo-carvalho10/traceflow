import { describe, expect, it } from "vitest";

import type { Experiment, IncidentSummary } from "@/lib/api";
import type { LiveIncident } from "@/lib/live";

import { experimentCycle, incidentFor } from "./playground";

const T0 = Date.UTC(2026, 9, 23, 14, 0, 0);
const iso = (secondsAfter: number) => new Date(T0 + secondsAfter * 1000).toISOString();

const experiment: Experiment = {
  id: "e1",
  kind: "scenario",
  scenario_id: "pagamentos-instaveis",
  title: "Pagamentos instáveis",
  faults: { payments: { latency_ms: 0, error_rate: 0.3, down: false } },
  expect_cause: ["payments"],
  expect_severity: "SEV1",
  started_at: iso(0),
  expires_at: iso(180),
  ended_at: null,
  ended_by: null,
};

const incident: IncidentSummary = {
  id: "i1",
  environment: "demo",
  status: "open",
  severity: "SEV1",
  peak_severity: "SEV1",
  title: "payments falhando",
  opened_at: iso(9),
  resolved_at: null,
  causes: ["payments"],
};

const state = (steps: ReturnType<typeof experimentCycle>) => Object.fromEntries(steps.map((s) => [s.key, s.state]));

describe("incidentFor", () => {
  it("é o primeiro incidente aberto depois de a falha começar", () => {
    const older = { ...incident, id: "velho", opened_at: iso(-600), status: "resolved" as const, resolved_at: iso(-500) };
    expect(incidentFor(experiment, [older, incident])?.id).toBe("i1");
  });

  it("sem incidente novo, a falha continua no que ainda se recuperava quando ela começou", () => {
    const recovering = { ...incident, id: "anterior", opened_at: iso(-80), resolved_at: null };
    const past = { ...incident, id: "antigo", opened_at: iso(-900), status: "resolved" as const, resolved_at: iso(-800) };
    expect(incidentFor(experiment, [past, recovering])?.id).toBe("anterior");
    const steps = experimentCycle(experiment, recovering, null, T0 + 10_000);
    expect(steps.find((s) => s.key === "detected")).toMatchObject({
      state: "done",
      label: "Detectado: incidente já aberto",
    });
    expect(incidentFor(experiment, [past])).toBeNull(); // o antigo já tinha resolvido: não é desta falha
  });
});

describe("experimentCycle", () => {
  it("logo depois de injetar: esperando a detecção", () => {
    const steps = experimentCycle(experiment, null, null, T0 + 4_000);
    expect(state(steps)).toMatchObject({ injected: "done", detected: "current", cause: "pending" });
    expect(steps[1].detail).toBe("esperando… 4 s");
  });

  it("detectado em 9 s, com a causa e a severidade conferidas", () => {
    const steps = experimentCycle(experiment, incident, null, T0 + 20_000);
    expect(steps.find((s) => s.key === "detected")?.detail).toBe("9 s depois");
    expect(steps.find((s) => s.key === "cause")).toMatchObject({ ok: true, detail: "payments: acertou" });
    expect(steps.find((s) => s.key === "severity")).toMatchObject({ ok: true, detail: "SEV1: como esperado" });
    expect(state(steps).ended).toBe("current"); // o próximo a acontecer: a falha acabar
  });

  it("causa diferente da esperada: 'até agora' enquanto a falha vale, e erro depois que ela assentou", () => {
    const wrong = { ...incident, causes: ["orders"] };
    const cause = (exp: Experiment, now: number) => experimentCycle(exp, wrong, null, now).find((s) => s.key === "cause");
    expect(cause(experiment, T0 + 20_000)).toEqual({
      key: "cause",
      label: "Causa provável",
      state: "current",
      detail: "orders até agora (esperado: payments)",
    });
    const ended = { ...experiment, ended_at: iso(60), ended_by: "stopped" as const };
    expect(cause(ended, T0 + 70_000)?.state).toBe("current"); // 10 s depois do fim: o retrato ainda inclui a falha
    expect(cause(ended, T0 + 80_000)).toMatchObject({ state: "done", ok: false, detail: "orders (esperado: payments)" });
  });

  it("o incidente abre como SEV2 e sobe para SEV1: no começo não é erro, é 'até agora'", () => {
    const opening = { ...incident, severity: "SEV2", peak_severity: "SEV2" };
    const severity = (inc: IncidentSummary) => experimentCycle(experiment, inc, null, T0 + 12_000).find((s) => s.key === "severity");
    expect(severity(opening)).toMatchObject({ state: "current", detail: "SEV2 até agora (esperado: SEV1)" });
    expect(severity(opening)?.ok).toBeUndefined();
    expect(severity(incident)).toMatchObject({ state: "done", ok: true, detail: "SEV1: como esperado" });
  });

  it("em recuperação, e depois resolvido", () => {
    const ended = { ...experiment, ended_at: iso(60), ended_by: "stopped" as const };
    const live = { causes: [], peak_severity: "SEV1", healthy_since: iso(75), resolve_after_s: 30 } as unknown as LiveIncident;
    const healing = experimentCycle(ended, incident, live, T0 + 85_000);
    expect(healing.find((s) => s.key === "recovering")).toMatchObject({ state: "current", detail: "tudo saudável há 10 s · resolve em 20 s" });
    // sem causas no retrato ao vivo, vale a do incidente: o veredito não some na recuperação
    expect(healing.find((s) => s.key === "cause")).toMatchObject({ ok: true, detail: "payments: acertou" });
    const done = experimentCycle(ended, { ...incident, status: "resolved", resolved_at: iso(105) }, null, T0 + 110_000);
    expect(state(done)).toMatchObject({ ended: "done", recovering: "done", resolved: "done" });
    expect(done.at(-1)?.detail).toBe("o incidente durou 1 min 36 s");
  });

  it("sem incidente em 1 min, avisa", () => {
    expect(experimentCycle(experiment, null, null, T0 + 61_000)[1].state).toBe("missed");
  });
});
