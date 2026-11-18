import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { API_BASE } from "../../api/client";
import type { LogChunk, RunStatus } from "../../api/types";

interface StreamState {
  chunks: LogChunk[];
  status: RunStatus | null;
  ended: boolean;
  error: boolean;
}

/** Live log via Server-Sent Events; EventSource resumes with Last-Event-ID on reconnect. */
export function useRunLogStream(runId: number): StreamState {
  const client = useQueryClient();
  const [state, setState] = useState<StreamState>({ chunks: [], status: null, ended: false, error: false });

  useEffect(() => {
    setState({ chunks: [], status: null, ended: false, error: false });
    const source = new EventSource(`${API_BASE}/runs/${runId}/log/stream`);

    source.addEventListener("log", (event) => {
      const chunk = JSON.parse((event as MessageEvent).data) as LogChunk;
      setState((s) =>
        s.chunks.length && s.chunks[s.chunks.length - 1].seq >= chunk.seq
          ? s
          : { ...s, chunks: [...s.chunks, chunk], error: false },
      );
    });
    source.addEventListener("status", (event) => {
      const { status } = JSON.parse((event as MessageEvent).data) as { status: RunStatus };
      setState((s) => ({ ...s, status }));
      client.invalidateQueries({ queryKey: ["runs"] });
    });
    source.addEventListener("end", () => {
      source.close();
      setState((s) => ({ ...s, ended: true }));
      client.invalidateQueries();
    });
    source.onerror = () => setState((s) => (s.ended ? s : { ...s, error: true }));

    return () => source.close();
  }, [runId, client]);

  return state;
}
