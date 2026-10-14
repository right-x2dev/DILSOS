import type { Run } from "../../types/api";

/** Run export (CSV/JSON) — backend GET /exports/runs/{id} lands in Phase 7; disabled until then. */
export function ExportButtons(_props: { run: Run }) {
  return (
    <span className="flex gap-1">
      <button disabled title="Phase 7에서 구현 예정" className="cursor-not-allowed rounded border border-ink-200 px-2 py-0.5 text-xs text-ink-400">
        CSV (준비 중)
      </button>
      <button disabled title="Phase 7에서 구현 예정" className="cursor-not-allowed rounded border border-ink-200 px-2 py-0.5 text-xs text-ink-400">
        JSON (준비 중)
      </button>
    </span>
  );
}
