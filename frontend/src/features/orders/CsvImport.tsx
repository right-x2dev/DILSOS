import type { Scenario } from "../../types/api";

/** CSV import UI — implemented in Phase 7 (backend POST /imports/orders). Explicitly disabled until then. */
export function CsvImport(_props: { sc: Scenario }) {
  return (
    <div className="space-y-2 text-sm">
      <button disabled className="cursor-not-allowed rounded-md border border-ink-200 px-3 py-1.5 text-ink-400" title="Phase 7에서 구현 예정">
        CSV 파일 선택 (준비 중)
      </button>
      <p className="text-xs text-ink-400">Phase 7에서 구현 예정 — 현재 이 컨트롤은 동작하지 않습니다.</p>
    </div>
  );
}
