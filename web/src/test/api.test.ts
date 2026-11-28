import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, clearToken, messageFor, setToken, token, whenSignedOut } from "../api";

function respond(status: number, body: unknown) {
  // A fresh Response per call: a body can be read only once.
  return vi.fn((_url: string, _init?: RequestInit & { headers: Record<string, string> }) => Promise.resolve(new Response(status === 204 ? null : JSON.stringify(body), { status })));
}

describe("api", () => {
  beforeEach(() => clearToken());
  afterEach(() => vi.unstubAllGlobals());

  it("sends the token, a fresh Idempotency-Key on writes and If-Match for updates", async () => {
    const fetch = respond(200, { ok: true });
    vi.stubGlobal("fetch", fetch);
    setToken("tok");
    await api("/v1/x", { body: { a: 1 }, version: 3 });
    await api("/v1/x", { body: { a: 1 } });
    const [url, init] = fetch.mock.calls[0]!;
    if (!init) throw new Error("no request options");
    expect(url).toBe("/v1/x");
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBe("Bearer tok");
    expect(init.headers["If-Match"]).toBe('"3"');
    expect(init.body).toBe('{"a":1}');
    const second = fetch.mock.calls[1]![1]!.headers["Idempotency-Key"];
    expect(init.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(second).not.toBe(init.headers["Idempotency-Key"]); // a new submission, a new key
  });

  it("reuses a key when the same submission is retried, and reads never carry one", async () => {
    const fetch = respond(200, {});
    vi.stubGlobal("fetch", fetch);
    await api("/v1/x", { body: {}, key: "k-1" });
    await api("/v1/y", { query: { q: "a b", limit: 5, empty: "", none: undefined } });
    expect(fetch.mock.calls[0]![1]!.headers["Idempotency-Key"]).toBe("k-1");
    expect(fetch.mock.calls[1]![0]).toBe("/v1/y?q=a+b&limit=5");
    expect(fetch.mock.calls[1]![1]!.headers["Idempotency-Key"]).toBeUndefined();
    expect(fetch.mock.calls[1]![1]!.headers.Authorization).toBeUndefined();
  });

  it("turns API errors into ApiError with a readable message", async () => {
    vi.stubGlobal("fetch", respond(409, { error: { code: "stale_version", message: "expected 1", correlation_id: "c1" } }));
    const e = (await api("/v1/x").catch((x) => x)) as ApiError;
    expect(e).toBeInstanceOf(ApiError);
    expect([e.status, e.code, e.correlationId]).toEqual([409, "stale_version", "c1"]);
    expect(messageFor(e)).toMatch(/Someone changed this/);
    vi.stubGlobal("fetch", respond(422, { error: { code: "owner_required", message: "every outstanding item needs a named owner" } }));
    expect(messageFor(await api("/v1/x").catch((x) => x))).toBe("every outstanding item needs a named owner");
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("oops", { status: 500, statusText: "Server Error" }))));
    const plain = (await api("/v1/x").catch((x) => x)) as ApiError;
    expect([plain.code, plain.message]).toEqual(["error", "Server Error"]);
  });

  it("names the fields that need attention", () => {
    const e = new ApiError(422, "invalid_input", "invalid fields: body.birth_date, body.identifiers.0.value, body");
    expect(messageFor(e)).toBe("Check birth date, identifiers value.");
    expect(messageFor(new ApiError(422, "invalid_input", "invalid fields: body"))).toBe("Some fields need attention.");
    expect(messageFor(new ApiError(422, "invalid_input", "bad"))).toBe("Some fields need attention.");
  });

  it("ends the session on 401 and reports an unreachable service", async () => {
    const ended = vi.fn();
    whenSignedOut(ended);
    setToken("old");
    vi.stubGlobal("fetch", respond(401, { error: { code: "unauthenticated", message: "invalid token" } }));
    await api("/v1/me").catch(() => undefined);
    expect(ended).toHaveBeenCalledOnce();
    expect(token()).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const e = (await api("/v1/me").catch((x) => x)) as ApiError;
    expect(e.code).toBe("network");
    expect(messageFor(new Error("x"))).toMatch(/could not be reached/);
  });

  it("returns a file's bytes as a blob", async () => {
    const fetch = vi.fn(() => Promise.resolve(new Response("%PDF-1.7", { status: 200 })));
    vi.stubGlobal("fetch", fetch);
    const blob = await api<Blob>("/v1/documents/d/content", { as: "blob" });
    expect(await blob.text()).toBe("%PDF-1.7");
    expect((fetch.mock.calls[0] as unknown as [string, RequestInit & { headers: Record<string, string> }])[1].headers.Accept).toBe("*/*");
  });

  it("returns nothing for 204", async () => {
    vi.stubGlobal("fetch", respond(204, null));
    expect(await api("/v1/x", { method: "POST" })).toBeUndefined();
  });
});
