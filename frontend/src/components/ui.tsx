/** Small accessible UI primitives (Tailwind). Kept dependency-free on purpose. */
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { ApiError } from "../api/client";

export function cx(...c: (string | false | null | undefined)[]): string {
  return c.filter(Boolean).join(" ");
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" };
export function Button({ variant = "primary", className, ...rest }: BtnProps) {
  const v = {
    primary: "bg-accent-600 text-white hover:bg-accent-500 disabled:bg-ink-200 disabled:text-ink-400",
    secondary: "bg-white text-ink-800 border border-ink-200 hover:bg-ink-50 disabled:text-ink-400",
    danger: "bg-red-600 text-white hover:bg-red-500 disabled:bg-ink-200",
    ghost: "text-ink-600 hover:bg-ink-100",
  }[variant];
  return (
    <button
      className={cx(
        "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 disabled:cursor-not-allowed",
        v,
        className,
      )}
      {...rest}
    />
  );
}

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-lg border border-ink-200 bg-white shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-ink-100 px-4 py-2.5">
          <h2 className="text-sm font-semibold text-ink-800">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

const BADGE: Record<string, string> = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  red: "bg-red-50 text-red-700 ring-red-600/20",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/20",
  blue: "bg-blue-50 text-blue-700 ring-blue-600/20",
  gray: "bg-ink-50 text-ink-600 ring-ink-400/30",
  violet: "bg-violet-50 text-violet-700 ring-violet-600/20",
};
export function Badge({ color = "gray", children, title }: { color?: keyof typeof BADGE; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset", BADGE[color])}>
      {children}
    </span>
  );
}

export function statusColor(s: string | undefined | null): keyof typeof BADGE {
  switch (s) {
    case "SUCCEEDED":
    case "FEASIBLE":
    case "OPTIMAL":
    case "ok":
      return "green";
    case "FAILED":
    case "INFEASIBLE":
    case "ERROR":
      return "red";
    case "RUNNING":
    case "QUEUED":
      return "blue";
    case "TIME_LIMIT":
    case "CANCELLED":
      return "amber";
    default:
      return "gray";
  }
}

export function Spinner({ label = "불러오는 중…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 py-6 text-sm text-ink-600">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-200 border-t-accent-600" />
      {label}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const e = error as ApiError | Error;
  const code = e instanceof ApiError ? e.code : "client_error";
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      <div className="font-medium">오류: {e?.message ?? String(error)}</div>
      <div className="mt-0.5 text-xs text-red-700">
        code={code}
        {e instanceof ApiError && e.requestId ? ` · request_id=${e.requestId}` : ""}
      </div>
      {onRetry && (
        <Button variant="secondary" className="mt-2" onClick={onRetry}>
          다시 시도
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-dashed border-ink-200 p-6 text-center text-sm text-ink-400">{children}</div>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-ink-900">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-ink-600">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-ink-800">{label}</span>
      {children}
      {hint && <span className="mt-0.5 block text-xs text-ink-400">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "w-full rounded-md border border-ink-200 bg-white px-2.5 py-1.5 text-sm text-ink-900 focus:border-accent-500 focus:outline-none focus:ring-1 focus:ring-accent-500";

export function Kpi({ label, value, unit, hint }: { label: string; value: ReactNode; unit?: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-ink-200 bg-white p-3 shadow-sm" title={hint}>
      <div className="text-xs font-medium text-ink-600">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-ink-900">
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-ink-400">{unit}</span>}
      </div>
      {hint && <div className="mt-0.5 truncate text-xs text-ink-400">{hint}</div>}
    </div>
  );
}
