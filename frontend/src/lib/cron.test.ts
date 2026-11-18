import { describe, expect, it } from "vitest";

import { defaultModel, fromCron, modelProblem, toCron, type ScheduleModel } from "./cron";

describe("toCron", () => {
  it("builds interval expressions", () => {
    expect(toCron({ mode: "minutes", every: 15 })).toEqual(["*/15 * * * *"]);
    expect(toCron({ mode: "minutes", every: 1 })).toEqual(["* * * * *"]);
    expect(toCron({ mode: "hours", every: 2, minute: 30 })).toEqual(["30 */2 * * *"]);
    expect(toCron({ mode: "hours", every: 1, minute: 5 })).toEqual(["5 * * * *"]);
  });

  it("groups times with the same minute into one expression", () => {
    expect(toCron({ mode: "daily", times: ["17:30", "08:30", "12:00"] })).toEqual([
      "0 12 * * *",
      "30 8,17 * * *",
    ]);
  });

  it("builds weekly and monthly expressions", () => {
    expect(toCron({ mode: "weekly", days: [3, 1], times: ["08:30"] })).toEqual(["30 8 * * 1,3"]);
    expect(toCron({ mode: "weekly", days: [], times: ["08:30"] })).toEqual([]);
    expect(toCron({ mode: "monthly", day: 15, times: ["09:00"] })).toEqual(["0 9 15 * *"]);
    expect(toCron({ mode: "monthly", day: "last", times: ["23:00"] })).toEqual(["0 23 L * *"]);
  });

  it("ignores invalid / duplicate times and blank advanced lines", () => {
    expect(toCron({ mode: "daily", times: ["08:00", "08:00", ""] })).toEqual(["0 8 * * *"]);
    expect(toCron({ mode: "advanced", expressions: [" 0 8 * * * ", "", "  "] })).toEqual(["0 8 * * *"]);
    expect(toCron({ mode: "none" })).toEqual([]);
  });
});

describe("fromCron", () => {
  const cases: [string[], ScheduleModel][] = [
    [[], { mode: "none" }],
    [["*/10 * * * *"], { mode: "minutes", every: 10 }],
    [["* * * * *"], { mode: "minutes", every: 1 }],
    [["15 */3 * * *"], { mode: "hours", every: 3, minute: 15 }],
    [["0 * * * *"], { mode: "hours", every: 1, minute: 0 }],
    [["0 8 * * *", "30 17 * * *"], { mode: "daily", times: ["08:00", "17:30"] }],
    [["30 8,17 * * *"], { mode: "daily", times: ["08:30", "17:30"] }],
    [["30 8 * * 1,3"], { mode: "weekly", days: [1, 3], times: ["08:30"] }],
    [["0 9 * * 7"], { mode: "weekly", days: [0], times: ["09:00"] }],
    [["0 9 l * *"], { mode: "monthly", day: "last", times: ["09:00"] }],
    [["0 9 L * *"], { mode: "monthly", day: "last", times: ["09:00"] }],
    [["0 9 5 * *"], { mode: "monthly", day: 5, times: ["09:00"] }],
  ];

  it.each(cases)("rebuilds %j", (expressions, expected) => {
    expect(fromCron(expressions)).toEqual(expected);
  });

  it.each([
    [["0 8 * * 1-5"]], // ranges
    [["0 8 * * mon"]], // names
    [["0 8 1 * 1"]], // dom + dow
    [["0 8 * 1 *"]], // month restricted
    [["0 8 * * 1", "0 9 * * 2"]], // different days per expression
    [["*/5 8-17 * * *"]],
    [["61 8 * * *"]],
    [["garbage"]],
  ])("falls back to advanced for %j", (expressions) => {
    expect(fromCron(expressions)).toEqual({ mode: "advanced", expressions });
  });

  it("round-trips every visual model", () => {
    const models: ScheduleModel[] = [
      { mode: "minutes", every: 5 },
      { mode: "hours", every: 6, minute: 0 },
      { mode: "daily", times: ["06:15", "18:15", "23:59"] },
      { mode: "weekly", days: [0, 6], times: ["10:00"] },
      { mode: "monthly", day: 31, times: ["00:00", "12:30"] },
    ];
    for (const model of models) expect(fromCron(toCron(model))).toEqual(model);
  });
});

describe("modelProblem / defaultModel", () => {
  it("reports incomplete selections", () => {
    expect(modelProblem({ mode: "weekly", days: [], times: ["08:00"] })).toMatch(/dia da semana/);
    expect(modelProblem({ mode: "daily", times: [""] })).toMatch(/horários válidos/);
    expect(modelProblem({ mode: "daily", times: [] })).toMatch(/pelo menos um horário/);
    expect(modelProblem({ mode: "advanced", expressions: [""] })).toMatch(/expressão cron/);
    expect(modelProblem({ mode: "daily", times: ["08:00"] })).toBeNull();
    expect(modelProblem({ mode: "none" })).toBeNull();
  });

  it("keeps times when switching modes and seeds advanced with current cron", () => {
    const daily: ScheduleModel = { mode: "daily", times: ["07:45"] };
    expect(defaultModel("weekly", daily)).toEqual({ mode: "weekly", days: [1, 2, 3, 4, 5], times: ["07:45"] });
    expect(defaultModel("advanced", daily)).toEqual({ mode: "advanced", expressions: ["45 7 * * *"] });
  });
});
