import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Field, Input } from "./ui";

function renderField() {
  render(
    <Field label="Diretório de trabalho" htmlFor="wd" help="Pasta em que o comando é executado.">
      <Input id="wd" />
    </Field>,
  );
  return screen.getByRole("button", { name: "Ajuda: Diretório de trabalho" });
}

describe("HelpTip", () => {
  it("shows the explanation on hover and hides it when the pointer leaves", async () => {
    const user = userEvent.setup();
    const icon = renderField();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    await user.hover(icon);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Pasta em que o comando é executado.");
    expect(icon).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id);

    await user.unhover(icon);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("opens on keyboard focus and closes with Escape", async () => {
    const user = userEvent.setup();
    renderField();
    await user.tab(); // the "?" comes before the input
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("keeps the label linked to the input", () => {
    renderField();
    expect(screen.getByLabelText("Diretório de trabalho")).toHaveAttribute("id", "wd");
  });
});
