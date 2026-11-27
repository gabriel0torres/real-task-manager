import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SequenceRun, Subcategory, Task } from "../../api/types";
import { answerConfirm, bodyOf, mockApi, renderWithProviders } from "../../test/utils";
import { ExecutionCard } from "./ExecutionCard";

const SUB = {
  id: 1,
  group_id: 7,
  name: "Palácio",
  execution_mode: "sequential",
  stop_on_failure: false,
  running_sequence_id: null,
  inherited_schedule: { source: "group", cron_expressions: ["0 */2 * * *"], timezone: null, description: "A cada 2 horas" },
} as unknown as Subcategory;

const task = (id: number, name: string, step: number | null, extra: Partial<Task> = {}) =>
  ({ id, name, schedule_mode: "inherit", is_active: true, sequence_step: step, sequence_total: 3, ...extra }) as Task;

const TASKS = [
  task(11, "clientes", 1),
  task(12, "ordem_servico", 2),
  task(13, "estoque", 3),
  task(14, "conciliacao", null, { schedule_mode: "own" }),
];

const step = (index: number, name: string, status: string, run_id: number | null) => ({
  index,
  task_id: 11 + index,
  task_name: name,
  run_id,
  status,
  attempt: run_id ? 1 : null,
  started_at: null,
  finished_at: null,
  duration_ms: status === "success" ? 4200 : null,
});

const RUNNING: SequenceRun = {
  id: 5,
  subcategory_id: 1,
  status: "running",
  trigger: "scheduled",
  triggered_by: null,
  stop_on_failure: false,
  scheduled_for: null,
  created_at: "2026-11-18T20:00:00Z",
  finished_at: null,
  status_reason: null,
  current_index: 1,
  total_steps: 3,
  completed_steps: 1,
  steps: [step(0, "clientes", "success", 101), step(1, "ordem_servico", "running", 102), step(2, "estoque", "not_run", null)] as SequenceRun["steps"],
};

const DONE: SequenceRun = {
  ...RUNNING,
  id: 4,
  status: "failed",
  finished_at: "2026-11-18T18:03:00Z",
  created_at: "2026-11-18T18:00:00Z",
  status_reason: "2 de 3 tarefas com sucesso.",
  steps: [step(0, "clientes", "success", 91), step(1, "ordem_servico", "failed", 92), step(2, "estoque", "success", 93)] as SequenceRun["steps"],
};

afterEach(() => vi.restoreAllMocks());

describe("ExecutionCard", () => {
  it("shows the order, reorders and starts the sequence", async () => {
    const api = mockApi({
      "GET /subcategories/1/sequences": () => [DONE],
      "PUT /subcategories/1/sequence-order": (init) => JSON.parse(String(init?.body)),
      "POST /subcategories/1/sequences": () => ({ ...RUNNING, id: 6 }),
    });
    const user = userEvent.setup();
    renderWithProviders(<ExecutionCard sub={SUB} tasks={TASKS} />);

    expect(screen.getByRole("radio", { name: "Sequencial" })).toHaveAttribute("aria-checked", "true");
    const order = screen.getByTestId("sequence-order");
    expect(within(order).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "clientes",
      "ordem_servico",
      "estoque",
    ]);
    expect(screen.getByTestId("sequence-outside")).toHaveTextContent("conciliacao (agendamento próprio)");
    expect(screen.getByRole("button", { name: "Mover clientes para cima" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Mover estoque para cima" }));
    await waitFor(() =>
      expect(bodyOf(api, "PUT /subcategories/1/sequence-order")).toEqual({ task_ids: [11, 13, 12] }),
    );

    const history = await screen.findByTestId("sequence-history");
    expect(history).toHaveTextContent("2 de 3 tarefas com sucesso.");
    expect(history).toHaveTextContent("3min 00s");

    await user.click(screen.getByRole("button", { name: "Executar sequência agora" }));
    expect(await screen.findByText(/Sequência #6 iniciada \(3 tarefas\)/)).toBeInTheDocument();
  });

  it("follows a running sequence and cancels it", async () => {
    const api = mockApi({
      "GET /subcategories/1/sequences": () => [RUNNING],
      "POST /sequences/5/cancel": () => ({ ...RUNNING, status: "cancelled" }),
    });
    const user = userEvent.setup();
    renderWithProviders(<ExecutionCard sub={SUB} tasks={TASKS} />);

    const panel = await screen.findByTestId("sequence-running");
    expect(panel).toHaveTextContent("Sequência #5 em andamento: etapa 2 de 3 — ordem_servico");
    expect(within(panel).getByTestId("sequence-step-2")).toHaveTextContent("não executada");
    expect(screen.getByRole("button", { name: "Executar sequência agora" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Cancelar sequência" }));
    expect(await answerConfirm(user, "Cancelar sequência")).toContain(
      "A tarefa em andamento (ordem_servico) será encerrada",
    );
    await waitFor(() => expect(api.mock.calls.some(([u]) => String(u).includes("/sequences/5/cancel"))).toBe(true));
  });

  it("switches the mode and warns when there is no schedule", async () => {
    const api = mockApi({
      "GET /subcategories/1/sequences": () => [],
      "PATCH /subcategories/1": (init) => ({ ...SUB, ...JSON.parse(String(init?.body)) }),
    });
    const user = userEvent.setup();
    renderWithProviders(
      <ExecutionCard
        sub={{ ...SUB, execution_mode: "parallel", inherited_schedule: { ...SUB.inherited_schedule, source: "none" } }}
        tasks={TASKS}
      />,
    );
    expect(screen.queryByTestId("sequence-order")).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Sequencial" }));
    await waitFor(() => expect(bodyOf(api, "PATCH /subcategories/1")).toEqual({ execution_mode: "sequential" }));
  });
});
