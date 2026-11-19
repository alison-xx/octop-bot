import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ToolDetailsInline } from "../../../pages/Chat/components/MessageBubble";
import { ensureBuiltinToolRenderers } from "../ensureBuiltins";

function show(data: unknown) {
  ensureBuiltinToolRenderers();
  return render(
    <ToolDetailsInline
      toolData={{
        name: "show_view",
        callId: "view1",
        output: JSON.stringify({
          octop_ui: { renderer: "octop-bot-view", version: 1 },
          text: "Result",
          data,
        }),
      }}
      isStreaming={false}
    />,
  );
}
describe("show_view in a native conversation", () => {
  it("recomputes a formula and dependent named expression locally", () => {
    show({
      kind: "calculator",
      title: "Quote",
      inputs: [{ type: "number", id: "qty", label: "Units", value: 3 }],
      let: { subtotal: "qty * 10" },
      metrics: [{ label: "Total", value: { "=": "subtotal + 4" } }],
    });
    expect(screen.getByText("34")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("spinbutton", { name: "Units" }), {
      target: { value: "5" },
    });
    expect(screen.getByText("54")).toBeInTheDocument();
  });
  it("keeps HTML inside a sandbox with no external URLs or form actions", () => {
    show({
      kind: "html",
      title: "Preview",
      html: '<h1>Report</h1><a href="https://example.com">Details</a><form action="https://example.com"></form>',
    });
    const frame = screen.getByTitle<HTMLIFrameElement>("Preview");
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame.srcdoc).toContain("Report");
    expect(frame.srcdoc).toContain("default-src 'none'");
    expect(frame.srcdoc).not.toContain("https://example.com");
    expect(frame.srcdoc).not.toContain("<form");
  });
  it("renders tool output as a real table with headers and values", () => {
    show({
      kind: "table",
      title: "Deliveries",
      columns: ["Editor", "Done"],
      rows: [["Chief", true]],
    });
    const table = screen.getByRole("table", { name: "Deliveries" });
    expect(
      within(table).getByRole("columnheader", { name: "Done" }),
    ).toBeInTheDocument();
    expect(
      within(table).getByRole("cell", { name: "true" }),
    ).toBeInTheDocument();
  });
  it("preserves numeric zero metrics and completed user answers when reloading history", () => {
    const metrics = show({
      kind: "metrics",
      title: "Wallet",
      metrics: [{ label: "Cost", value: 0, unit: "USD" }],
    });
    expect(screen.getByText("0")).toBeInTheDocument();
    metrics.unmount();
    show({
      kind: "form",
      title: "Brief",
      questions: [{ question: "Audience?" }],
      answers: ["Editors"],
    });
    expect(screen.getByText("Editors")).toBeInTheDocument();
  });
  it("includes an accessible data table for a chart", () => {
    show({
      kind: "chart",
      title: "Weekly traffic",
      chart_type: "line",
      labels: ["Mon", "Tue"],
      series: [{ name: "Visits", values: [2, 7] }],
    });
    expect(screen.getByText("Visits")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
  });
});
