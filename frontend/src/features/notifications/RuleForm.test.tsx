import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DEFAULT_RULE } from "../../api/notifications";
import { mockApi, renderWithProviders } from "../../test/utils";
import { RuleForm } from "./RuleForm";

describe("RuleForm", () => {
  it("parses targets (lines, commas) and saves the rule", async () => {
    mockApi({});
    const onSave = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<RuleForm initial={DEFAULT_RULE} onSave={onSave} />);

    await user.click(screen.getByLabelText("voltar ao sucesso após falha"));
    await user.type(screen.getByLabelText("E-mails"), "a@x.com, b@x.com{enter}  {enter}c@x.com");
    await user.type(screen.getByLabelText("Chats do Telegram"), "-100123");
    await user.click(screen.getByRole("button", { name: "Salvar" }));

    expect(onSave).toHaveBeenCalledWith({
      ...DEFAULT_RULE,
      on_recovery: true,
      email_to: ["a@x.com", "b@x.com", "c@x.com"],
      telegram_chat_ids: ["-100123"],
      webhook_urls: [],
    });
  });

  it("sends a test message to the first target", async () => {
    const api = mockApi({ "POST /notifications/test": () => ({ ok: true, error: null }) });
    const user = userEvent.setup();
    renderWithProviders(<RuleForm initial={{ ...DEFAULT_RULE, webhook_urls: ["https://h.example/a"] }} onSave={() => {}} />);
    await user.click(screen.getByRole("button", { name: "Enviar teste para https://h.example/a" }));
    expect(await screen.findByText("Mensagem de teste enviada para https://h.example/a.")).toBeInTheDocument();
    expect(JSON.parse(String(api.mock.calls[0][1]?.body))).toEqual({ channel: "webhook", target: "https://h.example/a" });
  });
});
