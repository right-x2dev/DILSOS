import { lazy, Suspense, useMemo, useState } from "react";
import { useGeo, useSchedule } from "../../api/hooks";
import { RunPicker } from "../../components/RunPicker";
import { Badge, Card, EmptyState, ErrorState, Kpi, PageHeader, Spinner, cx } from "../../components/ui";
import { useUi } from "../../store/ui";
import type { Geo, Schedule } from "../../types/api";
import { clock, pct } from "../../utils/time";
import { routeColor } from "./colors";

const OsmMap = lazy(() => import("./OsmMap"));

/** Schematic SVG of synthetic km coordinates with straight stop-to-stop segments. */
export function SchematicMap({ geo, s, focus }: { geo: Geo; s: Schedule; focus: string | null }) {
  const pts = geo.points;
  const xs = pts.map((p) => p.x_km);
  const ys = pts.map((p) => p.y_km);
  const minX = Math.min(...xs) - 1;
  const maxX = Math.max(...xs) + 1;
  const minY = Math.min(...ys) - 1;
  const maxY = Math.max(...ys) + 1;
  const W = 640;
  const scale = W / Math.max(maxX - minX, maxY - minY);
  const H = (maxY - minY) * scale;
  const px = (x: number) => (x - minX) * scale;
  const py = (y: number) => H - (y - minY) * scale; // north up
  const byId = new Map(pts.map((p) => [p.id, p]));
  const depot = byId.get("DEPOT")!;
  const served = new Map<string, { color: string; late: boolean; seq: number; vid: string }>();
  s.routes.forEach((r, i) => r.stops.forEach((st) => served.set(st.customer_id, { color: routeColor(i), late: st.late_min > 0, seq: st.seq, vid: r.vehicle_id })));
  return (
    <svg role="img" aria-label="배송 경로 도식" viewBox={`-10 -10 ${W + 20} ${H + 20}`} className="w-full rounded border border-ink-100 bg-[#fbfcfe]" style={{ maxHeight: 560 }}>
      {s.routes.map((r, i) => {
        const returned = r.stops.length > 0 && r.return_min > r.stops[r.stops.length - 1].departure_min;
        const coords = [depot, ...r.stops.map((st) => byId.get(st.customer_id)!), ...(returned ? [depot] : [])].filter(Boolean);
        const dim = focus && focus !== r.vehicle_id;
        return (
          <polyline
            key={r.vehicle_id}
            points={coords.map((p) => `${px(p.x_km)},${py(p.y_km)}`).join(" ")}
            fill="none"
            stroke={routeColor(i)}
            strokeWidth={dim ? 1 : 2.2}
            strokeDasharray="6 3"
            opacity={dim ? 0.15 : 0.9}
          >
            <title>{`${r.vehicle_id}: 직선 도식 (실제 도로 아님)`}</title>
          </polyline>
        );
      })}
      {pts
        .filter((p) => p.kind === "customer")
        .map((p) => {
          const sv = served.get(p.id);
          const dim = focus && sv?.vid !== focus;
          return (
            <g key={p.id} opacity={dim ? 0.3 : 1}>
              <circle cx={px(p.x_km)} cy={py(p.y_km)} r={sv ? 5 : 4} fill={sv ? sv.color : "#cbd5e1"} stroke={sv?.late ? "#dc2626" : "#fff"} strokeWidth={sv?.late ? 2.5 : 1}>
                <title>{`${p.id} ${p.name}${sv ? ` · ${sv.vid} #${sv.seq}${sv.late ? " · 지연" : ""}` : " · 미배정"}\n시간창 ${p.tw_start !== null ? clock(s.horizon_start, s.timezone, p.tw_start) : "?"}–${p.tw_end !== null ? clock(s.horizon_start, s.timezone, p.tw_end) : "?"}`}</title>
              </circle>
              {sv && !dim && (
                <text x={px(p.x_km) + 6} y={py(p.y_km) - 5} fontSize={9} fill="#334155">
                  {sv.seq}
                </text>
              )}
            </g>
          );
        })}
      <rect x={px(depot.x_km) - 7} y={py(depot.y_km) - 7} width={14} height={14} fill="#0b2036">
        <title>물류센터 (depot)</title>
      </rect>
      <text x={px(depot.x_km) + 10} y={py(depot.y_km) + 4} fontSize={11} fontWeight={600} fill="#0b2036">
        DC
      </text>
      <text x={0} y={H + 6} fontSize={10} fill="#64748b">
        축척: 합성 km 좌표 · 점선 = 정류장 간 직선(도식) — 실제 도로 경로/거리 아님
      </text>
    </svg>
  );
}

export function RouteTable({ s, focus, onFocus }: { s: Schedule; focus: string | null; onFocus: (v: string | null) => void }) {
  const vmap = new Map(s.vehicles.map((v) => [v.id, v]));
  const c = (m: number) => clock(s.horizon_start, s.timezone, m);
  return (
    <div className="space-y-3">
      {s.routes.map((r, i) => {
        const v = vmap.get(r.vehicle_id);
        const late = r.stops.filter((x) => x.late_min > 0).length;
        return (
          <Card
            key={r.vehicle_id}
            title={
              <button className="flex items-center gap-2" onClick={() => onFocus(focus === r.vehicle_id ? null : r.vehicle_id)} aria-pressed={focus === r.vehicle_id}>
                <span className="inline-block h-3 w-3 rounded-sm" style={{ background: routeColor(i) }} />
                {r.vehicle_id} ({v?.vehicle_class}) · 정류장 {r.stops.length} · {(r.distance_m / 1000).toFixed(1)} km(합성)
                {late ? <Badge color="red">지연 {late}</Badge> : <Badge color="green">정시</Badge>}
              </button>
            }
            className={cx(focus && focus !== r.vehicle_id && "opacity-50")}
          >
            <div className="mb-2 text-xs text-ink-600">
              {r.dock_id ? `도크 ${r.dock_id} 적재 ${c(r.load_start_min!)}–${c(r.load_end_min!)} · ` : ""}출발 {c(r.departure_min)} → 복귀 {c(r.return_min)} · 적재 {r.load_kg}kg
              {v ? ` (${pct(r.load_kg / v.capacity_kg, 0)})` : ""}, {r.load_l}L
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-ink-400">
                  <tr>
                    <th>#</th>
                    <th>고객</th>
                    <th>주문</th>
                    <th>도착</th>
                    <th>대기</th>
                    <th>서비스</th>
                    <th>시간창</th>
                    <th>지연</th>
                    <th>잔여 적재</th>
                  </tr>
                </thead>
                <tbody>
                  {r.stops.map((st) => {
                    const o = s.orders.find((x) => x.id === st.order_ids[0]);
                    return (
                      <tr key={st.seq} className={cx("border-t border-ink-100", st.late_min > 0 && "bg-red-50")}>
                        <td className="py-0.5">{st.seq}</td>
                        <td>{st.customer_id}</td>
                        <td>{st.order_ids.join(", ")}</td>
                        <td>{c(st.arrival_min)}</td>
                        <td>{st.wait_min}분</td>
                        <td>
                          {c(st.service_start_min)}–{c(st.service_end_min)}
                        </td>
                        <td>{o ? `${c(o.tw_start)}–${c(o.tw_end)}` : "–"}</td>
                        <td className={st.late_min ? "font-medium text-red-700" : ""}>{st.late_min ? `${st.late_min}분` : "–"}</td>
                        <td>{st.load_after_kg}kg</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

export function RoutesPage() {
  const scenarioId = useUi((s) => s.scenarioId);
  const runId = useUi((s) => s.runId);
  const sched = useSchedule(runId);
  const geo = useGeo(scenarioId);
  const [mode, setMode] = useState<"schematic" | "osm">("schematic");
  const [focus, setFocus] = useState<string | null>(null);
  const s = sched.data;
  const totals = useMemo(() => {
    if (!s) return null;
    const stops = s.routes.flatMap((r) => r.stops);
    return {
      km: s.routes.reduce((a, r) => a + r.distance_m, 0) / 1000,
      late: stops.filter((x) => x.late_min > 0).length,
      stops: stops.length,
    };
  }, [s]);
  return (
    <div className="space-y-4">
      <PageHeader title="배송 경로" subtitle="차량별 정류장 순서·도착/서비스 시각·시간창 (경로선은 직선 도식)" actions={<RunPicker types={["routing", "dock", "integrated"]} />} />
      {!runId ? (
        <EmptyState>표시할 실행이 없습니다.</EmptyState>
      ) : sched.isLoading || geo.isLoading ? (
        <Spinner />
      ) : sched.isError ? (
        <ErrorState error={sched.error} onRetry={() => sched.refetch()} />
      ) : geo.isError ? (
        <ErrorState error={geo.error} />
      ) : s && geo.data && totals ? (
        !s.routes.length ? (
          <EmptyState>이 실행에는 경로가 없습니다 (문제 유형: {s.problem_type}).</EmptyState>
        ) : (
          <>
            <div role="note" className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
              데이터 출처: 좌표 = <b>{geo.data.coordinate_provenance}</b> · 이동시간/거리 = <b>{geo.data.travel_provenance}</b> ({geo.data.travel_notes}). 실제 도로 주행시간이 아닙니다.
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Kpi label="차량" value={s.routes.length} unit="대" />
              <Kpi label="정류장" value={totals.stops} unit="곳" />
              <Kpi label="총 거리(합성)" value={totals.km.toFixed(1)} unit="km" />
              <Kpi label="지연 정류장" value={totals.late} unit="곳" />
            </div>
            <div className="grid gap-4 xl:grid-cols-5">
              <Card
                className="xl:col-span-3"
                title="경로 지도"
                actions={
                  <div role="tablist" className="flex gap-1 text-xs">
                    <button role="tab" aria-selected={mode === "schematic"} className={cx("rounded px-2 py-1", mode === "schematic" ? "bg-tower-700 text-white" : "hover:bg-ink-100")} onClick={() => setMode("schematic")}>
                      도식 (합성 km)
                    </button>
                    <button role="tab" aria-selected={mode === "osm"} className={cx("rounded px-2 py-1", mode === "osm" ? "bg-tower-700 text-white" : "hover:bg-ink-100")} onClick={() => setMode("osm")}>
                      OSM 지도 (표시용)
                    </button>
                  </div>
                }
              >
                {mode === "schematic" ? (
                  <SchematicMap geo={geo.data} s={s} focus={focus} />
                ) : (
                  <Suspense fallback={<Spinner label="지도 로딩…" />}>
                    <OsmMap geo={geo.data} s={s} focus={focus} />
                  </Suspense>
                )}
                <div className="mt-2 flex flex-wrap gap-2 text-xs">
                  {s.routes.map((r, i) => (
                    <button key={r.vehicle_id} onClick={() => setFocus(focus === r.vehicle_id ? null : r.vehicle_id)} className={cx("flex items-center gap-1 rounded border px-1.5 py-0.5", focus === r.vehicle_id ? "border-ink-800" : "border-ink-200")}>
                      <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: routeColor(i) }} /> {r.vehicle_id}
                    </button>
                  ))}
                  <span className="text-ink-400">회색 = 이 실행에서 미배정 고객 · 빨간 테두리 = 지연</span>
                </div>
              </Card>
              <div className="max-h-[75vh] overflow-auto xl:col-span-2">
                <RouteTable s={s} focus={focus} onFocus={setFocus} />
              </div>
            </div>
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
