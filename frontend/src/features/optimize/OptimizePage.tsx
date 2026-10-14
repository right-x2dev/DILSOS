import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAlgorithms, useCancelRun, useCreateRun, useRun } from "../../api/hooks";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Kpi, PageHeader, inputCls, statusColor } from "../../components/ui";
import { useSelectedScenario } from "../../components/ScenarioPicker";
import { useUi } from "../../store/ui";
import type { Run } from "../../types/api";
import { fmtDuration, krw, pct } from "../../utils/time";

const PROBLEMS = [
  { id: "warehouse", label: "창고 (피킹·패킹)" },
  { id: "dock", label: "도크 (창고 + 도크 + 고정 경로)" },
  { id: "routing", label: "배송 경로 (VRPTW)" },
  { id: "integrated", label: "통합 (창고→도크→배송)" },
];

const VIEW_FOR: Record<string, { to: string; label: string }[]> = {
  warehouse: [{ to: "/gantt", label: "창고 간트" }],
  dock: [
    { to: "/gantt", label: "창고 간트" },
    { to: "/docks", label: "도크 타임라인" },
  ],
  routing: [{ to: "/routes", label: "배송 경로" }],
  integrated: [
    { to: "/gantt", label: "창고 간트" },
    { to: "/docks", label: "도크" },
    { to: "/routes", label: "경로" },
    { to: "/journey", label: "통합 타임라인" },
  ],
};

export function OptimizePage() {
  const sc = useSelectedScenario();
  const algos = useAlgorithms();
  const [problem, setProblem] = useState("warehouse");
  const [algorithm, setAlgorithm] = useState("");
  const [timeLimit, setTimeLimit] = useState(10);
  const [seed, setSeed] = useState(0);
  const [runId, setRunId] = useState<number | null>(null);
  const setGlobalRun = useUi((s) => s.setRun);
  const create = useCreateRun(sc?.id ?? null);
  const run = useRun(runId);
  const cancel = useCancelRun();

  const options = useMemo(() => (algos.data ?? []).filter((a) => a.problem_types.includes(problem)), [algos.data, problem]);
  useEffect(() => {
    if (options.length && !options.some((o) => o.name === algorithm)) setAlgorithm(options[0].name);
  }, [options, algorithm]);
  useEffect(() => {
    if (run.data?.status === "SUCCEEDED") setGlobalRun(run.data.id);
  }, [run.data?.status, run.data?.id, setGlobalRun]);

  const selected = options.find((o) => o.name === algorithm);
  const busy = run.data && ["QUEUED", "RUNNING"].includes(run.data.status);

  async function submit() {
    const r = await create.mutateAsync({ problem_type: problem, algorithm, time_limit_s: timeLimit, seed });
    setRunId(r.id);
  }

  return (
    <div className="space-y-4">
      <PageHeader title="최적화 실행 콘솔" subtitle={sc ? `시나리오 #${sc.id} ${sc.name} · 주문 ${sc.order_count}건` : "시나리오를 선택하세요"} />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="실행 설정">
          <div className="space-y-3">
            <Field label="문제 유형">
              <select className={inputCls} value={problem} onChange={(e) => setProblem(e.target.value)} aria-label="문제 유형">
                {PROBLEMS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="알고리즘" hint={selected ? `${selected.kind} · ${selected.description}` : undefined}>
              {options.length ? (
                <select className={inputCls} value={algorithm} onChange={(e) => setAlgorithm(e.target.value)} aria-label="알고리즘">
                  {options.map((a) => (
                    <option key={a.name} value={a.name} disabled={!a.available}>
                      {a.name} {a.available ? "" : "(솔버 없음)"}
                    </option>
                  ))}
                </select>
              ) : (
                <div className="rounded border border-dashed border-ink-200 p-2 text-xs text-ink-400">이 문제 유형의 알고리즘은 아직 구현되지 않았습니다 (준비 중).</div>
              )}
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="시간 제한(초)" hint="솔버 예산(벽시계)">
                <input className={inputCls} type="number" min={1} max={120} value={timeLimit} onChange={(e) => setTimeLimit(Number(e.target.value))} />
              </Field>
              <Field label="시드" hint="재현성">
                <input className={inputCls} type="number" min={0} value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
              </Field>
            </div>
            {create.isError && <ErrorState error={create.error} />}
            <Button onClick={submit} disabled={!sc || !options.length || !selected?.available || create.isPending || !!busy} className="w-full justify-center">
              {create.isPending ? "큐에 등록 중…" : "실행 (비동기 큐)"}
            </Button>
            <p className="text-xs text-ink-400">요청은 202로 큐에 등록되고 워커가 실행합니다. 결과는 독립 검증기를 통과해야만 게시(SUCCEEDED)됩니다.</p>
          </div>
        </Card>
        <div className="lg:col-span-2">
          {runId === null ? (
            <EmptyState>실행을 시작하면 진행 상태·검증 결과·솔버 메타데이터가 여기에 표시됩니다.</EmptyState>
          ) : run.isLoading ? (
            <Card title={`실행 #${runId}`}>불러오는 중…</Card>
          ) : run.isError ? (
            <ErrorState error={run.error} />
          ) : (
            <RunStatusCard run={run.data!} onCancel={() => cancel.mutate(run.data!.id)} cancelling={cancel.isPending} />
          )}
        </div>
      </div>
    </div>
  );
}

export function RunStatusCard({ run, onCancel, cancelling }: { run: Run; onCancel?: () => void; cancelling?: boolean }) {
  const active = run.status === "QUEUED" || run.status === "RUNNING";
  const k = run.kpis;
  const md = run.solver_metadata ?? {};
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          실행 #{run.id} · {run.algorithm}
          <Badge color={statusColor(run.status)}>{run.status}</Badge>
          {run.solver_status && <Badge color={statusColor(run.solver_status)} title="솔버 수준 상태 (실행 상태와 별도)">solver: {run.solver_status}</Badge>}
        </span>
      }
      actions={
        active && onCancel ? (
          <Button variant="danger" onClick={onCancel} disabled={cancelling || run.cancel_requested}>
            {run.cancel_requested ? "취소 요청됨" : "취소"}
          </Button>
        ) : null
      }
    >
      {active && (
        <div className="mb-3" role="progressbar" aria-valuenow={run.progress} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-2 rounded bg-ink-100">
            <div className="h-2 animate-pulse rounded bg-accent-500" style={{ width: `${Math.max(5, run.progress)}%` }} />
          </div>
          <div className="mt-1 text-xs text-ink-600">{run.status === "QUEUED" ? "워커 대기 중 (큐)…" : `솔버 실행 중… (제한 ${run.time_limit_s}s)`}</div>
        </div>
      )}
      {run.error_message && (
        <div role="alert" className="mb-3 rounded border border-red-200 bg-red-50 p-2 text-sm text-red-800">
          {run.error_message}
        </div>
      )}
      {k && (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Kpi label="총비용(공통 평가기)" value={krw(k.cost.total_cost)} />
          <Kpi label="정시율" value={pct(k.on_time_rate)} />
          <Kpi label="총 지연" value={fmtDuration(k.total_lateness_min)} />
          <Kpi label="미처리" value={k.orders_unserved} unit="건" />
          <Kpi label="창고 makespan" value={fmtDuration(k.warehouse_makespan_min)} />
          <Kpi label="총 거리" value={k.total_distance_km ? k.total_distance_km.toFixed(1) : "–"} unit={k.total_distance_km ? "km" : undefined} />
          <Kpi label="차량" value={k.vehicles_used} unit="대" />
          <Kpi label="런타임" value={run.runtime_ms !== null ? (run.runtime_ms / 1000).toFixed(2) : "–"} unit="s" />
        </div>
      )}
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="text-sm">
          <div className="mb-1 font-medium">검증 (feasibility)</div>
          {run.validation_summary ? (
            <div>
              <Badge color={run.validation_summary.is_feasible ? "green" : "red"}>{run.validation_summary.is_feasible ? "실행가능 (검증 통과)" : "검증 실패"}</Badge>
              <span className="ml-2 text-xs text-ink-600">
                범위 {(run.validation_summary.scope as string[]).join("+")} · 오류 {String(run.validation_summary.errors)} · 경고 {String(run.validation_summary.warnings)}
              </span>
            </div>
          ) : (
            <span className="text-xs text-ink-400">아직 없음</span>
          )}
        </div>
        <div className="text-sm">
          <div className="mb-1 font-medium">솔버 메타데이터</div>
          <dl className="grid grid-cols-2 gap-x-2 text-xs text-ink-600">
            {Object.entries(md)
              .filter(([, v]) => typeof v !== "object" || v === null)
              .slice(0, 14)
              .map(([kk, v]) => (
                <div key={kk} className="contents">
                  <dt className="truncate text-ink-400">{kk}</dt>
                  <dd className="truncate tabular-nums">{String(v)}</dd>
                </div>
              ))}
          </dl>
        </div>
      </div>
      {run.status === "SUCCEEDED" && (
        <div className="mt-3 flex flex-wrap gap-2 text-sm">
          {(VIEW_FOR[run.problem_type] ?? []).map((v) => (
            <Link key={v.to} to={v.to} className="rounded border border-accent-500 px-2 py-1 text-accent-600 hover:bg-blue-50">
              {v.label} 보기 →
            </Link>
          ))}
          <Link to={`/runs?run=${run.id}`} className="rounded border border-ink-200 px-2 py-1 text-ink-600 hover:bg-ink-50">
            상세/감사
          </Link>
        </div>
      )}
    </Card>
  );
}
