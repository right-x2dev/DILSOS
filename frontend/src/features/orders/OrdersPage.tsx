import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useDocks, useInvalidate, useOrders, useVehicles, useWorkers } from "../../api/hooks";
import { useSelectedScenario } from "../../components/ScenarioPicker";
import { Badge, Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, cx, inputCls } from "../../components/ui";
import type { Scenario } from "../../types/api";
import { fmtDateTime, localMin, parseHHMM } from "../../utils/time";
import { zonedToIso } from "../../utils/zoned";
import { CsvImport } from "./CsvImport";

const PRIO: Record<number, { label: string; color: "gray" | "amber" | "red" }> = {
  1: { label: "보통", color: "gray" },
  2: { label: "높음", color: "amber" },
  3: { label: "긴급", color: "red" },
};

function OrdersTable({ sc }: { sc: Scenario }) {
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 25;
  const orders = useOrders({ scenario_id: sc.id, status, priority, q, limit, offset });
  const tz = sc.facility.timezone;
  return (
    <Card
      title={`주문 (${orders.data?.total ?? "…"}건)`}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <input className={`${inputCls} w-36 py-1`} placeholder="주문/고객 코드" value={q} onChange={(e) => (setQ(e.target.value), setOffset(0))} aria-label="검색" />
          <select className={`${inputCls} w-28 py-1`} value={status} onChange={(e) => (setStatus(e.target.value), setOffset(0))} aria-label="상태 필터">
            <option value="">전체 상태</option>
            <option value="OPEN">OPEN</option>
            <option value="CANCELLED">CANCELLED</option>
            <option value="SHIPPED">SHIPPED</option>
          </select>
          <select className={`${inputCls} w-28 py-1`} value={priority} onChange={(e) => (setPriority(e.target.value), setOffset(0))} aria-label="우선순위 필터">
            <option value="">전체 우선순위</option>
            <option value="1">보통</option>
            <option value="2">높음</option>
            <option value="3">긴급</option>
          </select>
        </div>
      }
    >
      {orders.isLoading ? (
        <Spinner />
      ) : orders.isError ? (
        <ErrorState error={orders.error} />
      ) : !orders.data!.items.length ? (
        <EmptyState>조건에 맞는 주문이 없습니다.</EmptyState>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-ink-400">
                <tr>
                  <th className="py-1">주문</th>
                  <th>고객</th>
                  <th>입고(release)</th>
                  <th>출고마감(due)</th>
                  <th>우선순위</th>
                  <th>수량/중량</th>
                  <th>품목</th>
                  <th>상태</th>
                </tr>
              </thead>
              <tbody>
                {orders.data!.items.map((o) => (
                  <tr key={o.id} className="border-t border-ink-100">
                    <td className="py-1 font-mono text-xs">{o.code}</td>
                    <td className="text-xs">
                      {o.customer_code} <span className="text-ink-400">{o.customer_name}</span>
                    </td>
                    <td className="text-xs">{fmtDateTime(o.release_at, tz)}</td>
                    <td className="text-xs">{fmtDateTime(o.due_at, tz)}</td>
                    <td>
                      <Badge color={PRIO[o.priority].color}>{PRIO[o.priority].label}</Badge>
                    </td>
                    <td className="text-xs tabular-nums">
                      {o.units}개 · {o.weight_kg}kg
                    </td>
                    <td className="max-w-[12rem] truncate text-xs text-ink-600" title={o.lines.map((l) => `${l.sku_code}×${l.qty}`).join(", ")}>
                      {o.lines.map((l) => `${l.sku_code}×${l.qty}`).join(", ")}
                    </td>
                    <td className="text-xs">{o.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-2 flex items-center justify-between text-xs text-ink-600">
            <span>
              {offset + 1}–{Math.min(offset + limit, orders.data!.total)} / {orders.data!.total} (표시 시간대 {tz})
            </span>
            <span className="flex gap-1">
              <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>
                이전
              </Button>
              <Button variant="secondary" disabled={offset + limit >= orders.data!.total} onClick={() => setOffset(offset + limit)}>
                다음
              </Button>
            </span>
          </div>
        </>
      )}
    </Card>
  );
}

function NewOrderForm({ sc }: { sc: Scenario }) {
  const inv = useInvalidate();
  const [f, setF] = useState({ code: "", customer_code: "", release: "08:00", due: "12:00", priority: 1, sku: "", qty: 1 });
  const m = useMutation({
    mutationFn: () =>
      api("/orders", {
        body: {
          scenario_id: sc.id,
          code: f.code,
          customer_code: f.customer_code,
          release_at: zonedToIso(sc.operating_date, f.release, sc.facility.timezone),
          due_at: zonedToIso(sc.operating_date, f.due, sc.facility.timezone),
          priority: f.priority,
          lines: [{ sku_code: f.sku, qty: f.qty }],
        },
      }),
    onSuccess: () => inv(["orders"], ["scenarios"], ["dashboard"]),
  });
  const bad = parseHHMM(f.release) === null || parseHHMM(f.due) === null;
  function submit(e: FormEvent) {
    e.preventDefault();
    m.mutate();
  }
  return (
    <form onSubmit={submit} className="space-y-2" aria-label="주문 생성">
      <div className="grid grid-cols-2 gap-2">
        <Field label="주문 코드">
          <input className={inputCls} required pattern="[A-Za-z0-9_\-]+" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} />
        </Field>
        <Field label="고객 코드" hint="예: C001">
          <input className={inputCls} required value={f.customer_code} onChange={(e) => setF({ ...f, customer_code: e.target.value })} />
        </Field>
        <Field label={`입고 시각 (${sc.facility.timezone})`}>
          <input className={inputCls} required value={f.release} onChange={(e) => setF({ ...f, release: e.target.value })} />
        </Field>
        <Field label="출고 마감">
          <input className={inputCls} required value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} />
        </Field>
        <Field label="SKU" hint="예: SKU001">
          <input className={inputCls} required value={f.sku} onChange={(e) => setF({ ...f, sku: e.target.value })} />
        </Field>
        <Field label="수량">
          <input className={inputCls} type="number" min={1} required value={f.qty} onChange={(e) => setF({ ...f, qty: Number(e.target.value) })} />
        </Field>
        <Field label="우선순위">
          <select className={inputCls} value={f.priority} onChange={(e) => setF({ ...f, priority: Number(e.target.value) })}>
            <option value={1}>보통</option>
            <option value={2}>높음</option>
            <option value={3}>긴급</option>
          </select>
        </Field>
      </div>
      {bad && <div className="text-xs text-red-700">시각은 HH:MM 형식</div>}
      {m.isError && <ErrorState error={m.error} />}
      {m.isSuccess && <div className="text-xs text-emerald-700">주문이 생성되어 시나리오에 추가되었습니다 (다음 실행 시 새 스냅샷 버전).</div>}
      <Button type="submit" disabled={m.isPending || bad}>
        주문 추가
      </Button>
    </form>
  );
}

function ResourceTabs({ sc }: { sc: Scenario }) {
  const [tab, setTab] = useState<"workers" | "vehicles" | "docks">("workers");
  const fid = sc.facility.id;
  const workers = useWorkers(fid);
  const vehicles = useVehicles(fid);
  const docks = useDocks(fid);
  const inv = useInvalidate();
  const [w, setW] = useState({ code: "", name: "", skills: "pick,pack", hourly_cost: 15000, start: "08:00", end: "17:00" });
  const addW = useMutation({
    mutationFn: () =>
      api("/resources/workers", {
        body: {
          facility_id: fid,
          code: w.code,
          name: w.name,
          skills: w.skills.split(",").map((s) => s.trim()).filter(Boolean),
          hourly_cost: w.hourly_cost,
          shift_start_local_min: parseHHMM(w.start),
          shift_end_local_min: parseHHMM(w.end),
        },
      }),
    onSuccess: () => inv(["workers", fid], ["scenarios"]),
  });
  const [v, setV] = useState({ code: "", vehicle_class: "van", capacity_kg: 700, capacity_l: 4000, fixed_cost: 70000, cost_per_km: 850 });
  const addV = useMutation({
    mutationFn: () => api("/resources/vehicles", { body: { facility_id: fid, ...v, shift_start_local_min: 480, shift_end_local_min: 1320 } }),
    onSuccess: () => inv(["vehicles", fid], ["scenarios"]),
  });
  const [d, setD] = useState({ code: "", name: "", classes: "van,truck" });
  const addD = useMutation({
    mutationFn: () =>
      api("/resources/docks", {
        body: { facility_id: fid, code: d.code, name: d.name || d.code, vehicle_classes: d.classes.split(",").map((s) => s.trim()), open_start_local_min: 420, open_end_local_min: 1290 },
      }),
    onSuccess: () => inv(["docks", fid], ["scenarios"]),
  });
  const tabBtn = (id: typeof tab, label: string, n?: number) => (
    <button role="tab" aria-selected={tab === id} onClick={() => setTab(id)} className={cx("rounded-md px-3 py-1 text-sm", tab === id ? "bg-tower-700 text-white" : "text-ink-600 hover:bg-ink-100")}>
      {label} {n !== undefined && <span className="text-xs opacity-70">({n})</span>}
    </button>
  );
  return (
    <Card title={`자원 — ${sc.facility.code}`} actions={<div role="tablist" className="flex gap-1">{tabBtn("workers", "작업자", workers.data?.length)}{tabBtn("vehicles", "차량", vehicles.data?.length)}{tabBtn("docks", "도크", docks.data?.length)}</div>}>
      {tab === "workers" && (
        <>
          {workers.isError && <ErrorState error={workers.error} />}
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-ink-400">
              <tr>
                <th>코드</th>
                <th>이름</th>
                <th>기술</th>
                <th>교대(현지)</th>
                <th>정규 종료</th>
                <th>시급</th>
              </tr>
            </thead>
            <tbody>
              {(workers.data ?? []).map((x) => (
                <tr key={x.id} className="border-t border-ink-100">
                  <td className="py-1 font-mono text-xs">{x.code}</td>
                  <td>{x.name}</td>
                  <td className="text-xs">{x.skills.join(", ")}</td>
                  <td className="text-xs">
                    {localMin(x.shift_start_local_min)}–{localMin(x.shift_end_local_min)}
                  </td>
                  <td className="text-xs">{x.regular_end_local_min !== null ? localMin(x.regular_end_local_min) : "–"}</td>
                  <td className="text-xs tabular-nums">₩{x.hourly_cost.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <form className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-6" onSubmit={(e) => (e.preventDefault(), addW.mutate())} aria-label="작업자 추가">
            <input className={inputCls} placeholder="코드" required value={w.code} onChange={(e) => setW({ ...w, code: e.target.value })} />
            <input className={inputCls} placeholder="이름" required value={w.name} onChange={(e) => setW({ ...w, name: e.target.value })} />
            <input className={inputCls} placeholder="기술 pick,pack,cold" value={w.skills} onChange={(e) => setW({ ...w, skills: e.target.value })} />
            <input className={inputCls} placeholder="시작 HH:MM" value={w.start} onChange={(e) => setW({ ...w, start: e.target.value })} />
            <input className={inputCls} placeholder="종료 HH:MM (+24h=익일)" value={w.end} onChange={(e) => setW({ ...w, end: e.target.value })} />
            <Button type="submit" disabled={addW.isPending}>
              작업자 추가
            </Button>
          </form>
          {addW.isError && <ErrorState error={addW.error} />}
        </>
      )}
      {tab === "vehicles" && (
        <>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-ink-400">
              <tr>
                <th>코드</th>
                <th>유형</th>
                <th>용량</th>
                <th>고정비 / km당</th>
                <th>근무</th>
                <th>상태</th>
              </tr>
            </thead>
            <tbody>
              {(vehicles.data ?? []).map((x) => (
                <tr key={x.id} className="border-t border-ink-100">
                  <td className="py-1 font-mono text-xs">{x.code}</td>
                  <td>{x.vehicle_class}</td>
                  <td className="text-xs">
                    {x.capacity_kg}kg · {x.capacity_l}L
                  </td>
                  <td className="text-xs">
                    ₩{x.fixed_cost.toLocaleString()} / ₩{x.cost_per_km}
                  </td>
                  <td className="text-xs">
                    {localMin(x.shift_start_local_min)}–{localMin(x.shift_end_local_min)}
                  </td>
                  <td>
                    <Badge color={x.status === "AVAILABLE" ? "green" : "red"}>{x.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <form className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-5" onSubmit={(e) => (e.preventDefault(), addV.mutate())} aria-label="차량 추가">
            <input className={inputCls} placeholder="코드" required value={v.code} onChange={(e) => setV({ ...v, code: e.target.value })} />
            <select className={inputCls} value={v.vehicle_class} onChange={(e) => setV({ ...v, vehicle_class: e.target.value })}>
              <option value="van">van</option>
              <option value="truck">truck</option>
            </select>
            <input className={inputCls} type="number" placeholder="kg" value={v.capacity_kg} onChange={(e) => setV({ ...v, capacity_kg: Number(e.target.value) })} />
            <input className={inputCls} type="number" placeholder="L" value={v.capacity_l} onChange={(e) => setV({ ...v, capacity_l: Number(e.target.value) })} />
            <Button type="submit" disabled={addV.isPending}>
              차량 추가 (08:00–22:00)
            </Button>
          </form>
          {addV.isError && <ErrorState error={addV.error} />}
        </>
      )}
      {tab === "docks" && (
        <>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-ink-400">
              <tr>
                <th>코드</th>
                <th>이름</th>
                <th>허용 차종</th>
                <th>운영</th>
              </tr>
            </thead>
            <tbody>
              {(docks.data ?? []).map((x) => (
                <tr key={x.id} className="border-t border-ink-100">
                  <td className="py-1 font-mono text-xs">{x.code}</td>
                  <td>{x.name}</td>
                  <td className="text-xs">{x.vehicle_classes.join(", ")}</td>
                  <td className="text-xs">
                    {localMin(x.open_start_local_min)}–{localMin(x.open_end_local_min)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <form className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4" onSubmit={(e) => (e.preventDefault(), addD.mutate())} aria-label="도크 추가">
            <input className={inputCls} placeholder="코드" required value={d.code} onChange={(e) => setD({ ...d, code: e.target.value })} />
            <input className={inputCls} placeholder="이름" value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} />
            <input className={inputCls} placeholder="van,truck" value={d.classes} onChange={(e) => setD({ ...d, classes: e.target.value })} />
            <Button type="submit" disabled={addD.isPending}>
              도크 추가 (07:00–21:30)
            </Button>
          </form>
          {addD.isError && <ErrorState error={addD.error} />}
        </>
      )}
      <p className="mt-2 text-xs text-ink-400">자원 변경은 시설 마스터데이터에 반영되며, 다음 실행부터 새 스냅샷 버전으로 고정됩니다(과거 실행은 영향 없음).</p>
    </Card>
  );
}

export function OrdersPage() {
  const sc = useSelectedScenario();
  if (!sc) return <EmptyState>시나리오를 선택하세요.</EmptyState>;
  return (
    <div className="space-y-4">
      <PageHeader title="주문 · 자원" subtitle={`${sc.name} · ${sc.facility.name}`} />
      <OrdersTable sc={sc} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="주문 추가">
          <NewOrderForm sc={sc} />
        </Card>
        <Card title="CSV 주문 가져오기">
          <CsvImport sc={sc} />
        </Card>
      </div>
      <ResourceTabs sc={sc} />
    </div>
  );
}
