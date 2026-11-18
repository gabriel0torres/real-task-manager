import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ImportOptions, ImportReport, PlanItem } from "../../api/transfer";
import { mockApi, renderWithProviders } from "../../test/utils";
import { ImportWizard } from "./ImportWizard";

const header = {
  schema_version: 1,
  rts_version: "0.1.0",
  exported_at: "2026-11-17T12:00:00Z",
  scope: "group" as const,
  secrets_mode: "encrypted" as const,
  groups: ["instagram"],
  has_settings: false,
};

function item(partial: Partial<PlanItem> & Pick<PlanItem, "path" | "name" | "kind">): PlanItem {
  return {
    depth: 0,
    action: "create",
    conflict: false,
    resolution: null,
    allowed_resolutions: [],
    new_name: null,
    details: [],
    ...partial,
  };
}

/** Fake backend: conflict on the group; password "segredo123"; merge reveals a child. */
function fakeServer() {
  const calls: { step: string; body: ImportOptions }[] = [];
  const report = (body: ImportOptions, applied = false): ImportReport => {
    const res = body.resolutions["group:instagram"]?.action ?? "skip";
    const items: PlanItem[] = [
      item({
        path: "group:instagram",
        name: "instagram",
        kind: "group",
        conflict: true,
        resolution: res,
        allowed_resolutions: ["overwrite", "merge", "rename", "skip"],
        action: res === "skip" ? "skip" : "update",
        details: res === "skip" ? ["já existe; nada abaixo dele será importado"] : [],
      }),
    ];
    if (res === "merge") {
      items.push(item({ path: "group:instagram/sub:novos", name: "novos", kind: "subcategory", depth: 1 }));
    }
    const passwordOk = body.password ? body.password === "segredo123" : null;
    return {
      valid: passwordOk !== false,
      applied,
      errors: passwordOk === false ? ["Senha incorreta."] : [],
      header,
      needs_password: true,
      password_ok: passwordOk,
      items: passwordOk === false ? [] : items,
      pending_secrets: [],
      summary: { create: res === "merge" ? 1 : 0, update: res === "skip" ? 0 : 1, skip: res === "skip" ? 1 : 0 },
      tasks_paused: !body.activate_tasks,
    };
  };
  const api = mockApi({
    "GET /tree": () => [],
    "POST /transfer/import/preview": (init) => {
      const body = JSON.parse(String(init?.body));
      calls.push({ step: "preview", body });
      return report(body);
    },
    "POST /transfer/import/apply": (init) => {
      const body = JSON.parse(String(init?.body));
      calls.push({ step: "apply", body });
      return report(body, true);
    },
  });
  return { api, calls };
}

describe("ImportWizard", () => {
  it("previews, asks for the password, resolves conflicts and applies", async () => {
    const { calls } = fakeServer();
    const user = userEvent.setup();
    renderWithProviders(<ImportWizard />);

    const file = new File(["schema_version: 1\n"], "export.yaml", { type: "application/x-yaml" });
    await user.upload(document.getElementById("import-file") as HTMLInputElement, file);

    expect(await screen.findByText("export.yaml")).toBeInTheDocument();
    expect(await screen.findByText("Cifrados com senha")).toBeInTheDocument();
    const plan = await screen.findByTestId("import-plan");
    expect(within(plan).getByText("já existe; nada abaixo dele será importado")).toBeInTheDocument();
    expect(within(plan).getByLabelText("Resolução para instagram")).toHaveValue("skip");
    expect(screen.getByRole("button", { name: "Importar" })).toBeDisabled(); // password missing

    await user.type(screen.getByLabelText(/Senha da exportação/), "errada");
    expect(await screen.findByText("Senha incorreta.")).toBeInTheDocument();
    await user.clear(screen.getByLabelText(/Senha da exportação/));
    await user.type(screen.getByLabelText(/Senha da exportação/), "segredo123");
    expect(await screen.findByText("Senha correta.")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Resolução para instagram"), "merge");
    expect(await screen.findByText("novos")).toBeInTheDocument();
    expect(screen.getByTestId("import-summary")).toHaveTextContent("1 a criar · 1 a atualizar");
    expect(screen.getByTestId("import-summary")).toHaveTextContent("tarefas entram pausadas");

    await user.click(screen.getByLabelText(/Ativar as tarefas importadas/));
    await waitFor(() => expect(screen.getByTestId("import-summary")).not.toHaveTextContent("pausadas"));

    await user.click(screen.getByRole("button", { name: "Importar" }));
    expect(await screen.findByText(/Importação concluída: 1 criado/)).toBeInTheDocument();

    const applied = calls.find((c) => c.step === "apply")!.body;
    expect(applied.password).toBe("segredo123");
    expect(applied.activate_tasks).toBe(true);
    expect(applied.resolutions).toEqual({ "group:instagram": { action: "merge" } });
  });

  it("shows validation errors from the server", async () => {
    mockApi({
      "GET /tree": () => [],
      "POST /transfer/import/preview": () => ({
        valid: false,
        applied: false,
        errors: ["O arquivo usa schema_version 2, mas esta instalação suporta até 1."],
        header: null,
        needs_password: false,
        password_ok: null,
        items: [],
        pending_secrets: [],
        summary: {},
        tasks_paused: true,
      }),
    });
    const user = userEvent.setup();
    renderWithProviders(<ImportWizard />);
    await user.upload(
      document.getElementById("import-file") as HTMLInputElement,
      new File(["schema_version: 2"], "novo.yaml"),
    );
    expect(await screen.findByText(/suporta até 1/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Importar" })).not.toBeInTheDocument();
  });
});
