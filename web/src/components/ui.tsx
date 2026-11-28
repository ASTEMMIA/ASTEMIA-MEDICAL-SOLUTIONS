import {
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

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

interface Labelled {
  label: string;
  hint?: string;
  error?: string;
}

/** Label, hint and error around one control, wired with aria-describedby (WCAG 1.3.1, 3.3.1). */
function Wrap({ label, hint, error, control }: Labelled & { control: (a11y: Record<string, unknown>) => ReactNode }) {
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
      {control({
        id,
        "aria-invalid": error ? true : undefined,
        "aria-describedby": [hintId, errorId].filter(Boolean).join(" ") || undefined,
      })}
    </div>
  );
}

/** A labelled text input with optional hint and error. */
export function Field({ label, hint, error, ...input }: InputHTMLAttributes<HTMLInputElement> & Labelled) {
  return <Wrap label={label} hint={hint} error={error} control={(a) => <input {...a} {...input} />} />;
}

export function TextArea({ label, hint, error, ...input }: TextareaHTMLAttributes<HTMLTextAreaElement> & Labelled) {
  return <Wrap label={label} hint={hint} error={error} control={(a) => <textarea rows={3} {...a} {...input} />} />;
}

export function Select({
  label,
  hint,
  error,
  options,
  placeholder,
  ...input
}: SelectHTMLAttributes<HTMLSelectElement> & Labelled & { options: [string, string][]; placeholder?: string }) {
  return (
    <Wrap
      label={label}
      hint={hint}
      error={error}
      control={(a) => (
        <select {...a} {...input}>
          {placeholder !== undefined && <option value="">{placeholder}</option>}
          {options.map(([value, text]) => (
            <option key={value} value={value}>
              {text}
            </option>
          ))}
        </select>
      )}
    />
  );
}

/** A group of radio buttons with a legend. */
export function Radios({
  legend,
  name,
  value,
  options,
  onChange,
}: {
  legend: string;
  name: string;
  value: string;
  options: [string, ReactNode][];
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <fieldset className="radios">
      <legend>{legend}</legend>
      {options.map(([v, text]) => (
        <div className="radio" key={v}>
          <input type="radio" id={`${id}-${v}`} name={name} value={v} checked={value === v} onChange={() => onChange(v)} />
          <label htmlFor={`${id}-${v}`}>{text}</label>
        </div>
      ))}
    </fieldset>
  );
}

/** A titled part of a page, with an optional action beside the heading. */
export function Section({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  const id = useId();
  return (
    <section className="section" aria-labelledby={id}>
      <div className="section-head">
        <h2 id={id}>{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

/** A short status word, never conveyed by colour alone (WCAG 1.4.1). */
export function Tag({ tone = "neutral", children }: { tone?: "neutral" | "good" | "warn" | "bad"; children: ReactNode }) {
  return <span className={`tag tag-${tone}`}>{children}</span>;
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
