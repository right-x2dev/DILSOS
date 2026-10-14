import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { api } from "../../api/client";
import { useAlgorithms, useCompare, useInvalidate, useRuns } from "../../api/hooks";
import { Badge, Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, cx, inputCls, statusColor } from "../../components/ui";
import { useSelectedScenario } from "../../components/ScenarioPicker";
import type { CompareRow } from "../../types/api";
import { krw, pct } from "../../utils/time";

const COST_KEYS: [keyof NonNullable<CompareRow["cost"]>, string, string][] = [
  ["labor_cost", "인건비", "#2563eb"],
  ["overtime_cost", "초과근무", "#60a5fa"],
  ["transport_fixed", "차량 고정비", "#059669"],
  ["distance_cost", "거리비", "#34d399"],
  ["late_delivery_penalty", "지연 페널티", "#dc2626"],
  ["unserved_penalty", "미처리 페널티", "#7c3aed"],
  ["schedule_change_penalty", "변경 페널티", "#d97706"],
];

export type AlgoStat = { algorithm: string; n: number; feasible: number; best: number | null; mean: number | null; std: number | null; meanRuntime: number | null };

/** Per-algorithm statistics over the compared runs (best / mean / population std, feasibility). */
export function algoStats(rows: CompareRow[]): AlgoStat[] {
  const by = new Map<string, CompareRow[]>();
  for (const r of rows) by.set(r.algorithm, [...(by.get(r.algorithm) ?? []), r]);
  return [...by.entries()]
    .map(([algorithm, rs]) => {
      const ok = rs.filter((r) => r.is_feasible && r.status === "SUCCEEDED" && r.total_cost !== null).map((r) => r.total_cost!);
      const mean = ok.length ? ok.reduce((a, b) => a + b, 0) / ok.length : null;
      const std = ok.length > 1 && mean !== null ? Math.sqrt(ok.reduce((a, b) => a + (b - mean) ** 2, 0) / ok.length) : ok.length ? 0 : null;
      const rts = rs.filter((r) => r.runtime_ms !== null).map((r) => r.runtime_ms! / 1000);
      return { algorithm, n: rs.length, feasible: ok.length, best: ok.length ? Math.min(...ok) : null, mean, std, meanRuntime: rts.length ? rts.reduce((a, b) => a + b, 0) / rts.length : null };
    })
    .sort((a, b) => (a.mean ?? Infinity) - (b.mean ?? Infinity));
}

export function toCsv(rows: CompareRow[]): string {
  const cols = ["run_id", "algorithm", "problem_type", "status", "solver_status", "is_feasible", "seed", "runtime_ms", "total_cost", "on_time_rate", "total_lateness_min", "total_distance_km", "vehicles_used", "orders_unserved", "warehouse_makespan_min", "end_to_end_makespan_min", "changed_tasks", "stability_score", "gap"] as const;
  const esc = (v: unknown) => (v === null || v === undefined ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
}

function ExperimentForm({ scenarioId, onDone }: { scenarioId: number; onDone: (ids: number[]) => void }) {
  const algos = useAlgorithms();
  const inv = useInvalidate();
  const [problem, setProblem] = useState("routing");
  const [sel, setSel] = useState<string[]>([]);
  const [seeds, setSeeds] = useState(3);
  const [tl, setTl] = useState(5);
  const options = (algos.data ?? []).filter((a) => a.problem_types.includes(problem) && a.available);
  const m = useMutation({
    mutationFn: () =>
      api<{ run_ids: number[] }>(`/scenarios/${scenarioId}/experiments`, {
        body: { problem_type: problem, algorithms: sel, seeds: Array.from({ length: seeds }, (_, i) => i), time_limit_s: tl, params: { max_evaluations: 800, max_iterations: 200 } },
      }),
    onSuccess: (r) => {
      inv(["runs", scenarioId]);
      onDone(r.run_ids);
    },
  });
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-3 gap-2">
        <Field label="문제 유형">
          <select className={inputCls} value={problem} onChange={(e) => (setProblem(e.target.value), setSel([]))}>
            {["warehouse", "dock", "routing", "integrated"].map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </Field>
        <Field label="시드 수" hint="확률적 알고리즘만 반복">
          <input className={inputCls} type="number" min={1} max={20} value={seeds} onChange={(e) => setSeeds(Number(e.target.value))} />
        </Field>
        <Field label="시간 제한(초)">
          <input className={inputCls} type="number" min={1} max={60} value={tl} onChange={(e) => setTl(Number(e.target.value))} />
        </Field>
      </div>
      <fieldset className="flex flex-wrap gap-3 text-sm">
        <legend className="mb-1 text-xs text-ink-600">알고리즘 (동일 스냅샷·동일 평가기)</legend>
        {options.map((a) => (
          <label key={a.name} className="flex items-center gap-1">
            <input type="checkbox" checked={sel.includes(a.name)} onChange={(e) => setSel(e.target.checked ? [...sel, a.name] : sel.filter((x) => x !== a.name))} />
            {a.name} {a.stochastic && <Badge color="violet">확률적</Badge>}
          </label>
        ))}
      </fieldset>
      {m.isError && <ErrorState error={m.error} />}
      <Button onClick={() => m.mutate()} disabled={!sel.length || m.isPending}>
        {m.isPending ? "등록 중…" : `실험 실행 (${sel.length}개 알고리즘)`}
      </Button>
    </div>
  );
}

export function ComparePage() {
  const sc = useSelectedScenario();
  const runs = useRuns(sc?.id ?? null);
  const [picked, setPicked] = useState<number[]>([]);
  const [problem, setProblem] = useState<string>("");
  const all = runs.data?.items ?? [];
  const types = [...new Set(all.map((r) => r.problem_type))];
  const pt = problem || types[0] || "";
  const candidates = all.filter((r) => r.problem_type === pt);
  const ids = picked.filter((id) => candidates.some((r) => r.id === id));
  const cmp = useCompare(ids.length ? ids[0] : null, ids.length > 1 ? ids.slice(1).join(",") : undefined);
  const rows = cmp.data?.rows ?? [];
  const stats = useMemo(() => algoStats(rows), [rows]);
  const costData = rows
    .filter((r) => r.cost)
    .map((r) => ({ name: `#${r.run_id} ${r.algorithm.replace(/^(warehouse|routing|dock|integrated)_/, "")}${r.seed ? `·s${r.seed}` : ""}`, ...Object.fromEntries(COST_KEYS.map(([k]) => [k, r.cost![k] as number])) }));
  const scatter = rows.filter((r) => r.total_cost !== null && r.runtime_ms !== null).map((r) => ({ x: r.runtime_ms! / 1000, y: r.total_cost!, algorithm: r.algorithm, id: r.run_id }));
  function download() {
    const blob = new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `dilsos_compare_scenario${sc?.id}_${pt}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }
  if (!sc) return <EmptyState>시나리오를 선택하세요.</EmptyState>;
  return (
    <div className="space-y-4">
      <PageHeader title="알고리즘 비교 · 실험" subtitle="동일 시나리오·동일 스냅샷·공통 평가기 기준 비교 (솔버 내부 목적값 아님)" />
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="실험 실행 (알고리즘 × 시드)">
          <ExperimentForm scenarioId={sc.id} onDone={(newIds) => setPicked(newIds)} />
        </Card>
        <Card
          title="비교할 실행 선택"
          className="xl:col-span-2"
          actions={
            <select className={`${inputCls} w-36 py-1`} value={pt} onChange={(e) => (setProblem(e.target.value), setPicked([]))} aria-label="문제 유형">
              {types.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          }
        >
          {runs.isLoading ? (
            <Spinner />
          ) : !candidates.length ? (
            <EmptyState>실행이 없습니다.</EmptyState>
          ) : (
            <div className="max-h-56 overflow-auto">
              <div className="mb-1 flex gap-2 text-xs">
                <button className="text-accent-600 underline" onClick={() => setPicked(candidates.filter((r) => r.status === "SUCCEEDED").map((r) => r.id))}>
                  성공 실행 모두 선택
                </button>
                <button className="text-ink-600 underline" onClick={() => setPicked([])}>
                  해제
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                {candidates.map((r) => (
                  <label key={r.id} className={cx("flex items-center gap-1 rounded border px-2 py-0.5 text-xs", ids.includes(r.id) ? "border-accent-500 bg-blue-50" : "border-ink-200")}>
                    <input type="checkbox" checked={ids.includes(r.id)} onChange={(e) => setPicked(e.target.checked ? [...ids, r.id] : ids.filter((x) => x !== r.id))} />#{r.id} {r.algorithm} s{r.seed}
                    <Badge color={statusColor(r.status)}>{r.status}</Badge>
                  </label>
                ))}
              </div>
            </div>
          )}
        </Card>
      </div>
      {ids.length === 0 ? (
        <EmptyState>비교할 실행을 선택하거나 실험을 실행하세요.</EmptyState>
      ) : cmp.isLoading ? (
        <Spinner />
      ) : cmp.isError ? (
        <ErrorState error={cmp.error} />
      ) : (
        <>
          <div className={cx("rounded border p-2 text-xs", cmp.data!.same_snapshot ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900")} role="note">
            {cmp.data!.same_snapshot ? "모든 실행이 동일한 입력 스냅샷을 사용했습니다." : `주의: 서로 다른 스냅샷(${cmp.data!.snapshot_ids.join(", ")})의 실행이 섞여 있습니다 — 입력이 달라 직접 비교가 제한됩니다.`} {cmp.data!.objective_note}
          </div>
          <Card title="알고리즘별 통계 (성공·검증 통과 실행 기준)" actions={<Button variant="secondary" onClick={download}>CSV 다운로드</Button>}>
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-ink-400">
                <tr>
                  <th>알고리즘</th>
                  <th>실행</th>
                  <th>실행가능</th>
                  <th>최고</th>
                  <th>평균</th>
                  <th>표준편차</th>
                  <th>평균 런타임</th>
                </tr>
              </thead>
              <tbody>
                {stats.map((s) => (
                  <tr key={s.algorithm} className="border-t border-ink-100">
                    <td className="py-1">{s.algorithm}</td>
                    <td>{s.n}</td>
                    <td>{pct(s.n ? s.feasible / s.n : null, 0)}</td>
                    <td className="tabular-nums">{krw(s.best)}</td>
                    <td className="tabular-nums">{krw(s.mean)}</td>
                    <td className="tabular-nums">{krw(s.std)}</td>
                    <td className="tabular-nums">{s.meanRuntime !== null ? `${s.meanRuntime.toFixed(2)}s` : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card title="목적함수 분해 (실행별)">
              <div className="h-72">
                <ResponsiveContainer>
                  <BarChart data={costData}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="name" fontSize={10} interval={0} angle={-25} textAnchor="end" height={60} />
                    <YAxis tickFormatter={(v) => `${Math.round(v / 1000)}k`} fontSize={11} />
                    <Tooltip formatter={(v: number) => krw(v)} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    {COST_KEYS.map(([k, label, color]) => (
                      <Bar key={k} dataKey={k} name={label} stackId="c" fill={color} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title="런타임 vs 총비용">
              <div className="h-72">
                <ResponsiveContainer>
                  <ScatterChart>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" dataKey="x" name="런타임" unit="s" fontSize={11} />
                    <YAxis type="number" dataKey="y" name="총비용" tickFormatter={(v) => `${Math.round(v / 1000)}k`} fontSize={11} />
                    <ZAxis range={[60, 60]} />
                    <Tooltip formatter={(v: number, n: string) => (n === "총비용" ? krw(v) : `${v}s`)} />
                    <Scatter data={scatter} fill="#2563eb" />
                  </ScatterChart>
                </ResponsiveContainer>
              </div>
              <p className="text-xs text-ink-400">런타임은 하드웨어 의존적입니다.</p>
            </Card>
          </div>
          <Card title="실행별 상세">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-ink-400">
                  <tr>
                    {["#", "알고리즘", "시드", "상태", "solver", "총비용", "정시율", "지연(분)", "거리(km)", "차량", "미처리", "창고 makespan", "gap"].map((h) => (
                      <th key={h}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.run_id} className="border-t border-ink-100">
                      <td className="py-0.5">{r.run_id}</td>
                      <td>{r.algorithm}</td>
                      <td>{r.seed}</td>
                      <td>
                        <Badge color={statusColor(r.status)}>{r.status}</Badge>
                      </td>
                      <td>{r.solver_status}</td>
                      <td className="tabular-nums">{krw(r.total_cost)}</td>
                      <td>{pct(r.on_time_rate)}</td>
                      <td>{r.total_lateness_min ?? "–"}</td>
                      <td>{r.total_distance_km?.toFixed(1) ?? "–"}</td>
                      <td>{r.vehicles_used ?? "–"}</td>
                      <td>{r.orders_unserved ?? "–"}</td>
                      <td>{r.warehouse_makespan_min ?? "–"}</td>
                      <td>{r.gap ?? "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
