import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "../components/Toast";

export function renderWithProviders(ui: ReactElement, { route = "/" } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <ToastProvider>{ui}</ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

type Handler = (init: RequestInit | undefined, url: URL) => unknown;

/**
 * Stub global fetch with "METHOD /path" handlers. A handler returns the JSON body,
 * or a Response for custom statuses. Returns the mock to inspect calls.
 */
export function mockApi(handlers: Record<string, Handler>) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url.pathname.replace("/api/v1", "")}`;
    const handler = handlers[key];
    if (!handler) return new Response(JSON.stringify({ detail: `no mock for ${key}` }), { status: 500 });
    const result = handler(init, url);
    if (result instanceof Response) return result;
    if (result === undefined) return new Response(null, { status: 204 });
    return new Response(JSON.stringify(result), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

export function bodyOf(mock: ReturnType<typeof mockApi>, key: string): unknown {
  const call = mock.mock.calls.find(([input, init]) => {
    const url = new URL(String(input), "http://localhost");
    return `${(init?.method ?? "GET").toUpperCase()} ${url.pathname.replace("/api/v1", "")}` === key;
  });
  return call?.[1]?.body ? JSON.parse(String(call[1].body)) : undefined;
}
