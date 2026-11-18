import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { App } from "../../App";
import { bodyOf, mockApi, renderWithProviders } from "../../test/utils";
import { ApiTokens } from "./ApiTokens";

const USER = {
  id: 1,
  username: "admin",
  role: "admin",
  must_change_password: false,
  permissions: ["view", "run_tasks", "manage_config", "manage_settings"],
  last_login_at: null,
};

const DASHBOARD = {
  running: [],
  upcoming: [],
  recent_failures: [],
  stats: {
    last_24h: { success: 0, failed: 0, timeout: 0, total: 0, success_rate: null },
    last_7d: { success: 0, failed: 0, timeout: 0, total: 0, success_rate: null },
  },
  counts: { groups: 0, subcategories: 0, tasks: 0, tasks_active: 0, tasks_paused: 0 },
  worker: { online: true, worker_id: "w", last_seen: null, version: "0.1.0" },
};

const unauthorized = () => new Response(JSON.stringify({ detail: "Faça login para continuar." }), { status: 401 });

describe("authentication gate", () => {
  it("shows the login form and enters the app after logging in", async () => {
    let logged = false;
    const api = mockApi({
      "GET /auth/me": () => (logged ? USER : unauthorized()),
      "POST /auth/login": (init) => {
        const body = JSON.parse(String(init?.body));
        if (body.password !== "certa-123") {
          return new Response(JSON.stringify({ detail: "Usuário ou senha inválidos." }), { status: 401 });
        }
        logged = true;
        return USER;
      },
      "GET /dashboard": () => DASHBOARD,
      "GET /tree": () => [],
      "GET /system/worker": () => DASHBOARD.worker,
    });
    const user = userEvent.setup();
    renderWithProviders(<App />);

    await user.type(await screen.findByLabelText("Usuário"), "admin");
    await user.type(screen.getByLabelText("Senha"), "errada");
    await user.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByText("Usuário ou senha inválidos.")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Senha"));
    await user.type(screen.getByLabelText("Senha"), "certa-123");
    await user.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("heading", { name: "Painel" })).toBeInTheDocument();
    expect(bodyOf(api, "POST /auth/login")).toEqual({ username: "admin", password: "errada" });
  });

  it("forces a password change when the admin password was generated", async () => {
    mockApi({
      "GET /auth/me": () => ({ ...USER, must_change_password: true }),
      "POST /auth/change-password": () => USER,
      "GET /dashboard": () => DASHBOARD,
      "GET /tree": () => [],
      "GET /system/worker": () => DASHBOARD.worker,
    });
    const user = userEvent.setup();
    renderWithProviders(<App />);
    expect(await screen.findByRole("heading", { name: "Defina sua senha" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Senha atual"), "gerada-abc");
    await user.type(screen.getByLabelText("Nova senha"), "nova-senha-1");
    await user.type(screen.getByLabelText("Confirmar nova senha"), "nova-senha-1");
    await user.click(screen.getByRole("button", { name: "Trocar senha" }));
    expect(await screen.findByRole("heading", { name: "Painel" })).toBeInTheDocument();
  });
});

describe("ApiTokens", () => {
  it("shows a new token only once, with a usage example", async () => {
    const tokens: object[] = [];
    mockApi({
      "GET /auth/tokens": () => tokens,
      "GET /tasks": () => [{ id: 5, name: "relatorio" }],
      "POST /auth/tokens": (init) => {
        const body = JSON.parse(String(init?.body));
        const info = {
          id: 1,
          name: body.name,
          prefix: "rts_abc123",
          task_id: body.task_id,
          task_name: body.task_id ? "relatorio" : null,
          created_at: "2026-11-18T00:00:00Z",
          last_used_at: null,
          revoked_at: null,
        };
        tokens.push(info);
        return { ...info, token: "rts_abc123segredo" };
      },
    });
    const user = userEvent.setup();
    renderWithProviders(<ApiTokens />);
    expect(await screen.findByText("Nenhum token criado.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Nome"), "ci");
    await user.selectOptions(screen.getByLabelText("Pode disparar"), "5");
    await user.click(screen.getByRole("button", { name: "Criar token" }));

    expect(await screen.findByTestId("new-token")).toHaveTextContent("rts_abc123segredo");
    expect(screen.getByText(/Authorization: Bearer rts_abc123segredo/)).toHaveTextContent("/trigger/tasks/5");
    await user.click(screen.getByRole("button", { name: "Fechar" }));
    await waitFor(() => expect(screen.queryByText("rts_abc123segredo")).not.toBeInTheDocument());
    expect(screen.getByText("rts_abc123…")).toBeInTheDocument();
  });
});
