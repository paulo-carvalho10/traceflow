import { describe, expect, it } from "vitest";

import { CLIENTS, buildGraph, graphShape, layoutGraph } from "./service-map";

const svc = (name: string, extra: Partial<{ rps: number; error_rate: number; entry_rps: number }> = {}) => ({
  name,
  rps: 10,
  error_rate: 0,
  p50_ms: 10,
  p95_ms: 20,
  requests: 100,
  entry_rps: 0,
  ...extra,
});
const call = (source: string, target: string, extra: Partial<{ virtual: boolean; error_rate: number; rps: number }> = {}) => ({
  source,
  target,
  address: `${target}:8000`,
  virtual: false,
  rps: 5,
  error_rate: 0,
  p50_ms: 5,
  p95_ms: 9,
  requests: 50,
  ...extra,
});

// a loja: gateway (entrada) → orders → payments → bank:8000 (externo)
const shop = buildGraph({
  services: [svc("gateway", { entry_rps: 20 }), svc("orders"), svc("payments")],
  edges: [
    call("gateway", "orders"),
    call("orders", "payments", { error_rate: 0.12 }),
    { ...call("payments", "bank:8000", { virtual: true }), address: "bank:8000" },
  ],
});

describe("buildGraph", () => {
  it("cria os clientes, ligados a quem recebeu requisições de fora", () => {
    const entry = shop.edges.find((e) => e.source === CLIENTS);
    expect(entry).toMatchObject({ target: "gateway", stats: { rps: 20 } });
  });
  it("endereço sem serviço vira nó virtual, com o nome sem a porta", () => {
    const bank = shop.nodes.find((n) => n.id === "bank:8000");
    expect(bank).toMatchObject({ kind: "virtual", label: "bank", detail: "bank:8000", stats: { rps: 5 } });
  });
  it("marca a ligação com falha a partir de 5%", () => {
    expect(shop.edges.find((e) => e.id === "orders->payments")?.failing).toBe(true);
    expect(shop.edges.find((e) => e.id === "gateway->orders")?.failing).toBe(false);
  });
  it("o serviço que caiu continua no mapa, sem números e marcado", () => {
    const g = buildGraph({
      services: [svc("orders")],
      edges: [call("orders", "notifications", { error_rate: 1 })],
      unresponsive: ["notifications"],
    });
    expect(g.nodes.find((n) => n.id === "notifications")).toMatchObject({ kind: "service", stats: null, unresponsive: true });
  });
  it("ignora o serviço chamando a si mesmo", () => {
    expect(buildGraph({ services: [svc("a")], edges: [call("a", "a")] }).edges).toEqual([]);
  });
});

describe("layoutGraph", () => {
  it("põe as camadas da esquerda para a direita, no sentido das chamadas", () => {
    const at = layoutGraph(shop);
    const x = (id: string) => at.get(id)!.x;
    expect(x(CLIENTS)).toBeLessThan(x("gateway"));
    expect(x("gateway")).toBeLessThan(x("orders"));
    expect(x("orders")).toBeLessThan(x("payments"));
    expect(x("payments")).toBeLessThan(x("bank:8000"));
  });
  it("em tela estreita, as camadas vão de cima para baixo", () => {
    const at = layoutGraph(shop, "TB");
    const y = (id: string) => at.get(id)!.y;
    expect(y(CLIENTS)).toBeLessThan(y("gateway"));
    expect(y("orders")).toBeLessThan(y("payments"));
    expect(y("payments")).toBeLessThan(y("bank:8000"));
  });
  it("a forma não muda com os números, só com quem existe e quem chama quem", () => {
    const busier = buildGraph({
      services: [svc("gateway", { entry_rps: 99, rps: 99 }), svc("orders"), svc("payments")],
      edges: [
        call("gateway", "orders", { rps: 50 }),
        call("orders", "payments"),
        { ...call("payments", "bank:8000", { virtual: true }), address: "bank:8000" },
      ],
    });
    expect(graphShape(busier)).toBe(graphShape(shop));
  });
});
