import { ArrowDownToLine } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { LogChunk } from "../../api/types";
import { cx } from "../../components/ui";

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
      <pre
        ref={ref}
        onScroll={onScroll}
        data-testid="log-viewer"
        className="h-[28rem] overflow-auto rounded-lg bg-slate-900 p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap break-all"
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
