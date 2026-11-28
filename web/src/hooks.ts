import { useCallback, useEffect, useRef, useState } from "react";
import { api, messageFor, newKey, type RequestOptions } from "./api";

export interface Loaded<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/** GET a resource when the path or query changes; a null path loads nothing. */
export function useLoad<T>(path: string | null, query?: RequestOptions["query"]): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(path !== null);
  const [tick, setTick] = useState(0);
  const q = JSON.stringify(query ?? {});
  useEffect(() => {
    if (path === null) {
      setData(null);
      setLoading(false);
      return;
    }
    const abort = new AbortController();
    setLoading(true);
    setError(null);
    api<T>(path, { query: JSON.parse(q) as RequestOptions["query"], signal: abort.signal })
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (abort.signal.aborted) return;
        setError(e);
        setLoading(false);
      });
    return () => abort.abort();
  }, [path, q, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

export interface Action<A extends unknown[], R> {
  run: (...args: A) => Promise<R | undefined>;
  busy: boolean;
  error: string | null;
  clear: () => void;
}

/**
 * A write. One Idempotency-Key per submission: a retry after a failure or a
 * double click sends the same key, so the server applies it once (API-02).
 * The key is renewed only after a success.
 */
export function useAction<A extends unknown[], R>(fn: (key: string, ...args: A) => Promise<R>): Action<A, R> {
  const key = useRef(newKey());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(
    async (...args: A) => {
      setBusy(true);
      setError(null);
      try {
        const result = await fn(key.current, ...args);
        key.current = newKey();
        return result;
      } catch (e) {
        setError(messageFor(e));
        return undefined;
      } finally {
        setBusy(false);
      }
    },
    [fn],
  );
  return { run, busy, error, clear: () => setError(null) };
}
