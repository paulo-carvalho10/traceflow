import { describe, expect, it } from "vitest";

import { liveStatus } from "./live";

const NOW = 1_000_000;
const base = { connection: "assinado" as const, subscribedAt: NOW - 60_000, snapshotAt: null, idleAt: null, now: NOW };

describe("liveStatus", () => {
  it("chegou retrato agora: ao vivo", () => {
    expect(liveStatus({ ...base, snapshotAt: NOW - 800 })).toBe("ao vivo");
  });
  it("o aviso de falta de tráfego é mais novo que o último retrato: sem tráfego", () => {
    expect(liveStatus({ ...base, snapshotAt: NOW - 70_000, idleAt: NOW - 500 })).toBe("sem tráfego");
  });
  it("nem retrato nem aviso há mais de 5 s: o processamento parou (não é falta de tráfego)", () => {
    expect(liveStatus({ ...base, snapshotAt: NOW - 9_000, idleAt: NOW - 8_000 })).toBe("sem dados novos");
  });
  it("assinou há pouco e nada chegou ainda: conectando; passou de 5 s sem nada: parou", () => {
    expect(liveStatus({ ...base, subscribedAt: NOW - 400 })).toBe("conectando");
    expect(liveStatus({ ...base, subscribedAt: NOW - 6_000 })).toBe("sem dados novos");
  });
  it("antes de assinar, o estado é o da conexão", () => {
    expect(liveStatus({ ...base, connection: "reconectando", snapshotAt: NOW - 100 })).toBe("reconectando");
  });
});
