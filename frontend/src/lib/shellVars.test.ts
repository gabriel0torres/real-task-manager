import { describe, expect, it } from "vitest";

import { findSyntaxIssues, fixSyntaxIssues, referencedKeys, varReference } from "./shellVars";

const KNOWN = ["CAMINHO_PADRAO", "API_TOKEN"];

describe("varReference", () => {
  it("uses each shell's syntax", () => {
    expect(varReference("cmd", "X")).toBe("%X%");
    expect(varReference("bash", "X")).toBe("${X}");
    expect(varReference("sh", "X")).toBe("${X}");
    expect(varReference("powershell", "X")).toBe("$env:X");
    expect(varReference("python", "X")).toBe("os.environ['X']");
  });
});

describe("referencedKeys", () => {
  it("finds references in the shell's own syntax only", () => {
    expect(referencedKeys("echo %A% %B% $C", "cmd")).toEqual(["A", "B"]);
    expect(referencedKeys('echo "$A" ${B} %C%', "bash")).toEqual(["A", "B"]);
    expect(referencedKeys("Write-Host $env:A ${env:B} $C", "powershell")).toEqual(["A", "B"]);
    expect(referencedKeys("os.environ['A']; os.environ.get(\"B\"); os.getenv('C')", "python")).toEqual([
      "A",
      "B",
      "C",
    ]);
  });
});

describe("findSyntaxIssues", () => {
  it("detects the reported case: $VAR used with cmd", () => {
    const command = "python $CAMINHO_PADRAO\\gravar_log_teste.py";
    const issues = findSyntaxIssues(command, "cmd", KNOWN);
    expect(issues).toEqual([
      { key: "CAMINHO_PADRAO", found: "$CAMINHO_PADRAO", suggestion: "%CAMINHO_PADRAO%" },
    ]);
    expect(fixSyntaxIssues(command, issues)).toBe("python %CAMINHO_PADRAO%\\gravar_log_teste.py");
  });

  it("detects cmd/PowerShell syntax in bash and suggests ${VAR}", () => {
    const issues = findSyntaxIssues("echo %API_TOKEN% $env:CAMINHO_PADRAO", "bash", KNOWN);
    expect(issues.map((i) => [i.found, i.suggestion])).toEqual([
      ["%API_TOKEN%", "${API_TOKEN}"],
      ["$env:CAMINHO_PADRAO", "${CAMINHO_PADRAO}"],
    ]);
  });

  it("suggests $env:VAR in PowerShell and os.environ in Python", () => {
    expect(findSyntaxIssues("Write-Host $API_TOKEN", "powershell", KNOWN)[0].suggestion).toBe(
      "$env:API_TOKEN",
    );
    expect(findSyntaxIssues("print('${API_TOKEN}')", "python", KNOWN)[0].suggestion).toBe(
      "os.environ['API_TOKEN']",
    );
  });

  it("ignores correct syntax and unknown names (no false alarms)", () => {
    expect(findSyntaxIssues("echo %CAMINHO_PADRAO% %DATE%", "cmd", KNOWN)).toEqual([]);
    expect(findSyntaxIssues('echo "$1" $HOME ${CAMINHO_PADRAO}', "bash", KNOWN)).toEqual([]);
    expect(findSyntaxIssues("$env:API_TOKEN", "pwsh", KNOWN)).toEqual([]);
    expect(findSyntaxIssues("echo $OUTRA", "cmd", KNOWN)).toEqual([]);
  });

  it("fixes ${VAR} before $VAR when both appear", () => {
    const command = "echo ${API_TOKEN} $API_TOKEN";
    const issues = findSyntaxIssues(command, "cmd", KNOWN);
    expect(fixSyntaxIssues(command, issues)).toBe("echo %API_TOKEN% %API_TOKEN%");
  });
});
