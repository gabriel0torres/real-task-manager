import { ArrowDownToLine, Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { LogChunk } from "../../api/types";
import { cx } from "../../components/ui";
import { copyText } from "../../lib/clipboard";

const STREAM_CLASS = {
  stdout: "text-slate-100",
  stderr: "text-red-300",
  system: "text-sky-300",
} as const;

export function LogViewer({
  chunks,
  live,
  emptyText = "Sem saída até o momento.",
}: {
  chunks: LogChunk[];
  live?: boolean;
  emptyText?: string;
}) {
  const ref = useRef<HTMLPreElement>(null);
  const [follow, setFollow] = useState(true);
  const [copyState, setCopyState] = useState<"idle" | "done" | "error">("idle");

  const copy = async () => {
    try {
      await copyText(chunks.map((c) => c.content).join(""));
      setCopyState("done");
    } catch {
      setCopyState("error");
    }
    setTimeout(() => setCopyState("idle"), 2000);
  };

  useEffect(() => {
    const el = ref.current;
    if (el && follow) el.scrollTop = el.scrollHeight;
  }, [chunks, follow]);

  const onScroll = () => {
    const el = ref.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    setFollow(atBottom);
  };

  return (
    <div className="relative">
      {chunks.length > 0 && (
        <button
          type="button"
          onClick={copy}
          aria-label="Copiar log"
          className={cx(
            "absolute top-2 right-5 z-10 inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium ring-1 transition-colors",
            copyState === "done"
              ? "bg-emerald-600 text-white ring-emerald-500"
              : copyState === "error"
                ? "bg-red-600 text-white ring-red-500"
                : "bg-slate-800/90 text-slate-200 ring-slate-600 hover:bg-slate-700",
          )}
        >
          {copyState === "done" ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copyState === "done" ? "Copiado!" : copyState === "error" ? "Não foi possível copiar" : "Copiar log"}
        </button>
      )}
      <pre
        ref={ref}
        onScroll={onScroll}
        data-testid="log-viewer"
        className={cx(
          "h-[28rem] overflow-auto rounded-lg bg-slate-900 p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap break-all",
          chunks.length > 0 && "pt-11",
        )}
      >
        {chunks.length === 0 && <span className="text-slate-500">{emptyText}</span>}
        {chunks.map((chunk) => (
          <span key={chunk.seq} className={STREAM_CLASS[chunk.stream]} data-stream={chunk.stream}>
            {chunk.content}
          </span>
        ))}
        {live && <span className="inline-block h-3.5 w-1.5 animate-pulse bg-slate-400 align-middle" />}
      </pre>
      {!follow && (
        <button
          type="button"
          onClick={() => setFollow(true)}
          className={cx(
            "absolute right-4 bottom-4 inline-flex items-center gap-1 rounded-full bg-indigo-600 px-3 py-1 text-xs text-white shadow",
          )}
        >
          <ArrowDownToLine className="size-3.5" /> Acompanhar
        </button>
      )}
      <div className="mt-2 flex gap-4 text-xs text-slate-500">
        <span><span className="mr-1 inline-block size-2 rounded-full bg-slate-400" />saída padrão</span>
        <span><span className="mr-1 inline-block size-2 rounded-full bg-red-400" />erros (stderr)</span>
        <span><span className="mr-1 inline-block size-2 rounded-full bg-sky-400" />mensagens do RTS</span>
      </div>
    </div>
  );
}
