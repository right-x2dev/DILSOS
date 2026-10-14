import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../features/auth/authStore";
import { Badge, cx } from "../components/ui";
import { NAV } from "./nav";

type Ready = { status: string; task_backend: string; database_dialect: string };

function HealthBadge() {
  const q = useQuery({
    queryKey: ["health-ready"],
    queryFn: () => api<Ready>("/health/ready"),
    refetchInterval: 30_000,
    retry: false,
  });
  if (q.isLoading) return <Badge>상태 확인 중</Badge>;
  if (q.isError || q.data?.status !== "ready") return <Badge color="red">API 연결 불가</Badge>;
  return (
    <Badge color="green" title={`DB=${q.data.database_dialect}, queue=${q.data.task_backend}`}>
      API 정상 · {q.data.database_dialect}
    </Badge>
  );
}

export function Layout() {
  const { user, logout } = useAuth();
  return (
    <div className="flex min-h-screen bg-ink-50 text-ink-900">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col bg-tower-900 text-ink-100 md:flex">
        <div className="px-4 py-4">
          <div className="text-lg font-bold tracking-tight text-white">DILSOS</div>
          <div className="text-[11px] leading-tight text-ink-400">물류 통합 스케줄링 · 관제</div>
        </div>
        <nav aria-label="주 메뉴" className="flex-1 overflow-y-auto px-2 pb-4">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                cx(
                  "mb-0.5 flex items-center justify-between rounded-md px-3 py-1.5 text-sm",
                  isActive ? "bg-tower-700 font-medium text-white" : "text-ink-200 hover:bg-tower-800",
                )
              }
            >
              <span>{item.label}</span>
              <span className="text-[10px] text-ink-400">{item.en}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        {user?.is_demo && (
          <div role="note" className="bg-amber-100 px-4 py-1 text-center text-xs text-amber-900">
            데모 모드 — 합성(synthetic) 데이터와 개발용 계정입니다. 실제 운영/텔레메트리 데이터가 아닙니다.
          </div>
        )}
        <header className="flex items-center justify-between gap-2 border-b border-ink-200 bg-white px-4 py-2">
          <nav aria-label="모바일 메뉴" className="flex gap-1 overflow-x-auto md:hidden">
            {NAV.slice(0, 6).map((n) => (
              <NavLink key={n.to} to={n.to} className="whitespace-nowrap rounded px-2 py-1 text-xs text-ink-600">
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="hidden text-sm text-ink-600 md:block">시간 표시: 시나리오 기준 상대시간(분) + UTC</div>
          <div className="flex items-center gap-3">
            <HealthBadge />
            <span className="text-sm text-ink-600">{user?.display_name}</span>
            <button onClick={logout} className="text-sm text-accent-600 hover:underline">
              로그아웃
            </button>
          </div>
        </header>
        <main className="min-w-0 flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
