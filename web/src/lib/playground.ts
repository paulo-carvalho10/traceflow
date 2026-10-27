import type { Experiment, IncidentSummary } from "@/lib/api";
import { formatElapsed, recovery } from "@/lib/incidents";
import type { LiveIncident } from "@/lib/live";

/**
 * O ciclo de um experimento do Playground, passo a passo: a falha entra, o TraceFlow detecta,
 * aponta a causa (e a tela confere se acertou), a falha acaba, o sistema se recupera e o
 * incidente resolve. Função pura: recebe o que a API e o retrato ao vivo dizem, e o "agora".
 */

export type StepState = "done" | "current" | "pending" | "missed";
export type CycleStep = { key: string; label: string; state: StepState; at?: string; detail?: string; ok?: boolean };

const DETECTION_GRACE_MS = 5_000; // um incidente que abriu um pouco antes (relógios, lotes) ainda é deste experimento
const NO_DETECTION_AFTER_MS = 60_000; // sem incidente em 1 min: algo não está como deveria
// o retrato olha 10 s que terminam 3 s atrás: até uns 13 s depois do fim, os números ainda incluem a falha
const SETTLE_MS = 15_000;

/**
 * O incidente desta falha: o primeiro que abriu depois de ela começar. Se nenhum abriu, e um
 * incidente anterior ainda estava aberto quando ela começou (em recuperação, na carência de
 * 30 s), a falha continua nele: o motor não abre um incidente novo para a mesma doença.
 */
export function incidentFor(experiment: Experiment, incidents: IncidentSummary[]): IncidentSummary | null {
  const started = new Date(experiment.started_at).getTime();
  const start = started - DETECTION_GRACE_MS;
  const end = new Date(experiment.ended_at ?? experiment.expires_at).getTime();
  const byOpening = (a: IncidentSummary, b: IncidentSummary) => new Date(a.opened_at).getTime() - new Date(b.opened_at).getTime();
  const fresh = incidents
    .filter((i) => {
      const opened = new Date(i.opened_at).getTime();
      return opened >= start && opened <= end;
    })
    .sort(byOpening);
  if (fresh[0]) return fresh[0];
  const ongoing = incidents
    .filter((i) => new Date(i.opened_at).getTime() < start && (i.resolved_at === null || new Date(i.resolved_at).getTime() > started))
    .sort(byOpening);
  return ongoing.at(-1) ?? null;
}

export function experimentCycle(
  experiment: Experiment,
  incident: IncidentSummary | null,
  live: LiveIncident | null,
  now: number = Date.now(),
): CycleStep[] {
  const started = new Date(experiment.started_at).getTime();
  const after = (iso: string) => `${Math.max(0, Math.round((new Date(iso).getTime() - started) / 1000))} s depois`;
  const resolved = incident?.status === "resolved";
  // enquanto a falha vale, a causa e a severidade ainda mudam: o incidente abre antes de todos
  // os serviços adoecerem, e o pico da severidade só sobe
  const settled = resolved || (experiment.ended_at != null && now - new Date(experiment.ended_at).getTime() > SETTLE_MS);
  const steps: CycleStep[] = [];

  steps.push({ key: "injected", label: "Falha injetada", state: "done", at: experiment.started_at, detail: experiment.title });

  if (incident && new Date(incident.opened_at).getTime() < started - DETECTION_GRACE_MS) {
    steps.push({
      key: "detected",
      label: "Detectado: incidente já aberto",
      state: "done",
      at: incident.opened_at,
      detail: "o anterior ainda se recuperava, e a falha continua nele",
    });
  } else if (incident) {
    steps.push({
      key: "detected",
      label: "Detectado: incidente aberto",
      state: "done",
      at: incident.opened_at,
      detail: after(incident.opened_at),
    });
  } else {
    const waited = now - started;
    steps.push(
      waited > NO_DETECTION_AFTER_MS
        ? { key: "detected", label: "Detecção", state: "missed", detail: "nenhum incidente em 1 min: o tráfego está ligado?" }
        : { key: "detected", label: "Detecção", state: "current", detail: `esperando… ${Math.round(waited / 1000)} s` },
    );
  }

  const liveCauses = live?.causes.map((c) => c.node) ?? [];
  const causes = liveCauses.length ? liveCauses : (incident?.causes ?? []);
  if (causes.length) {
    steps.push(
      verdict(
        {
          key: "cause",
          label: "Causa provável",
          got: causes.join(", "),
          expected: experiment.expect_cause.join(", "),
          ok: experiment.expect_cause.includes(causes[0]),
          okText: "acertou",
        },
        settled,
      ),
    );
  } else {
    steps.push({ key: "cause", label: "Causa provável", state: incident ? "current" : "pending" });
  }

  if (experiment.expect_severity) {
    const peak = live?.peak_severity ?? incident?.peak_severity;
    const expected = experiment.expect_severity;
    steps.push(
      peak
        ? verdict({ key: "severity", label: "Severidade", got: peak, expected, ok: peak === expected, okText: "como esperado" }, settled)
        : { key: "severity", label: "Severidade", state: "pending" },
    );
  }

  if (experiment.ended_at) {
    steps.push({
      key: "ended",
      label: experiment.ended_by === "stopped" ? "Falha encerrada" : "A falha expirou",
      state: "done",
      at: experiment.ended_at,
    });
  } else {
    const left = Math.max(0, Math.round((new Date(experiment.expires_at).getTime() - now) / 1000));
    steps.push({ key: "ended", label: "Fim da falha", state: "pending", detail: `termina sozinha em ${clock(left)}` });
  }

  const healing = live ? recovery(live, now) : null;
  steps.push(
    resolved
      ? { key: "recovering", label: "Recuperação", state: "done" }
      : healing
        ? {
            key: "recovering",
            label: "Recuperação",
            state: "current",
            detail: `tudo saudável há ${healing.healthyFor} s · resolve em ${healing.resolvesIn} s`,
          }
        : { key: "recovering", label: "Recuperação", state: "pending" },
  );

  steps.push(
    resolved && incident?.resolved_at
      ? {
          key: "resolved",
          label: "Resolvido",
          state: "done",
          at: incident.resolved_at,
          detail: `o incidente durou ${formatElapsed(incident.opened_at, incident.resolved_at)}`,
        }
      : { key: "resolved", label: "Resolvido", state: "pending" },
  );

  // o passo "atual" é o primeiro que ainda não aconteceu (se nenhum outro já se marcou como atual)
  if (!steps.some((s) => s.state === "current" || s.state === "missed")) {
    const next = steps.find((s) => s.state === "pending");
    if (next && !(next.key === "ended" && !incident)) next.state = "current";
  }
  return steps;
}

/** O que bate é acerto na hora; o que não bate só vira erro depois que a falha assentou. */
function verdict(
  check: { key: string; label: string; got: string; expected: string; ok: boolean; okText: string },
  settled: boolean,
): CycleStep {
  const { key, label, got, expected, ok, okText } = check;
  if (ok) return { key, label, state: "done", detail: `${got}: ${okText}`, ok };
  if (!settled) return { key, label, state: "current", detail: `${got} até agora (esperado: ${expected})` };
  return { key, label, state: "done", detail: `${got} (esperado: ${expected})`, ok };
}

function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
