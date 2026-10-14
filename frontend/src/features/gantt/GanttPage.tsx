import { useMemo, useState } from "react";
import { useSchedule } from "../../api/hooks";
import { RunPicker } from "../../components/RunPicker";
import { LegendDot, Timeline, ZoomControl, type Bar, type Lane, type Link } from "../../components/Timeline";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Spinner, inputCls } from "../../components/ui";
import { useUi } from "../../store/ui";
import type { Schedule } from "../../types/api";
import { clock } from "../../utils/time";

const KIND_KO: Record<string, string> = { worker: "작업자", pack_station: "포장대", equipment: "장비" };
export const TASK_COLOR = { PICK: "#2563eb", PACK: "#059669", LOAD: "#d97706" } as const;

/** Build lanes/bars for warehouse resources from a schedule (shared with the reschedule diff view). */
export function warehouseBars(s: Schedule, kinds: Set<string>, focus: string, compareTo?: Schedule | null) {
  const tz = s.timezone;
  const hs = s.horizon_start;
  const om = new Map(s.orders.map((o) => [o.id, o]));
  const lanes: Lane[] = s.resources
    .filter((r) => r.kind !== "dock" && kinds.has(r.kind))
    .map((r) => ({
      id: r.id,
      label: `${r.id} ${KIND_KO[r.kind] ?? r.kind}`,
      sublabel: r.kind === "worker" ? `기술: ${r.skills.join(",")}` : r.name,
      available: r.available,
    }));
  const laneSet = new Set(lanes.map((l) => l.id));
  const packEnd = new Map<string, number>();
  for (const a of s.assignments) if (a.task_type === "PACK") packEnd.set(a.order_ids[0], a.end_min);
  const old = new Map((compareTo?.assignments ?? []).map((a) => [a.task_id, a]));
  const bars: Bar[] = [];
  for (const a of s.assignments) {
    if (a.task_type === "LOAD") continue;
    const oid = a.order_ids[0];
    const o = om.get(oid);
    const late = o ? (packEnd.get(oid) ?? 0) > o.due_min : false;
    const prev = old.get(a.task_id);
    const changed = compareTo ? !prev || prev.start_min !== a.start_min || JSON.stringify(prev.resources) !== JSON.stringify(a.resources) : false;
    for (const [kind, rid] of Object.entries(a.resources)) {
      if (!laneSet.has(rid)) continue;
      bars.push({
        id: `${a.task_id}@${rid}`,
        lane: rid,
        start: a.start_min,
        end: a.end_min,
        color: kind === a.task_type.toLowerCase() || rid === a.resource_id ? TASK_COLOR[a.task_type] : `${TASK_COLOR[a.task_type]}99`,
        label: oid,
        frozen: a.frozen,
        warn: late,
        outline: changed ? "#7c3aed" : undefined,
        faded: !!focus && !oid.toLowerCase().includes(focus.toLowerCase()),
        tooltip: [
          `${a.task_type} ${oid}`,
          `${clock(hs, tz, a.start_min)}–${clock(hs, tz, a.end_min)} (${a.end_min - a.start_min}분)`,
          `자원 ${Object.values(a.resources).join("+")}`,
          o ? `출고마감 ${clock(hs, tz, o.due_min)} · 우선순위 ${o.priority}` : "",
          late ? "⚠ 마감 초과" : "",
          a.frozen ? "고정(실행/확정)" : "",
          changed ? "재스케줄로 변경됨" : "",
        ].filter(Boolean),
      });
    }
  }
  const links: Link[] = [];
  if (focus) {
    for (const a of s.assignments) {
      if (a.task_type !== "PACK" || !a.order_ids[0].toLowerCase().includes(focus.toLowerCase())) continue;
      const pick = s.assignments.find((x) => x.task_id === a.task_id.replace("-PACK", "-PICK"));
      if (pick && laneSet.has(pick.resource_id) && laneSet.has(a.resource_id))
        links.push({ from: `${pick.task_id}@${pick.resource_id}`, to: `${a.task_id}@${a.resource_id}` });
    }
  }
  return { lanes, bars, links };
}

export function GanttPage() {
  const runId = useUi((s) => s.runId);
  const sched = useSchedule(runId);
  const [zoom, setZoom] = useState(1.5);
  const [kinds, setKinds] = useState(new Set(["worker", "pack_station", "equipment"]));
  const [focus, setFocus] = useState("");
  const s = sched.data;
  const view = useMemo(() => (s ? warehouseBars(s, kinds, focus) : null), [s, kinds, focus]);
  const span = useMemo(() => {
    if (!s) return { min: 0, max: 600 };
    const wh = s.assignments.filter((a) => a.task_type !== "LOAD");
    const lo = Math.min(...wh.map((a) => a.start_min), s.current_time_min);
    const hi = Math.max(...wh.map((a) => a.end_min));
    return { min: Math.max(0, Math.floor((lo - 30) / 30) * 30), max: Math.min(s.horizon_min, Math.ceil((hi + 30) / 30) * 30) };
  }, [s]);
  const toggle = (k: string) => {
    const n = new Set(kinds);
    if (n.has(k)) n.delete(k);
    else n.add(k);
    setKinds(n);
  };

  return (
    <div className="space-y-4">
      <PageHeader title="창고 작업 간트 (피킹·패킹)" subtitle="자원별 레인 · 읽기 전용 · 모든 막대는 검증된 실행 결과(API)에서 생성" actions={<RunPicker types={["warehouse", "dock", "integrated"]} />} />
      {!runId ? (
        <EmptyState>표시할 실행이 없습니다.</EmptyState>
      ) : sched.isLoading ? (
        <Spinner />
      ) : sched.isError ? (
        <ErrorState error={sched.error} onRetry={() => sched.refetch()} />
      ) : s && view ? (
        <>
          <Card>
            <div className="flex flex-wrap items-center gap-4 text-sm">
              <fieldset className="flex items-center gap-3">
                <legend className="sr-only">자원 유형</legend>
                {Object.entries(KIND_KO).map(([k, label]) => (
                  <label key={k} className="flex items-center gap-1">
                    <input type="checkbox" checked={kinds.has(k)} onChange={() => toggle(k)} /> {label}
                  </label>
                ))}
              </fieldset>
              <label className="flex items-center gap-2">
                주문 필터
                <input className={`${inputCls} w-32 py-1`} placeholder="예: O0012" value={focus} onChange={(e) => setFocus(e.target.value)} aria-label="주문 필터" />
              </label>
              <ZoomControl value={zoom} onChange={setZoom} />
              <span className="text-xs text-ink-400">
                작업 {s.assignments.filter((a) => a.task_type !== "LOAD").length}건 · 미처리 {s.unserved.length}건 · 시간대 {s.timezone}
              </span>
            </div>
          </Card>
          <Timeline
            ariaLabel="창고 작업 간트 차트"
            lanes={view.lanes}
            bars={view.bars}
            links={view.links}
            min={span.min}
            max={span.max}
            pxPerMin={zoom}
            tickLabel={(m) => clock(s.horizon_start, s.timezone, m)}
            markers={s.current_time_min > 0 ? [{ at: s.current_time_min, label: "재계획 시점", color: "#dc2626", dashed: true }] : []}
            legend={
              <span className="flex flex-wrap gap-3">
                <LegendDot color={TASK_COLOR.PICK}>피킹</LegendDot>
                <LegendDot color={TASK_COLOR.PACK}>패킹</LegendDot>
                <LegendDot color="#eef1f5">비가용(교대 외/정비)</LegendDot>
                <span className="text-red-600">빨간 테두리 = 출고마감 초과</span>
              </span>
            }
          />
          {s.unserved.length > 0 && (
            <Card title={`미처리 주문 (${s.unserved.length})`}>
              <div className="flex flex-wrap gap-1.5">
                {s.unserved.map((u) => (
                  <Badge key={u.order_id} color="red" title={`페널티 ₩${u.penalty.toLocaleString()}`}>
                    {u.order_id}: {u.reason}
                  </Badge>
                ))}
              </div>
            </Card>
          )}
        </>
      ) : null}
    </div>
  );
}
