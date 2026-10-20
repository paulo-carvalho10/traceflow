import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { Span } from "@/lib/api";

import { Waterfall, visibleSpans } from "./waterfall";

function span(id: string, depth: number, children: number, extra: Partial<Span> = {}): Span {
  return {
    span_id: id,
    parent_span_id: null,
    depth,
    offset_ms: depth * 10,
    duration_ms: 100 - depth * 10,
    self_time_ms: 5,
    orphan: false,
    children,
    service: `svc-${id}`,
    name: `op-${id}`,
    kind: "server",
    status: "unset",
    status_message: null,
    http_method: null,
    http_route: null,
    http_status_code: null,
    peer_address: null,
    attributes: {},
    resource: {},
    events: [],
    ...extra,
  };
}

// gateway > orders > (inventory, payments > bank); notifications é irmão do orders
const TREE = [
  span("gw", 0, 2),
  span("ord", 1, 2),
  span("inv", 2, 0),
  span("pay", 2, 1),
  span("bank", 3, 0, { kind: "client" }),
  span("notif", 1, 0),
];

describe("visibleSpans", () => {
  it("sem nada recolhido, mostra tudo", () => {
    expect(visibleSpans(TREE, new Set()).map((s) => s.span_id)).toEqual(["gw", "ord", "inv", "pay", "bank", "notif"]);
  });
  it("recolher um span esconde só os descendentes dele", () => {
    expect(visibleSpans(TREE, new Set(["ord"])).map((s) => s.span_id)).toEqual(["gw", "ord", "notif"]);
    expect(visibleSpans(TREE, new Set(["pay"])).map((s) => s.span_id)).toEqual(["gw", "ord", "inv", "pay", "notif"]);
  });
});

describe("Waterfall", () => {
  it("desenha uma linha por span e recolhe pelo botão", () => {
    render(
      <TooltipProvider>
        <Waterfall spans={TREE} totalMs={100} selected={null} onSelect={() => {}} />
      </TooltipProvider>,
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(6);
    fireEvent.click(screen.getAllByRole("button", { name: "Recolher" })[1]); // o do orders
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Expandir" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(6);
  });
});
