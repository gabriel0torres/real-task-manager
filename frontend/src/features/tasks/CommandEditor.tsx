import {
  autocompletion,
  type CompletionContext,
  type CompletionSource,
} from "@codemirror/autocomplete";
import { python } from "@codemirror/lang-python";
import { StreamLanguage, type StreamParser } from "@codemirror/language";
import { powerShell } from "@codemirror/legacy-modes/mode/powershell";
import { shell as shellMode } from "@codemirror/legacy-modes/mode/shell";
import type { Extension } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  MatchDecorator,
  ViewPlugin,
  type DecorationSet,
  type ViewUpdate,
} from "@codemirror/view";
import { vscodeDark } from "@uiw/codemirror-theme-vscode";
import CodeMirror, { type ReactCodeMirrorRef } from "@uiw/react-codemirror";
import { forwardRef, useImperativeHandle, useMemo, useRef } from "react";

import type { Shell } from "../../api/types";
import { keyOf, referenceRegex, varReference } from "../../lib/shellVars";

/** Minimal Windows batch (cmd) highlighting: comments, keywords, strings, %VAR%. */
const batch: StreamParser<unknown> = {
  name: "batch",
  token(stream) {
    if (stream.sol() && stream.match(/^\s*(rem\b|::)/i)) {
      stream.skipToEnd();
      return "comment";
    }
    if (stream.match(/^"[^"]*"?/)) return "string";
    if (stream.match(/^%~?[A-Za-z0-9_]+%?/)) return "variableName";
    if (
      stream.match(
        /^(echo|set|if|else|for|in|do|goto|call|exit|not|exist|errorlevel|setlocal|endlocal|cd|pushd|popd|start|copy|move|del|mkdir|type)\b/i,
      )
    ) {
      return "keyword";
    }
    if (stream.match(/^@?\w+/)) return null;
    stream.next();
    return null;
  },
};

function language(shell: Shell): Extension {
  switch (shell) {
    case "bash":
    case "sh":
      return StreamLanguage.define(shellMode);
    case "powershell":
    case "pwsh":
      return StreamLanguage.define(powerShell);
    case "python":
      return python();
    case "cmd":
      return StreamLanguage.define(batch);
  }
}

/** Highlights variable references: RTS variables in teal, other names in orange. */
function variableHighlighter(shell: Shell, known: Set<string>): Extension {
  const decorator = new MatchDecorator({
    regexp: referenceRegex(shell),
    decoration: (match) => {
      const key = keyOf(match);
      const isKnown = known.has(key);
      return Decoration.mark({
        class: isKnown ? "cm-rts-var" : "cm-rts-var-unknown",
        attributes: {
          title: isKnown
            ? `Variável do RTS: ${key}`
            : `${key} não é uma variável do RTS (pode existir no sistema operacional)`,
        },
      });
    },
  });
  return ViewPlugin.fromClass(
    class {
      decorations: DecorationSet;
      constructor(view: EditorView) {
        this.decorations = decorator.createDeco(view);
      }
      update(update: ViewUpdate) {
        this.decorations = decorator.updateDeco(update, this.decorations);
      }
    },
    { decorations: (v) => v.decorations },
  );
}

const editorTheme = EditorView.theme({
  "&": { fontSize: "13px", borderRadius: "0.375rem" },
  ".cm-scroller": { fontFamily: "var(--font-mono)", lineHeight: "1.55" },
  ".cm-content": { padding: "8px 0" },
  ".cm-rts-var": {
    color: "#4ec9b0",
    backgroundColor: "rgba(78, 201, 176, 0.14)",
    borderRadius: "3px",
    fontWeight: "600",
  },
  ".cm-rts-var-unknown": {
    color: "#ce9178",
    textDecoration: "underline dotted #d7ba7d",
  },
});

export interface EditorVariable {
  key: string;
  detail?: string;
}

/** Suggests variable references (already in the shell's syntax) on $, %, os.environ or Ctrl+Space. */
function variableCompletions(shell: Shell, variables: EditorVariable[]): CompletionSource {
  return (ctx: CompletionContext) => {
    const word = ctx.matchBefore(/(\$\{?|\$env:|%|os\.environ\[['"]?)?[A-Za-z_0-9]*$/);
    if (!word) return null;
    const hasPrefix = /^(\$|%|os\.environ\[)/.test(word.text);
    if (!hasPrefix && !ctx.explicit) return null;
    return {
      from: word.from,
      options: variables.map((v) => ({
        label: varReference(shell, v.key),
        detail: v.detail,
        type: "variable",
        boost: v.key.startsWith("RTS_") ? -1 : 0,
      })),
    };
  };
}

export interface CommandEditorHandle {
  /** Inserts the reference to a variable at the cursor, in the shell's syntax. */
  insertVariable: (key: string) => void;
}

export const CommandEditor = forwardRef<
  CommandEditorHandle,
  {
    value: string;
    onChange: (value: string) => void;
    shell: Shell;
    variables: EditorVariable[];
    id?: string;
  }
>(function CommandEditor({ value, onChange, shell, variables, id }, ref) {
  const cm = useRef<ReactCodeMirrorRef>(null);
  // Until the user places the cursor, inserting goes to the end (not to position 0).
  const touched = useRef(false);
  const variablesKey = JSON.stringify(variables);

  const extensions = useMemo(
    () => [
      language(shell),
      variableHighlighter(shell, new Set(variables.map((v) => v.key))),
      autocompletion({ override: [variableCompletions(shell, variables)] }),
      editorTheme,
      EditorView.lineWrapping,
      EditorView.updateListener.of((update) => {
        if (update.view.hasFocus && (update.selectionSet || update.focusChanged)) {
          touched.current = true;
        }
      }),
    ],
    // variablesKey captures the variables by value
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [shell, variablesKey],
  );

  useImperativeHandle(ref, () => ({
    insertVariable(key: string) {
      const view = cm.current?.view;
      const text = varReference(shell, key);
      if (!view) {
        onChange(value + text);
        return;
      }
      if (touched.current) {
        view.dispatch(view.state.replaceSelection(text));
      } else {
        const end = view.state.doc.length;
        const before = end > 0 && !/\s$/.test(view.state.doc.toString()) ? " " : "";
        view.dispatch({
          changes: { from: end, insert: before + text },
          selection: { anchor: end + before.length + text.length },
        });
      }
      touched.current = true;
      view.focus();
    },
  }));

  return (
    <div className="overflow-hidden rounded-md ring-1 ring-slate-700" data-testid="command-editor">
      <div className="flex items-center justify-between bg-[#2d2d2d] px-3 py-1 text-[11px] text-slate-300">
        <span>
          <span className="mr-1.5 inline-block size-2 rounded-full bg-[#4ec9b0]" />
          {shell}
        </span>
        <span className="text-slate-400">Ctrl+Espaço sugere variáveis · Ctrl+Z desfaz</span>
      </div>
      <CodeMirror
        ref={cm}
        id={id}
        value={value}
        onChange={onChange}
        theme={vscodeDark}
        extensions={extensions}
        minHeight="160px"
        maxHeight="480px"
        basicSetup={{ highlightActiveLine: true, foldGutter: false, autocompletion: false }}
        aria-label="Comando ou script"
      />
    </div>
  );
});
