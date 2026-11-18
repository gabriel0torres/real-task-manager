import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";

import { ToastProvider } from "../components/Toast";
import { mockApi } from "../test/utils";
import { RunDetailPage } from "./RunDetailPage";

class FakeEventSource {
  addEventListener() {}
  close() {}
  onerror = null;
}

const RUN = {
  id: 9,
  task_id: 4,
  task_name: "tarefa 1",
  status: "failed",
  trigger: "scheduled",
  attempt: 1,
  root_run_id: null,
  scheduled_for: null,
  created_at: "2026-11-17T22:36:00Z",
  started_at: "2026-11-17T22:36:00Z",
  finished_at: "2026-11-17T22:36:01Z",
  duration_ms: 295,
  exit_code: 2,
  status_reason: "Código de saída 2.",
  cancel_requested: false,
  triggered_by: null,
};

function renderAt(entries: string[], index: number) {
  vi.stubGlobal("EventSource", FakeEventSource);
  mockApi({ "GET /runs/9": () => RUN });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={entries} initialIndex={index}>
        <ToastProvider>
          <Routes>
            <Route path="/runs" element={<p>lista de execuções</p>} />
            <Route path="/tasks/:taskId" element={<p>página da tarefa</p>} />
            <Route path="/runs/:runId" element={<RunDetailPage />} />
          </Routes>
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RunDetailPage back button", () => {
  it("goes back to the previous page", async () => {
    renderAt(["/runs", "/runs/9"], 1);
    await userEvent.click(await screen.findByRole("button", { name: "Voltar" }));
    expect(await screen.findByText("lista de execuções")).toBeInTheDocument();
  });

  it("opened directly: goes to the task's run history", async () => {
    renderAt(["/runs/9"], 0);
    await userEvent.click(await screen.findByRole("button", { name: "Ver execuções da tarefa" }));
    expect(await screen.findByText("página da tarefa")).toBeInTheDocument();
  });
});
