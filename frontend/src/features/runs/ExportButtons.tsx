import { useState } from "react";
import { downloadFile } from "../../api/client";
import type { Run } from "../../types/api";

/** GET /exports/runs/{id}?format=csv|json — only validated (SUCCEEDED) schedules are exportable. */
export function ExportButtons({ run }: { run: Run }) {
  const [err, setErr] = useState<string | null>(null);
  const disabled = run.status !== "SUCCEEDED";
  const get = (fmt: "csv" | "json") =>
    downloadFile(`/exports/runs/${run.id}?format=${fmt}`, `dilsos_run_${run.id}.${fmt}`).catch((e: Error) => setErr(e.message));
  return (
    <span className="flex items-center gap-1">
      {(["csv", "json"] as const).map((f) => (
        <button
          key={f}
          onClick={() => get(f)}
          disabled={disabled}
          title={disabled ? "검증 통과(SUCCEEDED) 실행만 내보낼 수 있습니다" : `${f.toUpperCase()} 내보내기`}
          className="rounded border border-ink-200 px-2 py-0.5 text-xs text-ink-800 hover:bg-ink-50 disabled:cursor-not-allowed disabled:text-ink-400"
        >
          {f.toUpperCase()}
        </button>
      ))}
      {err && <span className="text-xs text-red-700">{err}</span>}
    </span>
  );
}
