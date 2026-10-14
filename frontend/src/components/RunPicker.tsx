import { useEffect } from "react";
import { useRuns } from "../api/hooks";
import { useUi } from "../store/ui";
import { inputCls } from "./ui";

/** Picks a SUCCEEDED run of the selected scenario whose problem type is in `types`. */
export function RunPicker({ types, label = "실행(run)", value, onChange }: { types: string[]; label?: string; value?: number | null; onChange?: (id: number | null) => void }) {
  const scenarioId = useUi((s) => s.scenarioId);
  const globalRun = useUi((s) => s.runId);
  const setRun = useUi((s) => s.setRun);
  const { data, isLoading } = useRuns(scenarioId, { status: "SUCCEEDED" });
  const runs = (data?.items ?? []).filter((r) => types.includes(r.problem_type));
  const current = value !== undefined ? value : globalRun;
  const set = onChange ?? setRun;
  useEffect(() => {
    if (value !== undefined) return;
    if (runs.length && !runs.some((r) => r.id === current)) set(runs[0].id);
  }, [runs, current, set, value]);
  if (isLoading) return <span className="text-xs text-ink-400">실행 목록 로딩…</span>;
  if (!runs.length)
    return <span className="text-xs text-amber-700">이 유형({types.join("/")})의 검증 완료 실행이 없습니다 — 최적화 실행 화면에서 먼저 실행하세요</span>;
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-ink-600">{label}</span>
      <select aria-label={label} className={`${inputCls} max-w-[22rem] py-1`} value={current ?? ""} onChange={(e) => set(e.target.value ? Number(e.target.value) : null)}>
        {!runs.some((r) => r.id === current) && <option value="">선택…</option>}
        {runs.map((r) => (
          <option key={r.id} value={r.id}>
            #{r.id} {r.algorithm} · {r.problem_type} · v{r.schedule_version} · {r.solver_status}
          </option>
        ))}
      </select>
    </label>
  );
}
