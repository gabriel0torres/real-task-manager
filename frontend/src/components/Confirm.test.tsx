import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConfirmProvider, useConfirm, type ConfirmOptions } from "./Confirm";

function Asker({ options, onAnswer }: { options: ConfirmOptions; onAnswer: (v: boolean) => void }) {
  const confirm = useConfirm();
  return (
    <button type="button" onClick={async () => onAnswer(await confirm(options))}>
      perguntar
    </button>
  );
}

function setup(options: ConfirmOptions) {
  const onAnswer = vi.fn();
  render(
    <ConfirmProvider>
      <Asker options={options} onAnswer={onAnswer} />
    </ConfirmProvider>,
  );
  return onAnswer;
}

describe("Confirm dialog", () => {
  it("danger: red action, focus starts on 'Voltar', Esc answers no", async () => {
    const user = userEvent.setup();
    const onAnswer = setup({ title: "Excluir a tarefa?", message: <p>Sem volta.</p>, confirmLabel: "Excluir", tone: "danger" });
    await user.click(screen.getByRole("button", { name: "perguntar" }));

    const dialog = screen.getByRole("alertdialog", { name: "Excluir a tarefa?" });
    expect(dialog).toHaveAccessibleDescription("Sem volta.");
    expect(screen.getByRole("button", { name: "Voltar" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Excluir" }).className).toContain("bg-red-600");

    await user.keyboard("{Escape}");
    expect(onAnswer).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("primary: Enter on the focused action answers yes; clicking outside answers no", async () => {
    const user = userEvent.setup();
    const onAnswer = setup({ title: "Executar todas?", confirmLabel: "Executar todas" });
    await user.click(screen.getByRole("button", { name: "perguntar" }));
    expect(screen.getByRole("button", { name: "Executar todas" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onAnswer).toHaveBeenLastCalledWith(true);

    await user.click(screen.getByRole("button", { name: "perguntar" }));
    await user.click(screen.getByRole("alertdialog").parentElement!);
    expect(onAnswer).toHaveBeenLastCalledWith(false);
  });
});
