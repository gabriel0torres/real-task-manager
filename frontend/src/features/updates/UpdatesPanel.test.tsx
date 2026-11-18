import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { UpdateStatus } from "../../api/updates";
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
  last_result: null,
  instructions: "Rode o instalador novamente",
};

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
});
