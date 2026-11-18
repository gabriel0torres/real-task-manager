import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunStatusBadge } from "../../components/StatusBadge";
import { LogViewer } from "./LogViewer";

describe("LogViewer", () => {
  it("renders chunks in order, colouring each stream", () => {
    render(
      <LogViewer
        chunks={[
          { seq: 1, ts: "", stream: "system", content: "[RTS] início\n" },
          { seq: 2, ts: "", stream: "stdout", content: "olá\n" },
          { seq: 3, ts: "", stream: "stderr", content: "erro!\n" },
        ]}
      />,
    );
    const viewer = screen.getByTestId("log-viewer");
    expect(viewer).toHaveTextContent("[RTS] início olá erro!");
    expect(screen.getByText("erro!")).toHaveAttribute("data-stream", "stderr");
    expect(screen.getByText("erro!")).toHaveClass("text-red-300");
  });

  it("shows a placeholder when empty", () => {
    render(<LogViewer chunks={[]} />);
    expect(screen.getByText("Sem saída até o momento.")).toBeInTheDocument();
  });
});

describe("RunStatusBadge", () => {
  it("translates statuses", () => {
    render(<RunStatusBadge status="timeout" />);
    expect(screen.getByText("Tempo esgotado")).toBeInTheDocument();
  });
});
