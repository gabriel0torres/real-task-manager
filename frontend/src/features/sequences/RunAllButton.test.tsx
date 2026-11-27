import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Subcategory, Task } from "../../api/types";
import { answerConfirm, mockApi, renderWithProviders } from "../../test/utils";
import { RunAllButton } from "./RunAllButton";

const sub = (extra: Partial<Subcategory> = {}) =>
  ({ id: 1, name: "Palacio", execution_mode: "sequential", running_sequence_id: null, ...extra }) as Subcategory;
const task = (id: number, name: string, extra: Partial<Task> = {}) =>
  ({ id, name, is_active: true, sequence_step: id, ...extra }) as Task;
const TASKS = [
  task(1, "clientes"),
  task(2, "os"),
  task(3, "relatorio_avulso", { sequence_step: null }),
  task(4, "desligada", { is_active: false, sequence_step: null }),
];

afterEach(() => vi.restoreAllMocks());

describe("RunAllButton", () => {
  it("runs every active task in sequence, explaining what stays out", async () => {
    const api = mockApi({
      "POST /subcategories/1/run-all": () => ({
        mode: "sequential",
        sequence_id: 12,
        run_ids: [50],
        task_count: 3,
        paused: ["desligada"],
      }),
    });
    const user = userEvent.setup();
    renderWithProviders(<RunAllButton sub={sub()} tasks={TASKS} />);

    await user.click(screen.getByRole("button", { name: "Executar todas" }));
    const message = await answerConfirm(user, "Executar todas");
    expect(message).toContain('Executar todas as tarefas de "Palacio"?');
    expect(message).toContain("As 3 tarefas ativas vão rodar agora, uma depois da outra");
    expect(message).toContain("fora da sequência");
    expect(message).toContain("Ficam de fora as pausadas:desligada");
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(await screen.findByText("Sequência #12 iniciada com 3 tarefas.")).toBeInTheDocument();
  });

  it("runs all at once in a parallel subcategory", async () => {
    mockApi({
      "POST /subcategories/1/run-all": () => ({
        mode: "parallel",
        sequence_id: null,
        run_ids: [1, 2, 3],
        task_count: 3,
        paused: [],
      }),
    });
    const user = userEvent.setup();
    renderWithProviders(<RunAllButton sub={sub({ execution_mode: "parallel" })} tasks={TASKS.slice(0, 3)} />);
    await user.click(screen.getByRole("button", { name: "Executar todas" }));
    expect(await answerConfirm(user, "Executar todas")).toContain("ao mesmo tempo");
    expect(await screen.findByText("3 execuções solicitadas.")).toBeInTheDocument();
  });

  it("is disabled while a sequence runs or without active tasks", () => {
    const first = renderWithProviders(<RunAllButton sub={sub({ running_sequence_id: 5 })} tasks={TASKS} />);
    expect(screen.getByRole("button", { name: "Executar todas" })).toBeDisabled();
    first.unmount();
    renderWithProviders(<RunAllButton sub={sub()} tasks={[TASKS[3]]} />);
    expect(screen.getByRole("button", { name: "Executar todas" })).toBeDisabled();
  });
});
