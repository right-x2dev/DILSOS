import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Card, EmptyState, ErrorState, Spinner } from "../../components/ui";
import type { Page } from "../../types/api";
import { fmtDateTime } from "../../utils/time";

type AuditRow = {
  id: number;
  user_email: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before_ref: string | null;
  after_ref: string | null;
  detail: Record<string, unknown> | null;
  request_id: string | null;
  created_at: string;
};

export function AuditPanel({ runId }: { runId: number }) {
  const q = useQuery({
    queryKey: ["audit", "run", runId],
    queryFn: () => api<Page<AuditRow>>(`/audit-logs?entity_type=run&entity_id=${runId}`),
  });
  return (
    <Card title="감사 로그 (이 실행)">
      {q.isLoading ? (
        <Spinner />
      ) : q.isError ? (
        <ErrorState error={q.error} />
      ) : !q.data!.items.length ? (
        <EmptyState>기록 없음</EmptyState>
      ) : (
        <table className="w-full text-xs">
          <thead className="text-left text-ink-400">
            <tr>
              <th>시각</th>
              <th>사용자</th>
              <th>행위</th>
              <th>이전→이후</th>
              <th>request_id</th>
            </tr>
          </thead>
          <tbody>
            {q.data!.items.map((a) => (
              <tr key={a.id} className="border-t border-ink-100">
                <td className="py-1">{fmtDateTime(a.created_at)}</td>
                <td>{a.user_email ?? "system"}</td>
                <td>{a.action}</td>
                <td>
                  {a.before_ref ?? "–"} → {a.after_ref ?? "–"}
                </td>
                <td className="font-mono">{a.request_id ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
