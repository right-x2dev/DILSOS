import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useAlgorithms, useInvalidate, useSchedule } from "../../api/hooks";
import { RunPicker } from "../../components/RunPicker";
import { Timeline, LegendDot } from "../../components/Timeline";
import { Badge, Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, cx, inputCls, statusColor } from "../../components/ui";
import { useSelectedScenario } from "../../components/ScenarioPicker";
import { useUi } from "../../store/ui";
import type { Schedule } from "../../types/api";
import { clock, krw } from "../../utils/time";
import { zonedToIso } from "../../utils/zoned";
import { TASK_COLOR, warehouseBars } from "../gantt/GanttPage";

export const EVENT_KO: Record<string, string> = {
  urgent_order: "긴급 주문",
  worker_absence: "작업자 결근",
  pack_station_outage: "포장대 고장",
  dock_outage: "도크 중단",
  vehicle_breakdown: "차량 고장",
  travel_time_increase: "교통 지연(이동시간 증가)",
  order_cancellation: "주문 취소",
};

type EventRow = { id: number; event_type: string; event_time_min: number; affected_code: string | null; payload: Record<string, unknown>; idempotency_key: string };
type ResItem = {
  id: number;
  event_id: number;
  policy: string;
  new_run_id: number;
  status: string;
  feasible: boolean;
  total_cost: number | null;
  late_min: number | null;
  unserved: number | null;
  changed_tasks: number | null;
  changed_routes: number | null;
  stability_score: number | null;
  runtime_ms: number | null;
  selection: string | null;
  schedule_version: number | null;
  summary: { exceptions?: string[]; frozen_tasks?: number; replanned_tasks?: number; frozen_routes?: number; replanned_routes?: number; affected_orders?: string[] } | null;
};
type Summary = { base_run_id: number; items: ResItem[]; recommendations: Record<string, { recommended: string | null; reason: string; scores: Record<string, number> }> };

/** Minutes from horizon start for a local wall-clock HH:MM on the operating day. */
export function hhmmToHorizonMin(operatingDate: string, hhmm: string, tz: string, horizonStartIso: string): number {
  return Math.round((new Date(zonedToIso(operatingDate, hhmm, tz)).getTime() - new Date(horizonStartIso).getTime()) / 60000);
}

/** Changed vehicles: stop sequence or departure differs between versions. */
export function routeDiff(before: Schedule, after: Schedule) {
  const b = new Map(before.routes.map((r) => [r.vehicle_id, r]));
  const a = new Map(after.routes.map((r) => [r.vehicle_id, r]));
  const out: { vehicle: string; before: string; after: string; depBefore: number | null; depAfter: number | null }[] = [];
  for (const v of [...new Set([...b.keys(), ...a.keys()])].sort()) {
    const x = b.get(v);
    const y = a.get(v);
    const sx = x?.stops.map((s) => s.customer_id).join("→") ?? "(없음)";
    const sy = y?.stops.map((s) => s.customer_id).join("→") ?? "(없음)";
    if (sx !== sy || x?.departure_min !== y?.departure_min) out.push({ vehicle: v, before: sx, after: sy, depBefore: x?.departure_min ?? null, depAfter: y?.departure_min ?? null });
  }
  return out;
}

function DiffView({ base, next }: { base: Schedule; next: Schedule }) {
  const view = useMemo(() => warehouseBars(next, new Set(["worker", "pack_station", "equipment"]), "", base), [base, next]);
  const rd = useMemo(() => routeDiff(base, next), [base, next]);
  const c = (m: number) => clock(next.horizon_start, next.timezone, m);
  const lo = Math.max(0, Math.floor(Math.min(...next.assignments.map((x) => x.start_min), next.current_time_min) / 60) * 60 - 30);
  const hi = Math.ceil(Math.max(...next.assignments.map((x) => x.end_min)) / 60) * 60;
  return (
    <div className="space-y-3">
      <Timeline
        ariaLabel="재스케줄 전후 비교 간트"
        lanes={view.lanes}
        bars={view.bars}
        min={lo}
        max={hi}
        pxPerMin={1}
        tickLabel={c}
        markers={[{ at: next.current_time_min, label: "이벤트 시각", color: "#dc2626", dashed: true }]}
        legend={
          <span className="flex flex-wrap gap-2">
            <LegendDot color={TASK_COLOR.PICK}>피킹</LegendDot>
            <LegendDot color={TASK_COLOR.PACK}>패킹</LegendDot>
            <span className="text-violet-700">보라 테두리 = 변경됨</span>
            <span>점선 테두리 = 고정(실행/확정)</span>
          </span>
        }
      />
      <Card title={`경로 변경 (${rd.length}대)`}>
        {rd.length ? (
          <table className="w-full text-xs">
            <thead className="text-left text-ink-400">
              <tr>
                <th>차량</th>
                <th>변경 전</th>
                <th>변경 후</th>
                <th>출발 전→후</th>
              </tr>
            </thead>
            <tbody>
              {rd.map((d) => (
                <tr key={d.vehicle} className="border-t border-ink-100 align-top">
                  <td className="py-1 font-medium">{d.vehicle}</td>
                  <td className="max-w-xs break-words text-ink-600">{d.before}</td>
                  <td className="max-w-xs break-words">{d.after}</td>
                  <td>
                    {d.depBefore !== null ? c(d.depBefore) : "–"} → {d.depAfter !== null ? c(d.depAfter) : "–"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="text-xs text-ink-400">경로 변경 없음</div>
        )}
      </Card>
    </div>
  );
}

export function DisruptionPage() {
  const sc = useSelectedScenario();
  const [baseId, setBaseId] = useState<number | null>(null);
  const base = useSchedule(baseId);
  const algos = useAlgorithms();
  const inv = useInvalidate();
  const nav = useNavigate();
  const setRun = useUi((s) => s.setRun);
  const [type, setType] = useState("vehicle_breakdown");
  const [at, setAt] = useState("09:30");
  const [affected, setAffected] = useState("");
  const [duration, setDuration] = useState(120);
  const [factor, setFactor] = useState(1.3);
  const [urg, setUrg] = useState({ customer: "", sku: "", qty: 2, dueOffset: 150, priority: 3 });
  const [idemKey, setIdemKey] = useState(() => crypto.randomUUID());
  const [eventId, setEventId] = useState<number | null>(null);
  const [policies, setPolicies] = useState(["KEEP", "PARTIAL", "FULL"]);
  const [freeze, setFreeze] = useState(30);
  const [reopt, setReopt] = useState("");
  const [weights, setWeights] = useState({ w_cost: 1, w_lateness: 0.5, w_changes: 0.5, w_runtime: 0.05 });
  const [selected, setSelected] = useState<number | null>(null);

  const events = useQuery({ queryKey: ["events", sc?.id], queryFn: () => api<EventRow[]>(`/scenarios/${sc!.id}/events`), enabled: !!sc });
  const summary = useQuery({
    queryKey: ["reschedules", baseId, weights],
    queryFn: () => api<Summary>(`/runs/${baseId}/reschedules?${new URLSearchParams(Object.entries(weights).map(([k, v]) => [k, String(v)]))}`),
    enabled: !!baseId,
    refetchInterval: (q) => (q.state.data?.items.some((i) => ["QUEUED", "RUNNING"].includes(i.status)) ? 1500 : false),
  });
  const next = useSchedule(selected, !!selected && summary.data?.items.find((i) => i.new_run_id === selected)?.status === "SUCCEEDED");

  const s = base.data;
  const affectedOptions = useMemo(() => {
    if (!s) return [];
    switch (type) {
      case "worker_absence":
        return s.resources.filter((r) => r.kind === "worker").map((r) => r.id);
      case "pack_station_outage":
        return s.resources.filter((r) => r.kind === "pack_station").map((r) => r.id);
      case "dock_outage":
        return s.resources.filter((r) => r.kind === "dock").map((r) => r.id);
      case "vehicle_breakdown":
        return s.vehicles.map((v) => v.id);
      case "order_cancellation":
        return s.orders.map((o) => o.id);
      default:
        return [];
    }
  }, [s, type]);
  useEffect(() => {
    if (affectedOptions.length && !affectedOptions.includes(affected)) setAffected(affectedOptions[0]);
  }, [affectedOptions, affected]);
  const customers = useMemo(() => [...new Set((s?.orders ?? []).map((o) => o.customer_id))].sort(), [s]);

  const minutes = sc && s ? hhmmToHorizonMin(sc.operating_date, at, s.timezone, s.horizon_start) : null;
  const record = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {};
      if (["worker_absence", "pack_station_outage", "dock_outage"].includes(type)) payload.duration_min = duration;
      if (type === "travel_time_increase") payload.factor = factor;
      if (type === "urgent_order") Object.assign(payload, { customer_id: urg.customer, lines: [[urg.sku, urg.qty]], due_offset_min: urg.dueOffset, priority: urg.priority });
      return api<EventRow>(`/scenarios/${sc!.id}/events`, {
        body: { event_type: type, event_time_min: minutes, affected_code: ["travel_time_increase", "urgent_order"].includes(type) ? null : affected, payload },
        headers: { "Idempotency-Key": idemKey },
      });
    },
    onSuccess: (e) => {
      setEventId(e.id);
      setIdemKey(crypto.randomUUID());
      inv(["events", sc?.id]);
    },
  });
  const start = useMutation({
    mutationFn: () => api<{ new_run_ids: number[] }>(`/runs/${baseId}/reschedule`, { body: { event_id: eventId, policies, freeze_window_min: freeze, time_limit_s: 8, reoptimizer: reopt || null, expected_schedule_version: undefined } }),
    onSuccess: () => inv(["reschedules", baseId]),
  });
  const reopts = (algos.data ?? []).filter((a) => s && a.problem_types.includes(s.problem_type) && !a.name.startsWith("reschedule_") && a.available);
  const items = (summary.data?.items ?? []).filter((i) => i.event_id === eventId);
  const rec = eventId ? summary.data?.recommendations[String(eventId)] : undefined;

  if (!sc) return <EmptyState>시나리오를 선택하세요.</EmptyState>;
  return (
    <div className="space-y-4">
      <PageHeader title="교란 시뮬레이터" subtitle="이벤트 기록(멱등) → KEEP / PARTIAL / FULL 재스케줄 → 비교·추천 → 새 스케줄 버전" actions={<RunPicker types={["integrated", "warehouse"]} label="기준 실행" value={baseId} onChange={setBaseId} />} />
      <div role="note" className="rounded border border-ink-200 bg-white p-2 text-xs text-ink-600">
        모델링 가정: 진행 중 작업은 선점하지 않음(결근/고장은 현재 작업 종료 후 적용) · 출발 후 차량 고장은 경로 복구를 모델링하지 않고 예외로 표시 · 실행된 작업과 경로는 절대 변경하지 않음 · 모든 결과는 독립 검증기를 통과해야 게시됩니다.
      </div>
      {!baseId ? (
        <EmptyState>기준 실행(통합 또는 창고, SUCCEEDED)을 선택하세요.</EmptyState>
      ) : base.isLoading ? (
        <Spinner />
      ) : base.isError ? (
        <ErrorState error={base.error} />
      ) : (
        <>
          <div className="grid gap-4 xl:grid-cols-3">
            <Card title="1. 이벤트">
              <div className="space-y-2">
                <Field label="유형">
                  <select className={inputCls} value={type} onChange={(e) => setType(e.target.value)} aria-label="이벤트 유형">
                    {Object.entries(EVENT_KO).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label={`발생 시각 (${s!.timezone})`} hint={minutes !== null ? `계획 시작 + ${minutes}분` : undefined}>
                  <input className={inputCls} value={at} onChange={(e) => setAt(e.target.value)} aria-label="발생 시각" />
                </Field>
                {affectedOptions.length > 0 && (
                  <Field label="대상">
                    <select className={inputCls} value={affected} onChange={(e) => setAffected(e.target.value)} aria-label="대상">
                      {affectedOptions.map((x) => (
                        <option key={x}>{x}</option>
                      ))}
                    </select>
                  </Field>
                )}
                {["worker_absence", "pack_station_outage", "dock_outage"].includes(type) && (
                  <Field label="지속 시간(분)">
                    <input className={inputCls} type="number" min={1} value={duration} onChange={(e) => setDuration(Number(e.target.value))} />
                  </Field>
                )}
                {type === "travel_time_increase" && (
                  <Field label="이동시간 배율" hint="≥ 1 (합성 행렬에 적용)">
                    <input className={inputCls} type="number" min={1} step={0.1} value={factor} onChange={(e) => setFactor(Number(e.target.value))} />
                  </Field>
                )}
                {type === "urgent_order" && (
                  <div className="grid grid-cols-2 gap-2">
                    <Field label="고객">
                      <select className={inputCls} value={urg.customer} onChange={(e) => setUrg({ ...urg, customer: e.target.value })}>
                        <option value="">선택</option>
                        {customers.map((c) => (
                          <option key={c}>{c}</option>
                        ))}
                      </select>
                    </Field>
                    <Field label="SKU" hint="예: SKU001">
                      <input className={inputCls} value={urg.sku} onChange={(e) => setUrg({ ...urg, sku: e.target.value })} />
                    </Field>
                    <Field label="수량">
                      <input className={inputCls} type="number" min={1} value={urg.qty} onChange={(e) => setUrg({ ...urg, qty: Number(e.target.value) })} />
                    </Field>
                    <Field label="마감(분 후)">
                      <input className={inputCls} type="number" min={10} value={urg.dueOffset} onChange={(e) => setUrg({ ...urg, dueOffset: Number(e.target.value) })} />
                    </Field>
                  </div>
                )}
                {record.isError && <ErrorState error={record.error} />}
                <Button onClick={() => record.mutate()} disabled={record.isPending || minutes === null || minutes < 0}>
                  이벤트 기록
                </Button>
                <div className="text-[11px] text-ink-400">Idempotency-Key: {idemKey.slice(0, 8)}… (재시도 시 중복 기록 방지)</div>
              </div>
            </Card>
            <Card title="2. 기록된 이벤트">
              {events.data?.length ? (
                <ul className="max-h-64 space-y-1 overflow-auto text-sm">
                  {events.data.map((e) => (
                    <li key={e.id}>
                      <label className={cx("flex cursor-pointer items-center gap-2 rounded px-1", eventId === e.id && "bg-blue-50")}>
                        <input type="radio" name="event" checked={eventId === e.id} onChange={() => setEventId(e.id)} />
                        <Badge color="amber">{EVENT_KO[e.event_type] ?? e.event_type}</Badge>
                        <span className="text-xs">
                          {clock(s!.horizon_start, s!.timezone, e.event_time_min)} {e.affected_code ?? ""}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState>이벤트가 없습니다.</EmptyState>
              )}
            </Card>
            <Card title="3. 재스케줄">
              <div className="space-y-2 text-sm">
                <fieldset className="flex gap-3">
                  {["KEEP", "PARTIAL", "FULL"].map((p) => (
                    <label key={p} className="flex items-center gap-1">
                      <input type="checkbox" checked={policies.includes(p)} onChange={(e) => setPolicies(e.target.checked ? [...policies, p] : policies.filter((x) => x !== p))} />
                      {p}
                    </label>
                  ))}
                </fieldset>
                <Field label="확정(동결) 구간(분)" hint="이벤트 후 이 시간 내 시작 작업은 FULL에서도 유지">
                  <input className={inputCls} type="number" min={0} value={freeze} onChange={(e) => setFreeze(Number(e.target.value))} />
                </Field>
                <Field label="재최적화 알고리즘 (PARTIAL/FULL)">
                  <select className={inputCls} value={reopt} onChange={(e) => setReopt(e.target.value)}>
                    <option value="">기본값</option>
                    {reopts.map((a) => (
                      <option key={a.name}>{a.name}</option>
                    ))}
                  </select>
                </Field>
                {start.isError && <ErrorState error={start.error} />}
                <Button onClick={() => start.mutate()} disabled={!eventId || !policies.length || start.isPending}>
                  재스케줄 실행
                </Button>
              </div>
            </Card>
          </div>
          {eventId && (
            <Card title="4. 정책 비교 (같은 이벤트·같은 기준 실행)">
              {items.length === 0 ? (
                <EmptyState>재스케줄을 실행하세요.</EmptyState>
              ) : (
                <>
                  <table className="w-full text-sm">
                    <thead className="text-left text-xs text-ink-400">
                      <tr>
                        {["정책", "상태", "총비용(변경 페널티 포함)", "지연", "미처리", "변경 작업", "변경 경로", "안정성", "런타임", "버전", ""].map((h) => (
                          <th key={h}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((i) => (
                        <tr key={i.id} className={cx("border-t border-ink-100", rec?.recommended === i.policy && "bg-emerald-50")}>
                          <td className="py-1 font-medium">
                            {i.policy} {rec?.recommended === i.policy && <Badge color="green">추천</Badge>}
                          </td>
                          <td>
                            <Badge color={statusColor(i.status)}>{i.status}</Badge>
                          </td>
                          <td className="tabular-nums">{krw(i.total_cost)}</td>
                          <td>{i.late_min ?? "–"}분</td>
                          <td>{i.unserved ?? "–"}</td>
                          <td>{i.changed_tasks ?? "–"}</td>
                          <td>{i.changed_routes ?? "–"}</td>
                          <td>{i.stability_score ?? "–"}</td>
                          <td>{i.runtime_ms !== null ? `${(i.runtime_ms / 1000).toFixed(2)}s` : "–"}</td>
                          <td>v{i.schedule_version}</td>
                          <td>
                            <button className="text-xs text-accent-600 underline" onClick={() => setSelected(i.new_run_id)} disabled={i.status !== "SUCCEEDED"}>
                              전/후 비교
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <div className="rounded bg-ink-50 p-2 text-xs">
                      <div className="mb-1 font-medium text-ink-800">정책 추천 (규칙 기반 가중 점수)</div>
                      <div>{rec?.reason ?? "완료된 실행가능 결과가 없습니다."}</div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {(Object.keys(weights) as (keyof typeof weights)[]).map((k) => (
                          <label key={k} className="flex items-center gap-1">
                            {{ w_cost: "비용", w_lateness: "지연", w_changes: "변경", w_runtime: "시간" }[k]}
                            <input className="w-14 rounded border border-ink-200 px-1" type="number" step={0.1} min={0} value={weights[k]} onChange={(e) => setWeights({ ...weights, [k]: Number(e.target.value) })} />
                          </label>
                        ))}
                      </div>
                    </div>
                    <div className="rounded bg-ink-50 p-2 text-xs">
                      <div className="mb-1 font-medium text-ink-800">예외 · 동결 범위</div>
                      {items.map((i) => (
                        <div key={i.id}>
                          <b>{i.policy}</b>: 동결 작업 {i.summary?.frozen_tasks} / 재계획 {i.summary?.replanned_tasks} · 동결 경로 {i.summary?.frozen_routes} / 재계획 {i.summary?.replanned_routes}
                          {i.selection ? ` · ${i.selection}` : ""}
                        </div>
                      ))}
                      {(items[0]?.summary?.exceptions ?? []).map((x, k) => (
                        <div key={k} className="text-amber-800">
                          ⚠ {x}
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </Card>
          )}
          {selected && next.data && s && (
            <Card
              title={`5. 변경 전(#${baseId}) → 후(#${selected}) 비교`}
              actions={
                <Button
                  variant="secondary"
                  onClick={() => {
                    setRun(selected);
                    nav("/gantt");
                  }}
                >
                  이 버전을 간트에서 보기
                </Button>
              }
            >
              <DiffView base={s} next={next.data} />
            </Card>
          )}
        </>
      )}
    </div>
  );
}
