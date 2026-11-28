import { useEffect, useId, useRef, type ReactNode, type ButtonHTMLAttributes, type InputHTMLAttributes } from "react";

/**
 * A page: one h1 that takes focus when the page opens, so keyboard and
 * screen-reader users land at its start (WCAG 2.4.3).
 */
export function Page({ title, intro, children }: { title: string; intro?: ReactNode; children?: ReactNode }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = `${title} · ASTEMIA Health`;
    heading.current?.focus();
  }, [title]);
  return (
    <>
      <h1 ref={heading} tabIndex={-1}>
        {title}
      </h1>
      {intro && <p className="intro">{intro}</p>}
      {children}
    </>
  );
}

export function Button({ variant = "primary", busy = false, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger"; busy?: boolean }) {
  return (
    <button className={`btn btn-${variant}`} aria-busy={busy || undefined} disabled={busy || rest.disabled} {...rest}>
      {children}
    </button>
  );
}

/** A labelled field with optional hint and error, wired with aria-describedby. */
export function Field({ label, hint, error, ...input }: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string; error?: string }) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  return (
    <div className={`field${error ? " field-error" : ""}`}>
      <label htmlFor={id}>{label}</label>
      {hint && (
        <p className="hint" id={hintId}>
          {hint}
        </p>
      )}
      {error && (
        <p className="error-text" id={errorId}>
          {error}
        </p>
      )}
      <input id={id} aria-invalid={error ? true : undefined} aria-describedby={[hintId, errorId].filter(Boolean).join(" ") || undefined} {...input} />
    </div>
  );
}

/** A message that is announced: role="alert" for problems, role="status" for news. */
export function Notice({ kind = "info", children }: { kind?: "info" | "success" | "error" | "warning"; children: ReactNode }) {
  return (
    <div className={`notice notice-${kind}`} role={kind === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <p className="loading" role="status" aria-live="polite">
      {what}…
    </p>
  );
}
