import { useMemo, useState } from "react";
import { useSchedule } from "../../api/hooks";
import { RunPicker } from "../../components/RunPicker";
import { LegendDot, Timeline, ZoomControl, type Bar, type Lane } from "../../components/Timeline";
import { Badge, Card, EmptyState, ErrorState, Kpi, PageHeader, Spinner, inputCls } from "../../components/ui";
import { useUi } from "../../store/ui";
import type { Schedule } from "../../types/api";
import { clock, fmtDuration } from "../../utils/time";

export const STAGE = {
  wait: "#e2e8f0",
  pick: "#2563eb",
  pack: "#059669",
  dockwait: "#fde68a",
  load: "#d97706",
  transit: "#7c3aed",
  custwait: "#ddd6fe",
  service: "#4c1d95",
  late: "#dc2626",
};

const CAUSE_KO: Record<string, string> = {
  wait_pick: "피킹 대기(작업자/장비 부족)",
  wait_pack: "포장 대기(포장대/포장인력)",
  wait_load: "도크/차량 대기(동승 주문 준비·도크 경합)",
  transit: "운송(경로상 앞 정류장)",
};

export type Journey = {
  order: string;
  vehicle: string;
  release: number;
  pick: [number, number];
  pack: [number, number];
  load: [number, number];
  departure: number;
  arrival: number;
  serviceStart: number;
  serviceEnd: number;
  twEnd: number;
  late: number;
  segments: Record<string, number>;
  cause: string | null;
};

/** Build one journey per delivered order purely from the published schedule. */
export function buildJourneys(s: Schedule): Journey[] {
  const om = new Map(s.orders.map((o) => [o.id, o]));
  const task = new Map<string, { s: number; e: number }>();
  for (const a of s.assignments) if (a.task_type !== "LOAD") task.set(`${a.task_type}:${a.order_ids[0]}`, { s: a.start_min, e: a.end_min });
  const out: Journey[] = [];
  for (const r of s.routes) {
    if (r.load_start_min === null || r.load_end_min === null) continue;
    for (const st of r.stops) {
      for (const oid of st.order_ids) {
        const pk = task.get(`PICK:${oid}`);
        const pc = task.get(`PACK:${oid}`);
        const o = om.get(oid);
        if (!pk || !pc || !o) continue;
        const segments = {
          wait_pick: pk.s - o.release_min,
          wait_pack: pc.s - pk.e,
          wait_load: r.load_start_min - pc.e,
          transit: st.arrival_min - r.departure_min,
        };
        const late = st.late_min;
        const cause = late > 0 ? Object.entries(segments).sort((a, b) => b[1] - a[1])[0][0] : null;
        out.push({
          order: oid,
          vehicle: r.vehicle_id,
          release: o.release_min,
          pick: [pk.s, pk.e],
          pack: [pc.s, pc.e],
          load: [r.load_start_min, r.load_end_min],
          departure: r.departure_min,
          arrival: st.arrival_min,
          serviceStart: st.service_start_min,
          serviceEnd: st.service_end_min,
          twEnd: o.tw_end,
          late,
          segments,
          cause,
        });
      }
    }
  }
  return out.sort((a, b) => b.late - a.late || a.order.localeCompare(b.order));
}

function journeyBars(j: Journey, c: (m: number) => string): Bar[] {
  const lane = j.order;
  const seg = (id: string, s: number, e: number, color: string, label: string): Bar | null =>
    e > s ? { id: `${lane}-${id}`, lane, start: s, end: e, color, tooltip: [`${j.order} ${label}`, `${c(s)}–${c(e)} (${e - s}분)`, `차량 ${j.vehicle}`] } : null;
  return [
    seg("w1", j.release, j.pick[0], STAGE.wait, "피킹 대기"),
    seg("pk", j.pick[0], j.pick[1], STAGE.pick, "피킹"),
    seg("w2", j.pick[1], j.pack[0], STAGE.wait, "포장 대기"),
    seg("pc", j.pack[0], j.pack[1], STAGE.pack, "포장"),
    seg("w3", j.pack[1], j.load[0], STAGE.dockwait, "도크/차량 대기"),
    seg("ld", j.load[0], j.load[1], STAGE.load, "적재"),
    seg("tr", j.departure, j.arrival, STAGE.transit, "운송(앞 정류장 포함)"),
    seg("w4", j.arrival, j.serviceStart, STAGE.custwait, "고객 시간창 대기"),
    seg("sv", j.serviceStart, j.serviceEnd, STAGE.service, "배송 서비스"),
    j.late > 0 ? seg("late", j.twEnd, j.serviceStart, STAGE.late, `지연 ${j.late}분 (시간창 종료 초과)`) : null,
  ].filter((b): b is Bar => b !== null);
}

export function JourneyPage() {
  const runId = useUi((s) => s.runId);
  const sched = useSchedule(runId);
  const [lateOnly, setLateOnly] = useState(false);
  const [q, setQ] = useState("");
  const [zoom, setZoom] = useState(1);
  const s = sched.data;
  const journeys = useMemo(() => (s ? buildJourneys(s) : []), [s]);
  const shown = journeys.filter((j) => (!lateOnly || j.late > 0) && (!q || j.order.toLowerCase().includes(q.toLowerCase())));
  const c = (m: number) => (s ? clock(s.horizon_start, s.timezone, m) : String(m));
  const lanes: Lane[] = shown.map((j) => ({ id: j.order, label: j.order, sublabel: `${j.vehicle}${j.late ? ` · 지연 ${j.late}분` : ""}` }));
  const bars = shown.flatMap((j) => journeyBars(j, c));
  const causes = journeys.filter((j) => j.cause).reduce<Record<string, number>>((acc, j) => ((acc[j.cause!] = (acc[j.cause!] ?? 0) + 1), acc), {});
  const lo = Math.min(...shown.map((j) => j.release), 0);
  const hi = Math.max(...shown.map((j) => j.serviceEnd), 60);
  return (
    <div className="space-y-4">
      <PageHeader title="통합 타임라인 (주문 여정)" subtitle="입고 → 피킹 → 포장 → 적재 → 출발 → 배송 · 지연 전파와 주 원인" actions={<RunPicker types={["integrated", "dock"]} />} />
      {!runId ? (
        <EmptyState>표시할 실행이 없습니다.</EmptyState>
      ) : sched.isLoading ? (
        <Spinner />
      ) : sched.isError ? (
        <ErrorState error={sched.error} onRetry={() => sched.refetch()} />
      ) : !journeys.length ? (
        <EmptyState>창고 작업과 배송 경로가 모두 있는 실행(통합/도크)을 선택하세요.</EmptyState>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Kpi label="배송 주문" value={journeys.length} unit="건" />
            <Kpi label="지연 주문" value={journeys.filter((j) => j.late > 0).length} unit="건" />
            <Kpi label="평균 도크/차량 대기" value={fmtDuration(Math.round(journeys.reduce((a, j) => a + j.segments.wait_load, 0) / journeys.length))} hint="포장 완료 → 적재 시작" />
            <Kpi label="평균 리드타임" value={fmtDuration(Math.round(journeys.reduce((a, j) => a + (j.serviceStart - j.release), 0) / journeys.length))} hint="입고 → 배송 시작" />
            <Kpi label="미처리" value={s!.unserved.length} unit="건" />
          </div>
          {Object.keys(causes).length > 0 && (
            <Card title="지연 주 원인 (가장 긴 대기/운송 구간 기준)">
              <div className="flex flex-wrap gap-2 text-sm">
                {Object.entries(causes)
                  .sort((a, b) => b[1] - a[1])
                  .map(([k, n]) => (
                    <Badge key={k} color="red">
                      {CAUSE_KO[k] ?? k}: {n}건
                    </Badge>
                  ))}
              </div>
              <p className="mt-1 text-xs text-ink-400">휴리스틱 귀속: 각 지연 주문에서 가장 긴 구간을 원인으로 표시합니다(인과 추론 아님).</p>
            </Card>
          )}
          <Card>
            <div className="flex flex-wrap items-center gap-4 text-sm">
              <label className="flex items-center gap-1">
                <input type="checkbox" checked={lateOnly} onChange={(e) => setLateOnly(e.target.checked)} /> 지연 주문만
              </label>
              <input className={`${inputCls} w-36 py-1`} placeholder="주문 검색" value={q} onChange={(e) => setQ(e.target.value)} aria-label="주문 검색" />
              <ZoomControl value={zoom} onChange={setZoom} />
              <span className="text-xs text-ink-400">{shown.length}건 표시 (지연 큰 순)</span>
            </div>
          </Card>
          {shown.length ? (
            <Timeline
              ariaLabel="주문 여정 타임라인"
              lanes={lanes}
              bars={bars}
              min={Math.max(0, Math.floor(lo / 60) * 60)}
              max={Math.ceil(hi / 60) * 60}
              pxPerMin={zoom}
              rowH={22}
              tickLabel={c}
              legend={
                <span className="flex flex-wrap gap-2">
                  <LegendDot color={STAGE.pick}>피킹</LegendDot>
                  <LegendDot color={STAGE.pack}>포장</LegendDot>
                  <LegendDot color={STAGE.dockwait}>도크 대기</LegendDot>
                  <LegendDot color={STAGE.load}>적재</LegendDot>
                  <LegendDot color={STAGE.transit}>운송</LegendDot>
                  <LegendDot color={STAGE.service}>배송</LegendDot>
                  <LegendDot color={STAGE.late}>지연</LegendDot>
                </span>
              }
            />
          ) : (
            <EmptyState>조건에 맞는 주문이 없습니다.</EmptyState>
          )}
        </>
      )}
    </div>
  );
}
