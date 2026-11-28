/**
 * The one way the app talks to the API (/v1, same origin).
 *
 * - The access token is kept in sessionStorage: a reload keeps you signed in for
 *   this tab, closing the tab forgets it. It is never put in a URL or a log.
 * - Every write carries a fresh Idempotency-Key, so retrying after a dropped
 *   connection cannot do the work twice.
 * - Updates send If-Match with the version the screen was showing, so a change
 *   someone else made in the meantime is refused rather than overwritten.
 * - Errors become ApiError with the API's stable code and a sentence for the
 *   screen. A 401 ends the session.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: unknown = undefined,
    readonly correlationId: string | undefined = undefined,
  ) {
    super(message);
  }
}

const TOKEN_KEY = "astemia.token";
let memory: string | null = null;
let onSignedOut: () => void = () => {};

function store(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    store()?.setItem(TOKEN_KEY, token);
  } catch {
    /* storage blocked: the session lasts until reload */
  }
  memory = token;
}

export function token(): string | null {
  return memory ?? store()?.getItem(TOKEN_KEY) ?? null;
}

export function clearToken(): void {
  memory = null;
  try {
    store()?.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export function whenSignedOut(fn: () => void): void {
  onSignedOut = fn;
}

export function newKey(): string {
  return crypto.randomUUID();
}

/** Readable sentences for the API's stable error codes; anything else uses its message. */
const MESSAGES: Record<string, string> = {
  not_found: "Not found, or you do not have access to it.",
  stale_version: "Someone changed this while you were looking at it. Reload to see the latest.",
  precondition_required: "Reload the page and try again.",
  idempotency_key_reused: "This was already submitted with different content.",
  invalid_input: "Some fields need attention.",
  unauthenticated: "Your session has ended. Sign in again.",
  missing_capability: "Your role does not allow this.",
};

export function messageFor(e: unknown): string {
  if (e instanceof ApiError && e.code === "invalid_input" && e.message.startsWith("invalid fields: ")) {
    // "invalid fields: body.birth_date, body.identifiers.0.value" → "birth date, identifiers value"
    const fields = e.message
      .slice("invalid fields: ".length)
      .split(", ")
      .map((f) => f.replace(/^(body|query|path|header)\.?/, "").replace(/\.\d+/g, "").replaceAll(".", " ").replaceAll("_", " ").trim())
      .filter(Boolean);
    return fields.length ? `Check ${[...new Set(fields)].join(", ")}.` : (MESSAGES.invalid_input as string);
  }
  if (e instanceof ApiError) return MESSAGES[e.code] ?? e.message;
  return "The service could not be reached. Check the connection and try again.";
}

type Query = Record<string, string | number | boolean | undefined | null>;

export interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  query?: Query;
  /** The version being changed, sent as If-Match. */
  version?: number;
  /** Reuse a key when retrying the same submission. */
  key?: string;
  signal?: AbortSignal;
}

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `${path}?${s}` : path;
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? (opts.body === undefined ? "GET" : "POST");
  const headers: Record<string, string> = { Accept: "application/json" };
  const t = token();
  if (t) headers.Authorization = `Bearer ${t}`;
  if (method === "POST") {
    headers["Content-Type"] = "application/json";
    headers["Idempotency-Key"] = opts.key ?? newKey();
  }
  if (opts.version !== undefined) headers["If-Match"] = `"${opts.version}"`;
  let r: Response;
  try {
    r = await fetch(withQuery(path, opts.query), {
      method,
      headers,
      body: method === "POST" ? JSON.stringify(opts.body ?? {}) : undefined,
      signal: opts.signal,
      credentials: "same-origin",
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "network", "The service could not be reached.");
  }
  if (r.status === 401 && t) {
    clearToken();
    onSignedOut();
  }
  if (!r.ok) {
    let body: { error?: { code?: string; message?: string; details?: unknown; correlation_id?: string } } = {};
    try {
      body = await r.json();
    } catch {
      /* not JSON */
    }
    const err = body.error ?? {};
    throw new ApiError(r.status, err.code ?? "error", err.message ?? r.statusText, err.details, err.correlation_id);
  }
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}
