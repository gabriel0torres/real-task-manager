import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

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

  it("shows a placeholder when empty (no copy button)", () => {
    render(<LogViewer chunks={[]} />);
    expect(screen.getByText("Sem saída até o momento.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copiar log" })).not.toBeInTheDocument();
  });

  it("copies the whole log as plain text", async () => {
    vi.stubGlobal("isSecureContext", true);
    const user = userEvent.setup(); // installs a clipboard stub on navigator
    render(
      <LogViewer
        chunks={[
          { seq: 1, ts: "", stream: "system", content: "[RTS] início\n" },
          { seq: 2, ts: "", stream: "stdout", content: "linha 1\n" },
        ]}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Copiar log" }));
    expect(await screen.findByText("Copiado!")).toBeInTheDocument();
    expect(await navigator.clipboard.readText()).toBe("[RTS] início\nlinha 1\n");
  });
});

describe("RunStatusBadge", () => {
  it("translates statuses", () => {
    render(<RunStatusBadge status="timeout" />);
    expect(screen.getByText("Tempo esgotado")).toBeInTheDocument();
  });
});
