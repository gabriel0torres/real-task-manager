import { AlertTriangle, HelpCircle } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";

import { Button, cx } from "./ui";

export interface ConfirmOptions {
  title: string;
  /** Body: text or JSX (paragraphs, lists of affected items...). */
  message?: ReactNode;
  confirmLabel?: string;
  /** Default "Voltar" (never ambiguous next to actions like "Cancelar sequência"). */
  cancelLabel?: string;
  /** "danger": red button, focus starts on "Voltar"; "primary": focus on the action. */
  tone?: "danger" | "primary";
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Confirm | null>(null);

/**
 * Styled replacement for window.confirm: ``if (!(await confirm({...}))) return;``.
 * Without a provider (shouldn't happen) it falls back to the browser dialog.
 */
export function useConfirm(): Confirm {
  const context = useContext(ConfirmContext);
  return context ?? ((options) => Promise.resolve(window.confirm(options.title)));
}

interface Pending {
  options: ConfirmOptions;
  resolve: (answer: boolean) => void;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null);

  const confirm = useCallback<Confirm>(
    (options) =>
      new Promise<boolean>((resolve) => {
        setPending((current) => {
          current?.resolve(false); // a new question replaces an unanswered one
          return { options, resolve };
        });
      }),
    [],
  );

  const answer = (value: boolean) => {
    pending?.resolve(value);
    setPending(null);
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && <ConfirmDialog options={pending.options} onAnswer={answer} />}
    </ConfirmContext.Provider>
  );
}

function ConfirmDialog({ options, onAnswer }: { options: ConfirmOptions; onAnswer: (value: boolean) => void }) {
  const danger = options.tone === "danger";
  const titleId = useId();
  const bodyId = useId();
  const confirmButton = useRef<HTMLButtonElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    (danger ? cancelButton : confirmButton).current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onAnswer(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [danger, onAnswer]);

  const Icon = danger ? AlertTriangle : HelpCircle;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 pt-[12vh]"
      onMouseDown={(e) => e.target === e.currentTarget && onAnswer(false)}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={options.message ? bodyId : undefined}
        className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl ring-1 ring-slate-200"
      >
        <div className="flex gap-3">
          <span
            className={cx(
              "flex size-9 shrink-0 items-center justify-center rounded-full",
              danger ? "bg-red-100 text-red-600" : "bg-indigo-100 text-indigo-600",
            )}
          >
            <Icon className="size-5" aria-hidden />
          </span>
          <div className="min-w-0 flex-1 space-y-2">
            <h2 id={titleId} className="text-base font-semibold text-slate-900">
              {options.title}
            </h2>
            {options.message && (
              <div id={bodyId} className="space-y-2 text-sm text-slate-600">
                {options.message}
              </div>
            )}
          </div>
        </div>
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <Button ref={cancelButton} onClick={() => onAnswer(false)}>
            {options.cancelLabel ?? "Voltar"}
          </Button>
          <Button ref={confirmButton} variant={danger ? "dangerSolid" : "primary"} onClick={() => onAnswer(true)}>
            {options.confirmLabel ?? "Confirmar"}
          </Button>
        </div>
      </div>
    </div>
  );
}

/** A short list inside a confirmation (e.g. the tasks affected), scrollable when long. */
export function ConfirmList({ items }: { items: string[] }) {
  return (
    <ul className="max-h-40 list-disc space-y-0.5 overflow-y-auto rounded-md bg-slate-50 py-2 pr-2 pl-7 text-slate-700 ring-1 ring-slate-200">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}
