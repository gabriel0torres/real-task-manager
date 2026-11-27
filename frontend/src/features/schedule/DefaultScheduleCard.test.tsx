import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ScheduleOwner, Task } from "../../api/types";
import { answerConfirm, mockApi, renderWithProviders } from "../../test/utils";
import { DefaultScheduleCard } from "./DefaultScheduleCard";

const NONE: ScheduleOwner = { cron_expressions: [], timezone: null, schedule_description: "Sem agendamento" };
const EVERY_2H: ScheduleOwner = {
  cron_expressions: ["0 */2 * * *"],
  timezone: null,
  schedule_description: "A cada 2 horas",
};

const task = (id: number, name: string, mode: Task["schedule_mode"]) =>
  ({ id, name, schedule_mode: mode, subcategory_id: 1 }) as Task;

function previewApi() {
  return mockApi({
    "POST /schedule/preview": () => ({
      valid: true,
      error: null,
      description: "A cada 3 horas",
      cron_expressions: ["0 */3 * * *"],
      timezone: "America/Sao_Paulo",
      next_runs: [],
    }),
  });
}

function renderCard(onSave = vi.fn()) {
  renderWithProviders(
    <DefaultScheduleCard
      kind="subcategory"
      owner={NONE}
      group={{ id: 7, name: "Clientes", owner: EVERY_2H }}
      affected={[task(1, "relatorio", "inherit"), task(2, "backup", "inherit")]}
      ownSchedule={[task(3, "conciliacao", "own")]}
      defaultTimezone="America/Sao_Paulo"
      busy={false}
      onSave={onSave}
    />,
  );
  return onSave;
}

afterEach(() => vi.restoreAllMocks());

describe("DefaultScheduleCard", () => {
  it("explains the group fallback and who follows the schedule", () => {
    previewApi();
    renderCard();
    expect(screen.getByTestId("default-schedule")).toHaveTextContent(
      "as tarefas que herdam usam o do grupo Clientes (A cada 2 horas)",
    );
    const usage = screen.getByTestId("schedule-usage");
    expect(usage).toHaveTextContent("Usado por 2 tarefas que herda(m): relatorio, backup.");
    expect(usage).toHaveTextContent("1 tarefa com agendamento próprio (não afetada): conciliacao.");
  });

  it("confirms who is affected before saving", async () => {
    previewApi();
    const user = userEvent.setup();
    const onSave = renderCard();

    await user.click(screen.getByRole("button", { name: "Alterar" }));
    // Empty schedule on a subcategory under a scheduled group = "use the group's".
    expect(screen.getByRole("radio", { name: "Usar o do grupo" })).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("radio", { name: "A cada X horas" }));
    const every = screen.getByLabelText("Intervalo em horas");
    await user.clear(every);
    await user.type(every, "3");

    await user.click(screen.getByRole("button", { name: "Salvar agendamento" }));
    const message = await answerConfirm(user, "Voltar");
    expect(message).toContain("Vale para 2 tarefas que herdam o agendamento:relatoriobackup");
    expect(message).toContain("Não mudam (1 tem agendamento próprio):conciliacao");
    expect(onSave).not.toHaveBeenCalled(); // cancelled
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Salvar agendamento" }));
    await answerConfirm(user, "Salvar agendamento");
    expect(onSave).toHaveBeenCalledWith(
      { cron_expressions: ["0 */3 * * *"], timezone: null },
      expect.any(Function),
    );
  });

  it("group card offers 'no default schedule' and saves without asking when nobody inherits", async () => {
    previewApi();
    const user = userEvent.setup();
    const onSave = vi.fn();
    renderWithProviders(
      <DefaultScheduleCard
        kind="group"
        owner={EVERY_2H}
        affected={[]}
        ownSchedule={[]}
        followSubcategory={[task(4, "fechamento", "inherit")]}
        defaultTimezone="America/Sao_Paulo"
        busy={false}
        onSave={onSave}
      />,
    );
    expect(screen.getByTestId("default-schedule")).toHaveTextContent("A cada 2 horas");
    expect(screen.getByTestId("schedule-usage")).toHaveTextContent(
      "1 tarefa segue o agendamento da própria subcategoria: fechamento.",
    );

    await user.click(screen.getByRole("button", { name: "Alterar" }));
    const modes = screen.getByRole("radiogroup", { name: "Tipo de agendamento" });
    await user.click(within(modes).getByRole("radio", { name: "Sem agendamento padrão" }));
    await user.click(screen.getByRole("button", { name: "Salvar agendamento" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(); // nobody inherits: no question
    expect(onSave).toHaveBeenCalledWith({ cron_expressions: [], timezone: null }, expect.any(Function));
  });
});
