import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useDashboard } from "../../api/hooks";
import { useSelectedScenario } from "../../components/ScenarioPicker";
import { Badge, Card, EmptyState, ErrorState, Kpi, PageHeader, Spinner, statusColor } from "../../components/ui";
import { useUi } from "../../store/ui";
import { fmtDateTime, fmtDuration, krw, pct } from "../../utils/time";

const STATUS_KO: Record<string, string> = { OPEN: "미출고", CANCELLED: "취소", SHIPPED: "출고완료" };

export function DashboardPage() {
  const scenarioId = useUi((s) => s.scenarioId);
  const sc = useSelectedScenario();
  const q = useDashboard(scenarioId);
  if (!scenarioId) return <EmptyState>시나리오를 선택하세요.</EmptyState>;
  if (q.isLoading) return <Spinner />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data!;
  const k = d.latest_success?.kpis;
  const util = k?.avg_utilization ?? {};
  const costRows = k
    ? [
        ["인건비", k.cost.labor_cost],
        ["초과근무", k.cost.overtime_cost],
        ["차량 고정비", k.cost.transport_fixed],
        ["거리비", k.cost.distance_cost],
        ["지연 페널티", k.cost.late_delivery_penalty],
        ["미처리 페널티", k.cost.unserved_penalty],
        ["변경 페널티", k.cost.schedule_change_penalty],
      ].map(([name, v]) => ({ name, v }))
    : [];
  return (
    <div className="space-y-4">
      <PageHeader
        title="운영 대시보드"
        subtitle={
          <>
            {d.scenario_name} · {sc?.facility.name} · 운영일 {sc?.operating_date} · KPI 출처: <b>{d.kpi_source}</b>
          </>
        }
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <Kpi label="주문(전체)" value={Object.values(d.orders_by_status).reduce((a, b) => a + b, 0)} unit="건" hint={Object.entries(d.orders_by_status).map(([s, n]) => `${STATUS_KO[s] ?? s} ${n}`).join(" · ")} />
        <Kpi label="정시율" value={pct(k?.on_time_rate)} hint={k ? "최근 성공 실행 기준(배송 또는 출고마감)" : "실행 결과 없음"} />
        <Kpi label="총 지연" value={k ? fmtDuration(k.total_lateness_min) : "–"} hint="예측 지연(계획 기준)" />
        <Kpi label="미처리 주문" value={k?.orders_unserved ?? "–"} unit={k ? "건" : undefined} hint="재고부족/용량부족 등 명시적 사유" />
        <Kpi label="도크 가동률" value={pct(util.dock)} hint={util.dock === undefined ? "도크 스케줄이 포함된 실행 필요" : "평균"} />
        <Kpi label="운행 차량" value={k ? `${k.vehicles_used}/${d.resources.vehicles}` : "–"} hint={`차량 상태: ${Object.entries(d.vehicles_by_status).map(([s, n]) => `${s} ${n}`).join(", ")}`} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="목적함수 분해 (최근 성공 실행)" className="lg:col-span-2">
          {k ? (
            <>
              <div className="mb-2 text-sm text-ink-600">
                총비용 <b className="text-ink-900">{krw(k.cost.total_cost)}</b> · 창고 makespan {fmtDuration(k.warehouse_makespan_min)}
                {k.total_distance_km ? ` · 총 거리 ${k.total_distance_km.toFixed(1)} km (합성)` : ""}
              </div>
              <div className="h-56">
                <ResponsiveContainer>
                  <BarChart data={costRows} layout="vertical" margin={{ left: 30 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                    <XAxis type="number" tickFormatter={(v) => `${Math.round(v / 1000)}k`} fontSize={11} />
                    <YAxis type="category" dataKey="name" fontSize={11} width={80} />
                    <Tooltip formatter={(v: number) => krw(v)} />
                    <Bar dataKey="v" name="금액" fill="#2563eb" radius={[0, 3, 3, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </>
          ) : (
            <EmptyState>
              성공한 실행이 없습니다. <Link className="text-accent-600 underline" to="/optimize">최적화 실행</Link>에서 알고리즘을 실행하세요.
            </EmptyState>
          )}
        </Card>
        <Card title="자원 가동률 (평균)">
          {k ? (
            <ul className="space-y-2 text-sm">
              {Object.entries(util).map(([kind, u]) => (
                <li key={kind}>
                  <div className="flex justify-between">
                    <span>{{ worker: "작업자", pack_station: "포장대", equipment: "장비", dock: "도크" }[kind] ?? kind}</span>
                    <span className="tabular-nums">{pct(u)}</span>
                  </div>
                  <div className="mt-1 h-2 rounded bg-ink-100">
                    <div className="h-2 rounded bg-accent-500" style={{ width: `${Math.min(100, u * 100)}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState>데이터 없음</EmptyState>
          )}
          <div className="mt-3 text-xs text-ink-400">가동률 = 배정 작업시간 / 가용시간(교대·정비 반영)</div>
        </Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="최근 실행">
          {d.latest_runs.length ? (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-ink-400">
                <tr>
                  <th className="py-1">#</th>
                  <th>알고리즘</th>
                  <th>상태</th>
                  <th>총비용</th>
                  <th>시간</th>
                </tr>
              </thead>
              <tbody>
                {d.latest_runs.map((r) => (
                  <tr key={r.id} className="border-t border-ink-100">
                    <td className="py-1">
                      <Link className="text-accent-600 hover:underline" to={`/runs?run=${r.id}`}>
                        {r.id}
                      </Link>
                    </td>
                    <td>{r.algorithm}</td>
                    <td>
                      <Badge color={statusColor(r.status)}>{r.status}</Badge>
                    </td>
                    <td className="tabular-nums">{krw(r.objective_total)}</td>
                    <td className="text-xs text-ink-600">{fmtDateTime(r.queued_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState>실행 이력 없음</EmptyState>
          )}
        </Card>
        <Card title="최근 교란 이벤트">
          {d.recent_events.length ? (
            <ul className="text-sm">
              {d.recent_events.map((e) => (
                <li key={e.id} className="border-t border-ink-100 py-1 first:border-0">
                  <Badge color="amber">{e.event_type}</Badge> {e.affected ?? ""} · t+{e.event_time_min}분
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState>기록된 교란 이벤트가 없습니다.</EmptyState>
          )}
        </Card>
      </div>
    </div>
  );
}
