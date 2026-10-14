import { useEffect } from "react";
import { useScenarios } from "../api/hooks";
import { useUi } from "../store/ui";
import { inputCls } from "./ui";

/** Global scenario selector (header). Auto-selects the first scenario when none is chosen. */
export function ScenarioPicker() {
  const { data, isLoading } = useScenarios();
  const { scenarioId, setScenario } = useUi();
  const items = data?.items ?? [];
  useEffect(() => {
    if (!items.length) return;
    if (!scenarioId || !items.some((s) => s.id === scenarioId)) setScenario(items[0].id);
  }, [items, scenarioId, setScenario]);
  if (isLoading) return <span className="text-xs text-ink-400">시나리오 로딩…</span>;
  if (!items.length) return <span className="text-xs text-amber-700">시나리오 없음 — 시나리오 화면에서 생성/시드하세요</span>;
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="hidden text-ink-600 lg:inline">시나리오</span>
      <select
        aria-label="시나리오 선택"
        className={`${inputCls} max-w-[16rem] py-1`}
        value={scenarioId ?? ""}
        onChange={(e) => setScenario(Number(e.target.value))}
      >
        {items.map((s) => (
          <option key={s.id} value={s.id}>
            #{s.id} {s.name} ({s.order_count}건)
          </option>
        ))}
      </select>
    </label>
  );
}

export function useSelectedScenario() {
  const scenarioId = useUi((s) => s.scenarioId);
  const { data } = useScenarios();
  return data?.items.find((s) => s.id === scenarioId) ?? null;
}
