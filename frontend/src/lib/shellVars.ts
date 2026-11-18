/**
 * How each interpreter references environment variables.
 *
 * The RTS injects variables as environment variables and does NOT rewrite the
 * command: the shell itself expands them. So the syntax depends on the shell:
 * cmd uses %VAR%, bash/sh use $VAR, PowerShell uses $env:VAR, Python reads
 * os.environ. Using the wrong one (e.g. $VAR in cmd) leaves the text literal.
 */
import type { Shell } from "../api/types";

export const SHELL_LABELS: Record<Shell, string> = {
  bash: "bash",
  sh: "sh",
  cmd: "cmd (Prompt de Comando)",
  powershell: "PowerShell",
  pwsh: "PowerShell Core",
  python: "Python",
};

const NAME = "[A-Za-z_][A-Za-z0-9_]*";

export function varReference(shell: Shell, key: string): string {
  switch (shell) {
    case "cmd":
      return `%${key}%`;
    case "bash":
    case "sh":
      return `\${${key}}`;
    case "powershell":
    case "pwsh":
      return `$env:${key}`;
    case "python":
      return `os.environ['${key}']`;
  }
}

/** Global regex matching references in the shell's own syntax; key in any group. */
export function referenceRegex(shell: Shell): RegExp {
  switch (shell) {
    case "cmd":
      return new RegExp(`%(${NAME})%`, "g");
    case "bash":
    case "sh":
      return new RegExp(`\\$\\{(${NAME})\\}|\\$(${NAME})`, "g");
    case "powershell":
    case "pwsh":
      return new RegExp(`\\$env:(${NAME})|\\$\\{env:(${NAME})\\}`, "gi");
    case "python":
      return new RegExp(
        `os\\.environ\\s*\\[\\s*['"](${NAME})['"]\\s*\\]|os\\.environ\\.get\\(\\s*['"](${NAME})['"]|os\\.getenv\\(\\s*['"](${NAME})['"]`,
        "g",
      );
  }
}

export function keyOf(match: RegExpExecArray | RegExpMatchArray): string {
  return match.slice(1).find((g) => g !== undefined) ?? "";
}

/** Keys referenced in the command, using the shell's own syntax. */
export function referencedKeys(command: string, shell: Shell): string[] {
  return [...new Set([...command.matchAll(referenceRegex(shell))].map(keyOf))];
}

export interface SyntaxIssue {
  key: string;
  found: string;
  suggestion: string;
}

const FOREIGN: { shells: Shell[]; regex: () => RegExp }[] = [
  // %VAR% (cmd)
  { shells: ["cmd"], regex: () => new RegExp(`%(${NAME})%`, "g") },
  // $env:VAR (PowerShell)
  { shells: ["powershell", "pwsh"], regex: () => new RegExp(`\\$env:(${NAME})`, "gi") },
  // ${VAR} / $VAR (bash/sh) - "$env:" is excluded because "env" is not followed by a name char
  { shells: ["bash", "sh"], regex: () => new RegExp(`\\$\\{(${NAME})\\}|\\$(${NAME})(?!:)`, "g") },
];

/**
 * References to *known* variables written in another shell's syntax, e.g.
 * `$CAMINHO` with cmd (which needs `%CAMINHO%`). Unknown names are ignored so
 * regular shell variables ($1, $HOME, %DATE%...) never raise false alarms.
 */
export function findSyntaxIssues(command: string, shell: Shell, known: Iterable<string>): SyntaxIssue[] {
  const keys = new Set(known);
  const issues = new Map<string, SyntaxIssue>();
  for (const { shells, regex } of FOREIGN) {
    if (shells.includes(shell)) continue;
    for (const match of command.matchAll(regex())) {
      const key = keyOf(match);
      if (!keys.has(key)) continue;
      const found = match[0];
      if (!issues.has(found)) issues.set(found, { key, found, suggestion: varReference(shell, key) });
    }
  }
  return [...issues.values()];
}

export function fixSyntaxIssues(command: string, issues: SyntaxIssue[]): string {
  // Longest first so "${VAR}" is replaced before a shorter overlapping "$VAR".
  return [...issues]
    .sort((a, b) => b.found.length - a.found.length)
    .reduce((text, issue) => text.split(issue.found).join(issue.suggestion), command);
}
