import { useMemo, useState } from "react";
import { useSchedule } from "../../api/hooks";
import { RunPicker } from "../../components/RunPicker";
import { LegendDot, Timeline, ZoomControl, type Bar, type Lane } from "../../components/Timeline";
import { Badge, Card, EmptyState, ErrorState, Kpi, PageHeader, Spinner } from "../../components/ui";
import { useUi } from "../../store/ui";
import type { Schedule } from "../../types/api";
import { clock, pct } from "../../utils/time";

export const DOCK_COLOR = { load: "#d97706", wait: "#cbd5e1", road: "#7c3aed" };

export type DockWarning = { kind: "overlap" | "capacity" | "early_load" | "incompatible"; text: string };

/** Derive dock/vehicle lanes and integrity warnings from the published schedule. */
export function dockView(s: Schedule) {
  const tz = s.timezone;
  const hs = s.horizon_start;
  const c = (m: number) => clock(hs, tz, m);
  const vmap = new Map(s.vehicles.map((v) => [v.id, v]));
  const docks = s.resources.filter((r) => r.kind === "dock");
  const dockLanes: Lane[] = docks.map((d) => ({ id: d.id, label: `${d.id} ${d.name}`, sublabel: `허용: ${d.vehicle_classes.join(",") || "전체"}`, available: d.available }));
  const vehLanes: Lane[] = s.routes.map((r) => {
    const v = vmap.get(r.vehicle_id);
    return {
      id: `veh-${r.vehicle_id}`,
      label: `${r.vehicle_id} ${v?.vehicle_class ?? ""}`,
      sublabel: v ? `근무 ${c(v.shift_start)}–${c(v.shift_end)}` : undefined,
      available: v ? [{ start: v.shift_start, end: v.shift_end }] : undefined,
    };
  });
  const dockBars: Bar[] = [];
  const vehBars: Bar[] = [];
  const warnings: DockWarning[] = [];
  for (const r of s.routes) {
    if (r.load_start_min === null || r.load_end_min === null || !r.dock_id) continue;
    const v = vmap.get(r.vehicle_id);
    const util = v ? r.load_kg / v.capacity_kg : null;
    const lateStops = r.stops.filter((x) => x.late_min > 0).length;
    const tip = [
      `${r.vehicle_id} @ ${r.dock_id}`,
      `적재 ${c(r.load_start_min)}–${c(r.load_end_min)} (${r.load_end_min - r.load_start_min}분, 주문 ${r.order_ids.length}건)`,
      `준비완료 ${c(r.ready_min)} · 출발 ${c(r.departure_min)} · 복귀 ${c(r.return_min)}`,
      v ? `적재율 ${pct(util)} (${r.load_kg}/${v.capacity_kg}kg, ${r.load_l}/${v.capacity_l}L)` : "",
      lateStops ? `지연 정류장 ${lateStops}곳` : "",
    ].filter(Boolean);
    dockBars.push({ id: `L-${r.vehicle_id}`, lane: r.dock_id, start: r.load_start_min, end: r.load_end_min, color: DOCK_COLOR.load, label: r.vehicle_id, tooltip: tip, warn: lateStops > 0 });
    if (r.load_start_min > r.ready_min)
      vehBars.push({ id: `W-${r.vehicle_id}`, lane: `veh-${r.vehicle_id}`, start: r.ready_min, end: r.load_start_min, color: DOCK_COLOR.wait, tooltip: [`${r.vehicle_id} 도크 대기`, `준비완료 ${c(r.ready_min)} → 적재시작 ${c(r.load_start_min)}`] });
    vehBars.push({ id: `VL-${r.vehicle_id}`, lane: `veh-${r.vehicle_id}`, start: r.load_start_min, end: r.load_end_min, color: DOCK_COLOR.load, tooltip: tip });
    vehBars.push({
      id: `R-${r.vehicle_id}`,
      lane: `veh-${r.vehicle_id}`,
      start: r.departure_min,
      end: r.return_min,
      color: DOCK_COLOR.road,
      label: `${r.stops.length}곳`,
      warn: lateStops > 0,
      tooltip: [`${r.vehicle_id} 배송`, `출발 ${c(r.departure_min)} → 복귀 ${c(r.return_min)}`, `정류장 ${r.stops.length} · 거리 ${(r.distance_m / 1000).toFixed(1)}km (합성)`, lateStops ? `지연 ${lateStops}곳` : "정시"],
    });
    if (util !== null && util > 1) warnings.push({ kind: "capacity", text: `${r.vehicle_id} 적재 초과 ${pct(util)}` });
    if (r.load_start_min < r.ready_min) warnings.push({ kind: "early_load", text: `${r.vehicle_id} 포장 완료 전 적재 시작` });
    const dock = docks.find((d) => d.id === r.dock_id);
    if (dock && v && dock.vehicle_classes.length && !dock.vehicle_classes.includes(v.vehicle_class))
      warnings.push({ kind: "incompatible", text: `${r.vehicle_id}(${v.vehicle_class}) → ${dock.id} 비호환` });
  }
  const byDock = new Map<string, Bar[]>();
  for (const b of dockBars) byDock.set(b.lane, [...(byDock.get(b.lane) ?? []), b]);
  for (const [d, bs] of byDock) {
    bs.sort((a, b) => a.start - b.start);
    for (let i = 1; i < bs.length; i++)
      if (bs[i].start < bs[i - 1].end) warnings.push({ kind: "overlap", text: `${d}: ${bs[i - 1].label} / ${bs[i].label} 적재 중첩` });
  }
  const busy = new Map<string, number>();
  for (const b of dockBars) busy.set(b.lane, (busy.get(b.lane) ?? 0) + (b.end - b.start));
  const utilization = docks.map((d) => {
    const avail = d.available.reduce((acc, w) => acc + (w.end - w.start), 0);
    return { id: d.id, util: avail ? (busy.get(d.id) ?? 0) / avail : 0 };
  });
  return { dockLanes, vehLanes, dockBars, vehBars, warnings, utilization };
}

export function DockPage() {
  const runId = useUi((s) => s.runId);
  const sched = useSchedule(runId);
  const [zoom, setZoom] = useState(1);
  const s = sched.data;
  const v = useMemo(() => (s ? dockView(s) : null), [s]);
  const span = useMemo(() => {
    if (!s || !s.routes.length) return { min: 0, max: s?.horizon_min ?? 960 };
    const lo = Math.min(...s.routes.map((r) => Math.min(r.ready_min, r.load_start_min ?? r.departure_min)));
    const hi = Math.max(...s.routes.map((r) => r.return_min));
    return { min: Math.max(0, Math.floor((lo - 30) / 60) * 60), max: Math.min(s.horizon_min, Math.ceil((hi + 30) / 60) * 60) };
  }, [s]);
  return (
    <div className="space-y-4">
      <PageHeader title="도크 · 차량 타임라인" subtitle="적재 예약(도크 레인)과 차량 운행(준비완료 → 적재 → 출발 → 복귀)" actions={<RunPicker types={["dock", "integrated"]} />} />
      {!runId ? (
        <EmptyState>표시할 실행이 없습니다.</EmptyState>
      ) : sched.isLoading ? (
        <Spinner />
      ) : sched.isError ? (
        <ErrorState error={sched.error} onRetry={() => sched.refetch()} />
      ) : s && v ? (
        !s.routes.length ? (
          <EmptyState>이 실행에는 도크/차량 배정이 없습니다 (문제 유형: {s.problem_type}).</EmptyState>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {v.utilization.map((u) => (
                <Kpi key={u.id} label={`${u.id} 가동률`} value={pct(u.util)} hint="적재시간 / 운영시간" />
              ))}
              <Kpi label="배차 차량" value={s.routes.length} unit="대" />
              <Kpi label="무결성 경고" value={v.warnings.length} unit="건" hint="중첩·용량·조기적재·비호환 (0이어야 정상)" />
            </div>
            {v.warnings.length > 0 && (
              <div role="alert" className="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-800">
                {v.warnings.map((w, i) => (
                  <div key={i}>⚠ {w.text}</div>
                ))}
              </div>
            )}
            <div className="flex items-center justify-end">
              <ZoomControl value={zoom} onChange={setZoom} />
            </div>
            <Timeline
              ariaLabel="도크 적재 타임라인"
              lanes={v.dockLanes}
              bars={v.dockBars}
              min={span.min}
              max={span.max}
              pxPerMin={zoom}
              rowH={30}
              tickLabel={(m) => clock(s.horizon_start, s.timezone, m)}
              legend={
                <span className="flex gap-3">
                  <LegendDot color={DOCK_COLOR.load}>적재</LegendDot>
                  <LegendDot color="#eef1f5">도크 비가용</LegendDot>
                  <span className="text-red-600">빨간 테두리 = 지연 정류장 포함</span>
                </span>
              }
            />
            <Timeline
              ariaLabel="차량 운행 타임라인"
              lanes={v.vehLanes}
              bars={v.vehBars}
              min={span.min}
              max={span.max}
              pxPerMin={zoom}
              tickLabel={(m) => clock(s.horizon_start, s.timezone, m)}
              legend={
                <span className="flex gap-3">
                  <LegendDot color={DOCK_COLOR.wait}>도크 대기</LegendDot>
                  <LegendDot color={DOCK_COLOR.load}>적재</LegendDot>
                  <LegendDot color={DOCK_COLOR.road}>배송 운행(합성 이동시간)</LegendDot>
                </span>
              }
            />
            {s.unserved.length > 0 && (
              <Card title={`미처리 주문 (${s.unserved.length})`}>
                <div className="flex flex-wrap gap-1.5">
                  {s.unserved.map((u) => (
                    <Badge key={u.order_id} color="red">
                      {u.order_id}: {u.reason}
                    </Badge>
                  ))}
                </div>
              </Card>
            )}
          </>
        )
      ) : null}
    </div>
  );
}
