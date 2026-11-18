import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Variable } from "../../api/types";
import { bodyOf, mockApi, renderWithProviders } from "../../test/utils";
import { VariablesEditor } from "./VariablesEditor";

const base = { scope: "group", owner_id: 1, description: "", created_at: "", updated_at: "" } as const;
const VARS: Variable[] = [
  { ...base, id: 1, key: "API_URL", value: "https://x", is_secret: false, has_value: true },
  { ...base, id: 2, key: "TOKEN", value: null, is_secret: true, has_value: true },
  { ...base, id: 3, key: "PENDING", value: null, is_secret: true, has_value: false },
];

describe("VariablesEditor", () => {
  it("never shows secret values and flags pending ones", async () => {
    mockApi({ "GET /variables": () => VARS });
    renderWithProviders(<VariablesEditor scope="group" ownerId={1} />);

    const tokenRow = (await screen.findByText("TOKEN")).closest("tr")!;
    expect(within(tokenRow).getByText(/••••••/)).toBeInTheDocument();
    expect(within(tokenRow).getByRole("button", { name: "Substituir TOKEN" })).toBeInTheDocument();
    expect(screen.getByText("https://x")).toBeInTheDocument();
    expect(within(screen.getByText("PENDING").closest("tr")!).getByText("a preencher")).toBeInTheDocument();
  });

  it("replacing a secret with an empty value keeps the current one (value omitted)", async () => {
    const user = userEvent.setup();
    const api = mockApi({
      "GET /variables": () => VARS,
      "PATCH /variables/2": () => VARS[1],
    });
    renderWithProviders(<VariablesEditor scope="group" ownerId={1} />);

    await user.click(await screen.findByRole("button", { name: "Substituir TOKEN" }));
    const value = screen.getByLabelText("Valor");
    expect(value).toHaveAttribute("type", "password");
    expect(value).toHaveValue("");
    await user.type(screen.getByLabelText("Descrição"), "token da API");
    await user.click(screen.getByRole("button", { name: "Salvar" }));

    await screen.findByText("Variável TOKEN atualizada.");
    expect(bodyOf(api, "PATCH /variables/2")).toEqual({
      key: "TOKEN",
      description: "token da API",
      is_secret: true,
    });
  });

  it("creates a variable at the given scope", async () => {
    const user = userEvent.setup();
    const api = mockApi({
      "GET /variables": () => [],
      "POST /variables": () => ({ ...VARS[0], id: 9, key: "NEW_KEY" }),
    });
    renderWithProviders(<VariablesEditor scope="subcategory" ownerId={7} />);

    expect(await screen.findByText("Nenhuma variável neste nível.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Adicionar" }));
    await user.type(screen.getByLabelText("Chave"), "new key");
    await user.type(screen.getByLabelText("Valor"), "abc");
    await user.click(screen.getByLabelText("Secreta"));
    await user.click(screen.getByRole("button", { name: "Salvar" }));

    await screen.findByText("Variável NEW_KEY criada.");
    expect(bodyOf(api, "POST /variables")).toEqual({
      scope: "subcategory",
      owner_id: 7,
      key: "NEW_KEY",
      value: "abc",
      is_secret: true,
      description: "",
    });
  });

  it("shows API errors", async () => {
    const user = userEvent.setup();
    mockApi({
      "GET /variables": () => [],
      "POST /variables": () =>
        new Response(JSON.stringify({ detail: "A variável 'X' já existe neste nível." }), { status: 409 }),
    });
    renderWithProviders(<VariablesEditor scope="global" ownerId={null} />);
    await user.click(await screen.findByRole("button", { name: "Adicionar" }));
    await user.type(screen.getByLabelText("Chave"), "X");
    await user.type(screen.getByLabelText("Valor"), "1");
    await user.click(screen.getByRole("button", { name: "Salvar" }));
    expect(await screen.findByText("A variável 'X' já existe neste nível.")).toBeInTheDocument();
  });
});
