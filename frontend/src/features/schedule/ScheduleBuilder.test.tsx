import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { mockApi, renderWithProviders } from "../../test/utils";
import { ScheduleBuilder } from "./ScheduleBuilder";

function previewApi(description = "Toda segunda e quarta às 08:30") {
  return mockApi({
    "POST /schedule/preview": (init) => {
      const body = JSON.parse(String(init?.body));
      return {
        valid: true,
        error: null,
        description,
        cron_expressions: body.cron_expressions,
        timezone: body.timezone ?? "America/Sao_Paulo",
        next_runs: ["2026-11-18T11:30:00Z", "2026-11-23T11:30:00Z"],
      };
    },
  });
}

describe("ScheduleBuilder", () => {
  it("rebuilds the weekly mode from an existing cron and shows the preview", async () => {
    const fetchMock = previewApi();
    renderWithProviders(
      <ScheduleBuilder value={["30 8 * * 1,3"]} timezone="America/Sao_Paulo" onChange={() => {}} />,
    );

    expect(screen.getByRole("radio", { name: "Dias da semana" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("button", { name: "segunda" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "quarta" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "sexta" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByLabelText("Horário 1")).toHaveValue("08:30");

    expect(await screen.findByTestId("schedule-description")).toHaveTextContent(
      "Toda segunda e quarta às 08:30",
    );
    // Preview rendered in the task time zone (08:30 in São Paulo = 11:30 UTC)
    expect(screen.getByTestId("schedule-next-runs")).toHaveTextContent("18/11/2026, 08:30");
    expect(fetchMock).toHaveBeenCalled();
  });

  it("opens unrecognised cron in advanced mode", () => {
    previewApi();
    renderWithProviders(<ScheduleBuilder value={["*/5 8-17 * * 1-5"]} timezone={null} onChange={() => {}} />);
    expect(screen.getByRole("radio", { name: "Avançado (cron)" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByLabelText(/Expressões cron/)).toHaveValue("*/5 8-17 * * 1-5");
  });

  it("emits cron when the user changes the visual selection", async () => {
    previewApi();
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(<ScheduleBuilder value={["0 8 * * *"]} timezone={null} onChange={onChange} />);

    await user.click(screen.getByRole("radio", { name: "A cada X minutos" }));
    expect(onChange).toHaveBeenLastCalledWith(["*/15 * * * *"], null);

    const input = screen.getByLabelText("Intervalo em minutos");
    await user.clear(input);
    await user.type(input, "5");
    expect(onChange).toHaveBeenLastCalledWith(["*/5 * * * *"], null);
  });

  it("supports several daily times and reports an empty weekday selection", async () => {
    previewApi();
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(<ScheduleBuilder value={["0 8 * * *"]} timezone={null} onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: "Adicionar horário" }));
    expect(onChange).toHaveBeenLastCalledWith(["0 8,12 * * *"], null);

    await user.click(screen.getByRole("radio", { name: "Dias da semana" }));
    for (const day of ["segunda", "terça", "quarta", "quinta", "sexta"]) {
      await user.click(screen.getByRole("button", { name: day }));
    }
    expect(onChange).toHaveBeenLastCalledWith([], "Selecione pelo menos um dia da semana.");
    expect(screen.getByText("Selecione pelo menos um dia.")).toBeInTheDocument();
  });

  it("selects the last day of the month", async () => {
    previewApi("No último dia do mês às 08:00");
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(<ScheduleBuilder value={["0 8 1 * *"]} timezone={null} onChange={onChange} />);
    await user.selectOptions(screen.getByLabelText("Dia do mês"), "last");
    expect(onChange).toHaveBeenLastCalledWith(["0 8 L * *"], null);
  });

  it("shows the server validation error for invalid advanced cron", async () => {
    mockApi({
      "POST /schedule/preview": () => ({
        valid: false,
        error: "Valor 61 fora do intervalo 0-59 no campo minuto.",
        description: null,
        cron_expressions: ["61 * * * *"],
        timezone: "UTC",
        next_runs: [],
      }),
    });
    renderWithProviders(<ScheduleBuilder value={["61 * * * *"]} timezone="UTC" onChange={() => {}} />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Valor 61 fora do intervalo 0-59 no campo minuto."),
    );
  });
});
