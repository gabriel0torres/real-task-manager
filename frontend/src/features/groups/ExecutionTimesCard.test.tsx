import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GroupExecutionTimes, Task } from "../../api/types";
import { answerConfirm, mockApi, renderWithProviders } from "../../test/utils";
import { InterruptButton } from "../runs/InterruptButton";
import { ExecutionTimesCard } from "./ExecutionTimesCard";

const TIMES: GroupExecutionTimes = {
  group_id: 3,
  total_last_ms: 70 * 60_000,
  activity: { running_sequences: 1, running_runs: 1, waiting_runs: 0 },
  subcategories: [
    {
      subcategory_id: 1,
      name: "Palacio",
      execution_mode: "sequential",
      running: {
        kind: "sequence",
        sequence_id: 9,
        started_at: "2026-11-25T13:00:00Z",
        finished_at: null,
        duration_ms: null,
        status: "running",
        succeeded: 2,
        total: 20,
      },
      last: {
        kind: "sequence",
        sequence_id: 8,
        started_at: "2026-11-25T11:00:00Z",
        finished_at: "2026-11-25T11:47:00Z",
        duration_ms: 47 * 60_000,
        status: "failed",
        succeeded: 19,
        total: 20,
      },
      average_ms: 45 * 60_000,
      average_of: 10,
    },
    {
      subcategory_id: 2,
      name: "Nacional",
      execution_mode: "sequential",
      running: null,
      last: {
        kind: "sequence",
        sequence_id: 7,
        started_at: "2026-11-25T12:30:00Z",
        finished_at: "2026-11-25T12:53:00Z",
        duration_ms: 23 * 60_000,
        status: "success",
        succeeded: 15,
        total: 15,
      },
      average_ms: 22 * 60_000,
      average_of: 4,
    },
  ],
};

afterEach(() => vi.restoreAllMocks());

describe("ExecutionTimesCard", () => {
  it("shows how long each subcategory took and interrupts everything", async () => {
    const api = mockApi({
      "GET /groups/3/execution-times": () => TIMES,
      "POST /groups/3/interrupt": () => ({ sequences_cancelled: 1, runs_cancelled: 1 }),
    });
    const user = userEvent.setup();
    renderWithProviders(<ExecutionTimesCard groupId={3} groupName="Automações" />);

    const palacio = await screen.findByTestId("execution-times-1");
    expect(palacio).toHaveTextContent("Palacio");
    expect(palacio).toHaveTextContent("47min 00s");
    expect(palacio).toHaveTextContent("19 de 20 com sucesso");
    expect(palacio).toHaveTextContent("45min 00s (últimas 10)");
    expect(palacio).toHaveTextContent("rodando desde");
    expect(screen.getByTestId("execution-times-2")).toHaveTextContent("23min 00s");
    expect(screen.getByTestId("execution-times-total")).toHaveTextContent("1h 10min");
    expect(screen.getByTestId("group-activity")).toHaveTextContent(
      "1 sequência em andamento, 1 execução rodando",
    );

    await user.click(screen.getByRole("button", { name: "Interromper tudo" }));
    const message = await answerConfirm(user, "Interromper tudo");
    expect(message).toContain('Interromper tudo no grupo "Automações"?');
    expect(message).toContain("Os agendamentos continuam valendo");
    await waitFor(() =>
      expect(api.mock.calls.some(([u, i]) => String(u).endsWith("/groups/3/interrupt") && i?.method === "POST")).toBe(true),
    );
    expect(await screen.findByText(/Interrompido: 1 sequência e 1 execução/)).toBeInTheDocument();
  });

  it("disables 'Interromper tudo' when nothing is running", async () => {
    mockApi({
      "GET /groups/3/execution-times": () => ({
        ...TIMES,
        activity: { running_sequences: 0, running_runs: 0, waiting_runs: 0 },
      }),
    });
    renderWithProviders(<ExecutionTimesCard groupId={3} groupName="Automações" />);
    expect(await screen.findByRole("button", { name: "Interromper tudo" })).toBeDisabled();
    expect(screen.queryByTestId("group-activity")).not.toBeInTheDocument();
  });
});

describe("InterruptButton", () => {
  const task = (extra: Partial<Task>) => ({ id: 1, name: "clientes", sequence_step: null, ...extra }) as Task;

  it("interrupts the running run, warning about the sequence", async () => {
    const api = mockApi({ "POST /runs/42/cancel": () => ({ id: 42 }) });
    const user = userEvent.setup();
    renderWithProviders(
      <InterruptButton task={task({ active_run_id: 42, active_run_status: "running", sequence_step: 3 })} />,
    );
    await user.click(screen.getByRole("button", { name: "Interromper" }));
    expect(await answerConfirm(user, "Interromper")).toContain("faz parte de uma sequência");
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(await screen.findByText("Interrupção solicitada.")).toBeInTheDocument();
  });

  it("cancels a waiting run, and renders nothing without an active run", () => {
    const first = renderWithProviders(
      <InterruptButton task={task({ active_run_id: 7, active_run_status: "pending" })} />,
    );
    expect(screen.getByRole("button", { name: "Cancelar execução" })).toBeInTheDocument();
    first.unmount();
    renderWithProviders(<InterruptButton task={task({ active_run_id: null })} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
