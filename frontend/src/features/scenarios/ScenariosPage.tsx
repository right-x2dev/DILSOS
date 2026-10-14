import { useEffect, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useInvalidate, useScenario, useScenarios, useValidateScenario } from "../../api/hooks";
import { Badge, Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, inputCls } from "../../components/ui";
import { useUi } from "../../store/ui";
import type { InputValidation, ObjectiveWeights, Scenario } from "../../types/api";
import { fmtDateTime } from "../../utils/time";

type Builder = {
  name: string;
  seed: number;
  n_orders: number;
  n_workers: number;
  n_pack_stations: number;
  n_docks: number;
  n_vans: number;
  n_trucks: number;
  area_km: number;
  deadline_tightness: number;
  inventory_shortage_skus: number;
  time_window_mode: "soft" | "hard";
};

const DEFAULT_B: Builder = {
  name: "새 합성 시나리오",
  seed: 1,
  n_orders: 30,
  n_workers: 5,
  n_pack_stations: 2,
  n_docks: 2,
  n_vans: 3,
  n_trucks: 1,
  area_km: 15,
  deadline_tightness: 1,
  inventory_shortage_skus: 0,
  time_window_mode: "soft",
};

function BuilderForm({ onCreated }: { onCreated: (s: Scenario) => void }) {
  const [b, setB] = useState<Builder>(DEFAULT_B);
  const inv = useInvalidate();
  const m = useMutation({
    mutationFn: (body: Builder) => api<Scenario>("/scenarios", { body }),
    onSuccess: (s) => {
      inv(["scenarios"]);
      onCreated(s);
    },
  });
  const num = (k: keyof Builder, label: string, min: number, max: number, step = 1, hint?: string) => (
    <Field label={label} hint={hint}>
      <input
        className={inputCls}
        type="number"
        min={min}
        max={max}
        step={step}
        value={b[k] as number}
        required
        onChange={(e) => setB({ ...b, [k]: Number(e.target.value) })}
      />
    </Field>
  );
  function submit(e: FormEvent) {
    e.preventDefault();
    m.mutate(b);
  }
  return (
    <form onSubmit={submit} className="space-y-3" aria-label="시나리오 빌더">
      <Field label="이름">
        <input className={inputCls} value={b.name} required maxLength={120} onChange={(e) => setB({ ...b, name: e.target.value })} />
      </Field>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
        {num("seed", "시드", 0, 2147483647, 1, "같은 시드 = 같은 데이터")}
        {num("n_orders", "주문 수", 1, 500)}
        {num("n_workers", "작업자", 1, 60)}
        {num("n_pack_stations", "포장대", 1, 20)}
        {num("n_docks", "도크", 1, 10)}
        {num("n_vans", "밴", 0, 50)}
        {num("n_trucks", "트럭", 0, 20)}
        {num("area_km", "배송 반경(km)", 1, 100, 0.5, "합성 좌표")}
        {num("deadline_tightness", "마감 강도", 0.5, 3, 0.1, ">1 이면 타이트")}
        {num("inventory_shortage_skus", "재고부족 SKU", 0, 20)}
        <Field label="시간창 모드" hint="종료시각 hard/soft">
          <select className={inputCls} value={b.time_window_mode} onChange={(e) => setB({ ...b, time_window_mode: e.target.value as "soft" | "hard" })}>
            <option value="soft">soft (지연 페널티)</option>
            <option value="hard">hard (위반 불가)</option>
          </select>
        </Field>
      </div>
      {m.isError && <ErrorState error={m.error} />}
      <Button type="submit" disabled={m.isPending}>
        {m.isPending ? "생성 중…" : "생성 및 저장"}
      </Button>
      <p className="text-xs text-ink-400">결정론적 합성 생성기로 시설·주문·자원·교대·도크·차량·이동행렬(합성 유클리드)을 만들고 MySQL에 저장합니다.</p>
    </form>
  );
}

function WeightsForm({ sc }: { sc: Scenario }) {
  const [w, setW] = useState<ObjectiveWeights>(sc.weights);
  const [mode, setMode] = useState(sc.params.time_window_mode);
  const [seed, setSeed] = useState(sc.seed);
  const inv = useInvalidate();
  useEffect(() => {
    setW(sc.weights);
    setMode(sc.params.time_window_mode);
    setSeed(sc.seed);
  }, [sc]);
  const m = useMutation({
    mutationFn: () => api<Scenario>(`/scenarios/${sc.id}`, { method: "PATCH", body: { version: sc.version, weights: w, seed, params: { ...sc.params, time_window_mode: mode } } }),
    onSuccess: () => inv(["scenarios"], ["scenario", sc.id]),
  });
  const f = (k: keyof ObjectiveWeights, label: string, unit: string) => (
    <Field label={label} hint={unit}>
      <input className={inputCls} type="number" min={0} step="any" value={w[k] as number} onChange={(e) => setW({ ...w, [k]: Number(e.target.value) })} />
    </Field>
  );
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        {f("late_penalty_per_min", "지연 페널티", "원/분 × 우선순위")}
        {f("unserved_penalty", "미처리 페널티", "원/주문 × 우선순위")}
        {f("overtime_premium", "초과근무 할증", "시급 대비 비율")}
        {f("change_penalty_per_task", "작업 변경 페널티", "원/작업")}
        {f("change_penalty_per_route", "경로 변경 페널티", "원/경로")}
        <Field label="시드">
          <input className={inputCls} type="number" min={0} value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
        </Field>
        <Field label="시간창 종료 모드">
          <select className={inputCls} value={mode} onChange={(e) => setMode(e.target.value as "soft" | "hard")}>
            <option value="soft">soft</option>
            <option value="hard">hard</option>
          </select>
        </Field>
      </div>
      {m.isError && <ErrorState error={m.error} />}
      {m.isSuccess && <div className="text-xs text-emerald-700">저장됨 (버전 {m.data.version})</div>}
      <Button onClick={() => m.mutate()} disabled={m.isPending}>
        저장 (낙관적 동시성 v{sc.version})
      </Button>
    </div>
  );
}

function ValidationView({ v }: { v: InputValidation }) {
  return (
    <div className="space-y-2 text-sm">
      <Badge color={v.ok ? "green" : "red"}>{v.ok ? "입력 유효" : "입력 오류 있음"}</Badge>
      <div className="text-xs text-ink-600">
        주문 {String(v.summary.orders)} · 작업 {String(v.summary.tasks)} · 서비스 가능 {String(v.summary.servable_orders)} · 스냅샷 v{String(v.summary.snapshot_version)} ·
        이동행렬 {String(v.summary.travel_provenance)}
      </div>
      {v.issues.length ? (
        <ul className="max-h-48 overflow-auto text-xs">
          {v.issues.map((i, k) => (
            <li key={k} className="border-t border-ink-100 py-0.5">
              <Badge color={i.severity === "error" ? "red" : i.severity === "warning" ? "amber" : "gray"}>{i.severity}</Badge> {i.entity}: {i.message}
            </li>
          ))}
        </ul>
      ) : (
        <div className="text-xs text-ink-400">이슈 없음</div>
      )}
    </div>
  );
}

export function ScenariosPage() {
  const list = useScenarios();
  const { scenarioId, setScenario } = useUi();
  const detail = useScenario(scenarioId);
  const validate = useValidateScenario();
  const inv = useInvalidate();
  const [cloneName, setCloneName] = useState("");
  const clone = useMutation({
    mutationFn: () => api<Scenario>(`/scenarios/${scenarioId}/clone`, { body: { name: cloneName || `clone of #${scenarioId}` } }),
    onSuccess: (s) => {
      inv(["scenarios"]);
      setScenario(s.id);
      setCloneName("");
    },
  });
  return (
    <div className="space-y-4">
      <PageHeader title="시나리오" subtitle="스냅샷 기반: 실행마다 입력이 불변 스냅샷으로 저장되어 재현 가능합니다." />
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="시나리오 목록" className="xl:col-span-2">
          {list.isLoading ? (
            <Spinner />
          ) : list.isError ? (
            <ErrorState error={list.error} />
          ) : list.data!.items.length === 0 ? (
            <EmptyState>
              시나리오가 없습니다. 오른쪽 빌더로 생성하거나 <code>python -m app.seed.cli demo-scenarios</code> 로 데모를 시드하세요.
            </EmptyState>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-ink-400">
                  <tr>
                    <th className="py-1">#</th>
                    <th>이름</th>
                    <th>시설</th>
                    <th>운영일</th>
                    <th>주문</th>
                    <th>자원 (작업자/포장/도크/차량)</th>
                    <th>스냅샷</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data!.items.map((s) => (
                    <tr
                      key={s.id}
                      className={`cursor-pointer border-t border-ink-100 hover:bg-ink-50 ${s.id === scenarioId ? "bg-blue-50" : ""}`}
                      onClick={() => setScenario(s.id)}
                      aria-selected={s.id === scenarioId}
                    >
                      <td className="py-1.5">{s.id}</td>
                      <td>
                        <div className="font-medium">{s.name}</div>
                        <div className="max-w-xs truncate text-xs text-ink-400">{s.description}</div>
                      </td>
                      <td className="text-xs">{s.facility.code}</td>
                      <td className="text-xs">{s.operating_date}</td>
                      <td className="tabular-nums">{s.order_count}</td>
                      <td className="text-xs tabular-nums">
                        {s.resource_counts.workers}/{s.resource_counts.pack_stations}/{s.resource_counts.docks}/{s.resource_counts.vehicles}
                      </td>
                      <td className="text-xs">v{s.snapshot_versions}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card title="시나리오 빌더 (합성 생성기)">
          <BuilderForm onCreated={(s) => setScenario(s.id)} />
        </Card>
      </div>
      {detail.data && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title={`#${detail.data.id} ${detail.data.name} — 설정`}>
            <dl className="grid grid-cols-2 gap-1 text-sm">
              <dt className="text-ink-400">시간대</dt>
              <dd>{detail.data.facility.timezone}</dd>
              <dt className="text-ink-400">계획 시작</dt>
              <dd>{fmtDateTime(detail.data.horizon_start, detail.data.facility.timezone)}</dd>
              <dt className="text-ink-400">계획 길이</dt>
              <dd>{detail.data.horizon_min}분</dd>
              <dt className="text-ink-400">적재 시간</dt>
              <dd>
                {detail.data.params.load_base_min}분 + {detail.data.params.load_per_order_min}분/주문
              </dd>
              <dt className="text-ink-400">이동행렬</dt>
              <dd className="text-xs">
                {String(detail.data.travel_params.provenance)} × {String(detail.data.travel_params.circuity)} @ {String(detail.data.travel_params.speed_kmh)}km/h
              </dd>
              <dt className="text-ink-400">부모</dt>
              <dd>{detail.data.parent_scenario_id ? `#${detail.data.parent_scenario_id}` : "–"}</dd>
              <dt className="text-ink-400">생성</dt>
              <dd className="text-xs">{fmtDateTime(detail.data.created_at)}</dd>
            </dl>
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <input className={`${inputCls} w-40`} placeholder="복제 이름" value={cloneName} onChange={(e) => setCloneName(e.target.value)} aria-label="복제 이름" />
              <Button variant="secondary" onClick={() => clone.mutate()} disabled={clone.isPending}>
                복제
              </Button>
              <Button variant="secondary" onClick={() => validate.mutate(detail.data!.id)} disabled={validate.isPending}>
                {validate.isPending ? "검증 중…" : "입력 검증"}
              </Button>
            </div>
            {clone.isError && <ErrorState error={clone.error} />}
          </Card>
          <Card title="목적함수 가중치 · 시드 · 시간창">
            <WeightsForm sc={detail.data} />
          </Card>
          <Card title="입력 검증 결과">
            {validate.isError ? <ErrorState error={validate.error} /> : validate.data ? <ValidationView v={validate.data} /> : <EmptyState>“입력 검증”을 누르세요.</EmptyState>}
          </Card>
        </div>
      )}
    </div>
  );
}
