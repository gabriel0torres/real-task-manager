export const API_BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface PydanticError {
  loc?: (string | number)[];
  msg: string;
}

/** Turn FastAPI/Pydantic error bodies into a readable pt-BR message. */
export function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return (detail as PydanticError[])
        .map((e) => {
          const msg = e.msg.replace(/^Value error, /, "");
          const field = e.loc?.filter((p) => p !== "body").join(".");
          return field ? `${field}: ${msg}` : msg;
        })
        .join("\n");
    }
  }
  return `Erro ${status} ao comunicar com o servidor.`;
}

/** Fired when the session expires so the app can show the login screen. */
export const UNAUTHORIZED_EVENT = "rts:unauthorized";

export function notifyUnauthorized() {
  window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.json();
    } catch {
      /* non-JSON error */
    }
    if (response.status === 401 && !path.startsWith("/auth/")) notifyUnauthorized();
    throw new ApiError(response.status, errorMessage(parsed, response.status));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  del: (path: string) => request<void>("DELETE", path),
};

export function query(params: Record<string, string | number | string[] | null | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v));
    else search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
