import { describe, expect, it } from "vitest";

import { errorMessage } from "../api/client";
import { formatDuration, formatPercent, formatRelative } from "./format";

describe("formatDuration", () => {
  it.each([
    [null, "—"],
    [450, "450 ms"],
    [1000, "1s"],
    [2500, "2,5s"],
    [65_000, "1min 05s"],
    [3_725_000, "1h 02min"],
  ])("%s -> %s", (ms, expected) => {
    expect(formatDuration(ms)).toBe(expected);
  });
});

describe("formatPercent / formatRelative", () => {
  it("formats rates in pt-BR", () => {
    expect(formatPercent(0.755)).toBe("75,5%");
    expect(formatPercent(null)).toBe("—");
  });

  it("formats relative times", () => {
    const now = new Date("2026-11-16T12:00:00Z");
    expect(formatRelative("2026-11-16T12:05:00Z", now)).toBe("em 5 minutos");
    expect(formatRelative("2026-11-16T10:00:00Z", now)).toBe("há 2 horas");
  });

  it("counts calendar days instead of rounding hours", () => {
    const mondayNight = new Date(2026, 10, 16, 21, 40); // local time
    const wednesdayMorning = new Date(2026, 10, 18, 8, 30).toISOString();
    expect(formatRelative(wednesdayMorning, mondayNight)).toBe("depois de amanhã");
    const tuesdayMorning = new Date(2026, 10, 17, 8, 30).toISOString();
    expect(formatRelative(tuesdayMorning, mondayNight)).toBe("amanhã");
    const nextMonday = new Date(2026, 10, 23, 8, 30).toISOString();
    expect(formatRelative(nextMonday, mondayNight)).toBe("em 7 dias");
  });
});

describe("errorMessage", () => {
  it("uses string details as-is", () => {
    expect(errorMessage({ detail: "Já existe um grupo chamado 'x'." }, 409)).toBe(
      "Já existe um grupo chamado 'x'.",
    );
  });

  it("flattens pydantic validation errors", () => {
    const body = {
      detail: [
        { loc: ["body", "cron_expressions"], msg: "Value error, '61 * * * *': Valor 61 fora do intervalo" },
      ],
    };
    expect(errorMessage(body, 422)).toBe("cron_expressions: '61 * * * *': Valor 61 fora do intervalo");
  });

  it("falls back to a generic message", () => {
    expect(errorMessage(null, 502)).toBe("Erro 502 ao comunicar com o servidor.");
  });
});
