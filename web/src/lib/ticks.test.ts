import { describe, expect, it } from "vitest";

import { niceStep, timeTicks, valueTicks } from "./ticks";

describe("valueTicks", () => {
  it("o topo é redondo e cobre o maior valor", () => {
    expect(valueTicks(161)).toEqual([0, 50, 100, 150, 200]);
    expect(valueTicks(22)).toEqual([0, 10, 20, 30]);
    expect(valueTicks(529)).toEqual([0, 200, 400, 600]);
  });
  it("porcentagens pequenas não viram 1,5% nem 0,06000000000000001", () => {
    expect(valueTicks(0.05)).toEqual([0, 0.02, 0.04, 0.06]);
  });
  it("tudo zero ainda desenha um eixo", () => {
    expect(valueTicks(0)).toEqual([0, 1]);
  });
  it("passos de 1, 2, 2,5 e 5", () => {
    expect([0.9, 1.1, 2.2, 4, 7].map(niceStep)).toEqual([1, 2, 2.5, 5, 10]);
  });
});

describe("timeTicks", () => {
  const at = (hh: number, mm: number, ss = 0) => new Date(2026, 9, 20, hh, mm, ss).getTime();
  const clock = (t: number) => new Date(t).toTimeString().slice(0, 8);

  it("o último minuto: de 15 em 15 segundos, em horários redondos", () => {
    expect(timeTicks(at(18, 29, 17), at(18, 30, 14)).map(clock)).toEqual([
      "18:29:30",
      "18:29:45",
      "18:30:00",
    ]);
  });
  it("a última hora: de 15 em 15 minutos", () => {
    expect(timeTicks(at(17, 31), at(18, 30)).map(clock)).toEqual(["17:45:00", "18:00:00", "18:15:00", "18:30:00"]);
  });
  it("um dia: de 6 em 6 horas, no fuso de quem olha", () => {
    expect(timeTicks(at(1, 10), at(23, 50)).map(clock)).toEqual(["06:00:00", "12:00:00", "18:00:00"]);
  });
});
