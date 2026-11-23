import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import type { InheritedSchedule, Task } from "../api/types";
import { ToastProvider } from "../components/Toast";
import { bodyOf, mockApi } from "../test/utils";
import { TaskFormPage } from "./TaskFormPage";

const FROM_GROUP: InheritedSchedule = {
  source: "group",
  cron_expressions: ["0 */2 * * *"],
  timezone: null,
  description: "A cada 2 horas",
};
const NOTHING: InheritedSchedule = { source: "none", cron_expressions: [], timezone: null, description: "" };

function task(overrides: Partial<Task>): Task {
  return {
    id: 5,
    subcategory_id: 1,
    group_id: 7,
    name: "conciliacao",
    description: "",
    command: "echo ok",
    shell: null,
    working_dir: null,
    schedule_mode: "own",
    cron_expressions: ["0 14 * * *"],
    timezone: null,
    schedule_source: "task",
    effective_cron_expressions: ["0 14 * * *"],
    schedule_description: "Todos os dias às 14:00",
    sequence_position: null,
    sequence_step: null,
    sequence_total: null,
    effective_timezone: "America/Sao_Paulo",
    timeout_seconds: null,
    max_retries: 0,
    retry_interval_seconds: 60,
    overlap_policy: "skip",
    misfire_policy: "ignore",
    is_active: true,
    is_effectively_active: true,
    next_run_at: null,
    created_at: "2026-11-18T00:00:00Z",
    updated_at: "2026-11-18T00:00:00Z",
    ...overrides,
  };
}

function setup(
  current: Task,
  inherited: InheritedSchedule = FROM_GROUP,
  { route = "/tasks/5/edit", extra = {} }: { route?: string; extra?: Parameters<typeof mockApi>[0] } = {},
) {
  const api = mockApi({
    ...extra,
    "GET /tasks/5": () => current,
    "PATCH /tasks/5": (init) => ({ ...current, ...JSON.parse(String(init?.body)) }),
    "GET /subcategories/1": () => ({
      id: 1,
      group_id: 7,
      name: "Cliente X",
      description: "",
      is_active: true,
      is_effectively_active: true,
      cron_expressions: [],
      timezone: null,
      schedule_description: "Sem agendamento",
      inherited_schedule: inherited,
      created_at: "",
      updated_at: "",
    }),
    "GET /groups/7": () => ({ id: 7, name: "Clientes", description: "", is_active: true }),
    "GET /settings": () => ({ default_timezone: "America/Sao_Paulo", retention_days: null, retention_keep_last: null }),
    "GET /system/info": () => ({
      version: "0.3.0",
      platform: "windows",
      default_shell: "cmd",
      metadata_variables: {},
    }),
    "GET /tasks/5/effective-variables": () => [],
    "POST /schedule/preview": (init) => {
      const body = JSON.parse(String(init?.body));
      return {
        valid: true,
        error: null,
        description: body.cron_expressions[0] === "0 */2 * * *" ? "A cada 2 horas" : "Todos os dias às 08:00",
        cron_expressions: body.cron_expressions,
        timezone: body.timezone,
        next_runs: [],
      };
    },
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <ToastProvider>
          <Routes>
            <Route path="/tasks/new" element={<TaskFormPage />} />
            <Route path="/tasks/:taskId/edit" element={<TaskFormPage />} />
            <Route path="/tasks/:taskId" element={<p>página da tarefa</p>} />
          </Routes>
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return api;
}

beforeAll(() => {
  // CodeMirror measures text ranges, which jsdom does not implement.
  const empty = () => Object.assign([], { item: () => null }) as unknown as DOMRectList;
  Range.prototype.getClientRects = empty;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
});

const originGroup = () => screen.getByRole("radiogroup", { name: "Origem do agendamento" });

describe("TaskFormPage schedule origin", () => {
  it("switches an own schedule to inherit, keeping the own expressions", async () => {
    const api = setup(task({}));
    const user = userEvent.setup();

    const own = await within(await screen.findByRole("radiogroup", { name: "Origem do agendamento" }))
      .findByRole("radio", { name: "Próprio" });
    expect(own).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText(/esta tarefa usará o horário abaixo no lugar/)).toHaveTextContent(
      "O grupo roda a cada 2 horas",
    );

    await user.click(within(originGroup()).getByRole("radio", { name: "Herdar" }));
    expect(screen.getByTestId("inherited-schedule")).toHaveTextContent("Herdado do grupo Clientes");
    expect(await screen.findByTestId("schedule-description")).toHaveTextContent("A cada 2 horas");

    await user.click(screen.getByRole("button", { name: "Salvar alterações" }));
    await screen.findByText("página da tarefa");
    expect(bodyOf(api, "PATCH /tasks/5")).toMatchObject({
      schedule_mode: "inherit",
      cron_expressions: ["0 14 * * *"],
    });
  });

  it("a manual task switched to own starts at daily 08:00, without a manual option", async () => {
    const api = setup(
      task({ schedule_mode: "manual", cron_expressions: [], schedule_source: "manual" }),
    );
    const user = userEvent.setup();
    await user.click(
      await within(await screen.findByRole("radiogroup", { name: "Origem do agendamento" })).findByRole(
        "radio",
        { name: "Próprio" },
      ),
    );
    const kinds = screen.getByRole("radiogroup", { name: "Tipo de agendamento" });
    expect(within(kinds).queryByRole("radio", { name: "Somente manual" })).not.toBeInTheDocument();
    expect(within(kinds).getByRole("radio", { name: "Diariamente" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByLabelText("Horário 1")).toHaveValue("08:00");

    await user.click(screen.getByRole("button", { name: "Salvar alterações" }));
    await waitFor(() =>
      expect(bodyOf(api, "PATCH /tasks/5")).toMatchObject({
        schedule_mode: "own",
        cron_expressions: ["0 8 * * *"],
      }),
    );
  });

  it("warns when inheriting but nothing above has a schedule", async () => {
    setup(task({ schedule_mode: "inherit", schedule_source: "none" }), NOTHING);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Nem a subcategoria Cliente X nem o grupo Clientes têm um agendamento padrão",
      ),
    );
  });
});

describe("TaskFormPage copy from another task", () => {
  const TREE = [
    {
      id: 7,
      name: "Clientes",
      is_active: true,
      has_failure: false,
      subcategories: [
        { id: 1, name: "Cliente X", is_active: true, is_effectively_active: true, has_failure: false, tasks: [{ id: 5, name: "conciliacao" }] },
      ],
    },
  ];
  const VARIABLES = [
    { id: 1, scope: "task", owner_id: 5, key: "EMPRESA", value: "nacional", is_secret: false, has_value: true },
    { id: 2, scope: "task", owner_id: 5, key: "SENHA", value: null, is_secret: true, has_value: true },
  ];

  it("prefills the form from ?copyFrom and copies the variables on create", async () => {
    const api = setup(task({ working_dir: "C:/robos", timeout_seconds: 600 }), FROM_GROUP, {
      route: "/tasks/new?subcategoryId=1&copyFrom=5",
      extra: {
        "GET /tree": () => TREE,
        "GET /variables": () => VARIABLES,
        "GET /subcategories/1/effective-variables": () => [],
        "POST /tasks": (init) => ({ ...task({}), id: 9, ...JSON.parse(String(init?.body)) }),
      },
    });
    const user = userEvent.setup();

    expect(await screen.findByLabelText("Nome")).toHaveValue("conciliacao (cópia)");
    expect(screen.getByLabelText("Diretório de trabalho")).toHaveValue("C:/robos");
    // The picker shows the source once the task list (tree) has loaded.
    await waitFor(() => expect(screen.getByLabelText("Copiar de outra tarefa (opcional)")).toHaveValue("5"));
    const copyVars = await screen.findByRole("checkbox", { name: "Copiar também as variáveis da tarefa (2)" });
    expect(copyVars).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Criar tarefa" }));
    await screen.findByText("página da tarefa");
    expect(bodyOf(api, "POST /tasks")).toMatchObject({
      name: "conciliacao (cópia)",
      subcategory_id: 1,
      command: "echo ok",
      working_dir: "C:/robos",
      timeout_seconds: 600,
      schedule_mode: "own",
      cron_expressions: ["0 14 * * *"],
      copy_variables_from: 5,
    });
  });

  it("starts blank and copies only when a task is picked; variables can be left out", async () => {
    const api = setup(task({}), FROM_GROUP, {
      route: "/tasks/new?subcategoryId=1",
      extra: {
        "GET /tree": () => TREE,
        "GET /variables": () => VARIABLES,
        "GET /subcategories/1/effective-variables": () => [],
        "POST /tasks": (init) => ({ ...task({}), id: 9, ...JSON.parse(String(init?.body)) }),
      },
    });
    const user = userEvent.setup();
    expect(await screen.findByLabelText("Nome")).toHaveValue("");

    await user.selectOptions(await screen.findByLabelText("Copiar de outra tarefa (opcional)"), "5");
    expect(await screen.findByLabelText("Nome")).toHaveValue("conciliacao (cópia)");
    await user.click(await screen.findByRole("checkbox", { name: /Copiar também as variáveis/ }));
    await user.clear(screen.getByLabelText("Nome"));
    await user.type(screen.getByLabelText("Nome"), "nova");
    await user.click(screen.getByRole("button", { name: "Criar tarefa" }));
    await screen.findByText("página da tarefa");
    const body = bodyOf(api, "POST /tasks") as Record<string, unknown>;
    expect(body.name).toBe("nova");
    expect(body).not.toHaveProperty("copy_variables_from");
  });
});
