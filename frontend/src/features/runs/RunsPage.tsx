import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useRun, useRuns, useValidation } from "../../api/hooks";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Spinner, cx, inputCls, statusColor } from "../../components/ui";
import { useUi } from "../../store/ui";
import { fmtDateTime, krw } from "../../utils/time";
import { RunStatusCard } from "../optimize/OptimizePage";
import { AuditPanel } from "./AuditPanel";
import { ExportButtons } from "./ExportButtons";

function ValidationFindings({ runId, enabled }: { runId: number; enabled: boolean }) {
  const v = useValidation(runId, enabled);
  const [sev, setSev] = useState<"all" | "error" | "warning" | "info">("all");
  if (!enabled) return <EmptyState>검증 보고서가 아직 없습니다.</EmptyState>;
  if (v.isLoading) return <Spinner />;
  if (v.isError) return <ErrorState error={v.error} />;
  const r = v.data!;
  const items = r.violations.filter((x) => sev === "all" || x.severity === sev);
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge color={r.is_feasible ? "green" : "red"}>{r.is_feasible ? "FEASIBLE" : "INFEASIBLE"}</Badge>
        <span className="text-xs text-ink-600">범위: {r.scope.join(" + ")}</span>
        <span className="text-xs text-ink-600">검사 규칙: {r.checked_rules.join(", ")}</span>
        <select className={`${inputCls} ml-auto w-28 py-0.5 text-xs`} value={sev} onChange={(e) => setSev(e.target.value as typeof sev)} aria-label="심각도 필터">
          <option value="all">전체</option>
          <option value="error">error</option>
          <option value="warning">warning</option>
          <option value="info">info</option>
        </select>
      </div>
      {items.length ? (
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-white text-left text-ink-400">
              <tr>
                <th>심각도</th>
                <th>규칙</th>
                <th>대상</th>
                <th>내용</th>
                <th>관측값</th>
              </tr>
            </thead>
            <tbody>
              {items.map((x, i) => (
                <tr key={i} className="border-t border-ink-100 align-top">
                  <td>
                    <Badge color={x.severity === "error" ? "red" : x.severity === "warning" ? "amber" : "gray"}>{x.severity}</Badge>
                  </td>
                  <td className="font-mono">{x.rule}</td>
                  <td>
                    {x.entity_type}:{x.entity_id}
                  </td>
                  <td>{x.message}</td>
                  <td className="max-w-xs truncate font-mono text-ink-600" title={JSON.stringify(x.observed)}>
                    {JSON.stringify(x.observed)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-xs text-ink-400">해당 심각도의 항목이 없습니다.</div>
      )}
    </div>
  );
}

export function RunsPage() {
  const scenarioId = useUi((s) => s.scenarioId);
  const [params, setParams] = useSearchParams();
  const selected = params.get("run") ? Number(params.get("run")) : null;
  const runs = useRuns(scenarioId);
  const run = useRun(selected);
  useEffect(() => {
    if (!selected && runs.data?.items.length) setParams({ run: String(runs.data.items[0].id) }, { replace: true });
  }, [selected, runs.data, setParams]);
  return (
    <div className="space-y-4">
      <PageHeader title="실행 이력 · 감사" subtitle="스케줄 버전, 시드, 파라미터, 검증 결과, 오류, 감사 로그" />
      <div className="grid gap-4 xl:grid-cols-5">
        <Card title="실행 목록" className="xl:col-span-2">
          {runs.isLoading ? (
            <Spinner />
          ) : runs.isError ? (
            <ErrorState error={runs.error} />
          ) : !runs.data!.items.length ? (
            <EmptyState>실행이 없습니다.</EmptyState>
          ) : (
            <div className="max-h-[70vh] overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-white text-left text-xs text-ink-400">
                  <tr>
                    <th>#</th>
                    <th>알고리즘</th>
                    <th>유형</th>
                    <th>상태</th>
                    <th>총비용</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data!.items.map((r) => (
                    <tr
                      key={r.id}
                      onClick={() => setParams({ run: String(r.id) })}
                      className={cx("cursor-pointer border-t border-ink-100 hover:bg-ink-50", r.id === selected && "bg-blue-50")}
                    >
                      <td className="py-1">
                        {r.id}
                        {r.parent_run_id ? <span className="text-xs text-violet-700"> ←{r.parent_run_id}</span> : null}
                      </td>
                      <td className="text-xs">{r.algorithm}</td>
                      <td className="text-xs">{r.problem_type}</td>
                      <td>
                        <Badge color={statusColor(r.status)}>{r.status}</Badge>
                      </td>
                      <td className="text-xs tabular-nums">{krw(r.objective_total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <div className="space-y-4 xl:col-span-3">
          {!selected ? (
            <EmptyState>실행을 선택하세요.</EmptyState>
          ) : run.isLoading ? (
            <Spinner />
          ) : run.isError ? (
            <ErrorState error={run.error} />
          ) : (
            <>
              <RunStatusCard run={run.data!} />
              <Card title="재현 정보" actions={<ExportButtons run={run.data!} />}>
                <dl className="grid grid-cols-2 gap-1 text-sm md:grid-cols-4">
                  <dt className="text-ink-400">스케줄 버전</dt>
                  <dd>v{run.data!.schedule_version}</dd>
                  <dt className="text-ink-400">스냅샷</dt>
                  <dd>
                    #{run.data!.snapshot_id} (v{run.data!.snapshot_version})
                  </dd>
                  <dt className="text-ink-400">시드</dt>
                  <dd>{run.data!.seed}</dd>
                  <dt className="text-ink-400">시간 제한</dt>
                  <dd>{run.data!.time_limit_s}s</dd>
                  <dt className="text-ink-400">큐 등록</dt>
                  <dd className="text-xs">{fmtDateTime(run.data!.queued_at)}</dd>
                  <dt className="text-ink-400">종료</dt>
                  <dd className="text-xs">{fmtDateTime(run.data!.finished_at)}</dd>
                  <dt className="text-ink-400">파라미터</dt>
                  <dd className="col-span-3 font-mono text-xs">{JSON.stringify(run.data!.params)}</dd>
                </dl>
              </Card>
              <Card title="검증 결과 (feasibility findings)">
                <ValidationFindings runId={run.data!.id} enabled={!!run.data!.validation_summary} />
              </Card>
              <AuditPanel runId={run.data!.id} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
