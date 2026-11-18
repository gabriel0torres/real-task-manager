import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { UpdateProgress, UpdateStatus } from "../../api/updates";
import { bodyOf, mockApi, renderWithProviders } from "../../test/utils";
import { UpdatesPanel } from "./UpdatesPanel";

const BASE: UpdateStatus = {
  current_version: "0.1.0",
  check_enabled: true,
  checked_at: "2026-11-18T10:00:00Z",
  error: null,
  latest_version: "0.2.0",
  latest_tag: "v0.2.0",
  release_url: "https://github.com/x/y/releases/tag/v0.2.0",
  release_notes: "- Avisos de nova versão\n- Correções",
  published_at: "2026-11-18T09:00:00Z",
  update_available: true,
  install_type: "python",
  can_self_update: true,
  update_in_progress: false,
  progress: null,
  last_duration_seconds: null,
  last_result: null,
  instructions: "Rode o instalador novamente",
};

const STEP_IDS = [
  ["request", "Pedido registrado", false],
  ["start", "Iniciando o atualizador", false],
  ["download", "Baixando a nova versão", false],
  ["stop", "Parando o RTS", true],
  ["backup", "Copiando o banco de dados", true],
  ["install", "Instalando a nova versão", true],
  ["restart", "Iniciando o RTS atualizado", true],
] as const;

/** Progress with the first ``done`` steps finished and the next one running. */
function progressAt(done: number, detail: string | null = null, running = true): UpdateProgress {
  const t0 = Date.now() - 60_000;
  const at = (i: number) => new Date(t0 + i * 5_000).toISOString();
  return {
    version: "v0.2.0",
    from_version: "0.1.0",
    started_at: at(0),
    updated_at: at(done),
    current_step: Math.min(done, STEP_IDS.length - 1),
    total_steps: STEP_IDS.length,
    failed: false,
    completed: done === STEP_IDS.length,
    steps: STEP_IDS.map(([id, label, offline], i) => ({
      id,
      label,
      api_offline: offline,
      status: i < done ? "done" : i === done && running ? "running" : "pending",
      started_at: i <= done ? at(i) : null,
      finished_at: i < done ? at(i + 1) : null,
      detail: i === done ? detail : null,
    })),
  };
}

const dashboard = (running: number) => ({
  running: Array.from({ length: running }, (_, i) => ({ id: i + 1 })),
  upcoming: [],
  recent_failures: [],
  stats: {},
  counts: {},
  worker: { online: true },
});

describe("UpdatesPanel", () => {
  it("shows the new version, notes and applies after confirmation", async () => {
    const api = mockApi({
      "GET /system/update": () => BASE,
      "GET /dashboard": () => dashboard(2),
      "POST /settings/update/apply": () => ({
        version: "v0.2.0",
        from_version: "0.1.0",
        requested_at: "2026-11-18T10:05:00Z",
      }),
    });
    const user = userEvent.setup();
    renderWithProviders(<UpdatesPanel />);

    expect(await screen.findByTestId("current-version")).toHaveTextContent("0.1.0");
    expect(screen.getByTestId("release-notes")).toHaveTextContent("Avisos de nova versão");
    await user.click(screen.getByRole("button", { name: "Atualizar para v0.2.0" }));
    expect(await screen.findByText("2 execução(ões) em andamento agora serão interrompidas.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Atualizar agora" }));

    expect(await screen.findByText(/Atualizando para v0.2.0/)).toBeInTheDocument();
    expect(bodyOf(api, "POST /settings/update/apply")).toEqual({ version: "v0.2.0" });
  });

  it("reloads the page once the server answers with the new version", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    let version = "0.1.0";
    mockApi({
      "GET /system/update": () => BASE,
      "GET /dashboard": () => dashboard(0),
      "POST /settings/update/apply": () => {
        version = "0.2.0";
        return { version: "v0.2.0", from_version: "0.1.0", requested_at: "" };
      },
      "GET /health": () => ({ status: "ok", version }),
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<UpdatesPanel />);
    await user.click(await screen.findByRole("button", { name: "Atualizar para v0.2.0" }));
    expect(screen.getByText("Nenhuma execução em andamento agora.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Atualizar agora" }));

    await vi.advanceTimersByTimeAsync(3500);
    expect(await screen.findByText(/RTS atualizado para v0.2.0/)).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(2000);
    await waitFor(() => expect(reload).toHaveBeenCalled());
    vi.useRealTimers();
  });

  it("shows instructions when this installation can't update itself", async () => {
    mockApi({
      "GET /system/update": () => ({
        ...BASE,
        install_type: "docker",
        can_self_update: false,
        instructions: "git pull\ndocker compose up -d --build",
      }),
      "GET /dashboard": () => dashboard(0),
    });
    renderWithProviders(<UpdatesPanel />);
    expect(await screen.findByText(/docker compose up -d --build/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Atualizar para/ })).not.toBeInTheDocument();
  });

  it("reports up to date, check errors and the last result", async () => {
    mockApi({
      "GET /system/update": () => ({
        ...BASE,
        latest_version: "0.1.0",
        latest_tag: "v0.1.0",
        update_available: false,
        release_notes: null,
        last_result: {
          ok: false,
          version: "v0.1.0",
          from_version: "0.0.9",
          finished_at: "2026-11-18T08:00:00Z",
          message: "Falha na atualização (veja data/update.log).",
        },
      }),
      "GET /dashboard": () => dashboard(0),
    });
    renderWithProviders(<UpdatesPanel />);
    expect(await screen.findByText("Você está na versão mais recente.")).toBeInTheDocument();
    expect(screen.getByText(/Falha na atualização \(veja data\/update.log\)/)).toBeInTheDocument();
  });

  it("shows each step, the current one and the time estimate while updating", async () => {
    mockApi({
      "GET /system/update": () => ({
        ...BASE,
        update_available: false,
        update_in_progress: true,
        last_duration_seconds: 180,
        progress: progressAt(2, "rts-0.2.0-py3-none-any.whl: 0,2 de 0,4 MB"),
      }),
      "GET /dashboard": () => dashboard(0),
    });
    renderWithProviders(<UpdatesPanel />);

    expect(await screen.findByTestId("update-current-step")).toHaveTextContent(
      "Etapa 3 de 7: Baixando a nova versão",
    );
    expect(screen.getByText("Atualizando de 0.1.0 para v0.2.0")).toBeInTheDocument();
    expect(screen.getByText("rts-0.2.0-py3-none-any.whl: 0,2 de 0,4 MB")).toBeInTheDocument();
    expect(screen.getByTestId("update-elapsed")).toHaveTextContent(/decorrido 1min 0\ds · faltam cerca de 2min/);
    expect(screen.getByTestId("update-step-request")).toHaveAttribute("data-state", "done");
    expect(screen.getByTestId("update-step-download")).toHaveAttribute("data-state", "running");
    expect(screen.getByTestId("update-step-install")).toHaveAttribute("data-state", "waiting");
    expect(screen.getByTestId("update-step-install")).toHaveTextContent("(servidor fora do ar)");
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "36");
  });

  it("keeps the last known progress while the server is down for the installation", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let down = false;
    mockApi({
      "GET /system/update": () =>
        down
          ? new Response("", { status: 502 })
          : { ...BASE, update_available: false, update_in_progress: true, progress: progressAt(2, "a.whl: 1 de 2 MB") },
      "GET /dashboard": () => dashboard(0),
    });
    renderWithProviders(<UpdatesPanel />);
    expect(await screen.findByTestId("update-current-step")).toHaveTextContent("Etapa 3 de 7");

    down = true;
    await vi.advanceTimersByTimeAsync(2_500);
    expect(await screen.findByText(/O RTS está parado para a instalação/)).toBeInTheDocument();
    // Download finished on the server side is unknown; the first offline step is assumed.
    expect(screen.getByTestId("update-current-step")).toHaveTextContent("Etapa 4 de 7: Parando o RTS");
    expect(screen.getByTestId("update-step-stop")).toHaveAttribute("data-state", "running");
    // The download was running at the last news; the updater moved on, so it finished.
    expect(screen.getByTestId("update-step-download")).toHaveAttribute("data-state", "done");
    vi.useRealTimers();
  });

  it("shows how long the last update took and its steps", async () => {
    const user = userEvent.setup();
    mockApi({
      "GET /system/update": () => ({
        ...BASE,
        update_available: false,
        progress: progressAt(7),
        last_result: {
          ok: true,
          version: "v0.2.0",
          from_version: "0.1.0",
          requested_at: "2026-11-18T10:00:00Z",
          finished_at: "2026-11-18T10:02:15Z",
          message: "Atualizado para v0.2.0.",
        },
      }),
      "GET /dashboard": () => dashboard(0),
    });
    renderWithProviders(<UpdatesPanel />);
    expect(await screen.findByText(/levou 2min 15s/)).toBeInTheDocument();
    await user.click(screen.getByText("Ver etapas"));
    expect(screen.getByTestId("update-step-restart")).toHaveAttribute("data-state", "done");
    expect(screen.queryByTestId("update-current-step")).not.toBeInTheDocument();
  });
});
