import { useEffect, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "../features/auth/authStore";
import { LoginPage } from "../features/auth/LoginPage";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { DockPage } from "../features/docks/DockPage";
import { GanttPage } from "../features/gantt/GanttPage";
import { OptimizePage } from "../features/optimize/OptimizePage";
import { OrdersPage } from "../features/orders/OrdersPage";
import { ComingSoon } from "../features/placeholder/ComingSoon";
import { RunsPage } from "../features/runs/RunsPage";
import { ScenariosPage } from "../features/scenarios/ScenariosPage";
import { Layout } from "./Layout";

function RequireAuth({ children }: { children: ReactNode }) {
  const { token, user, loadMe } = useAuth();
  useEffect(() => {
    if (token && !user) void loadMe();
  }, [token, user, loadMe]);
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="scenarios" element={<ScenariosPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="optimize" element={<OptimizePage />} />
        <Route path="gantt" element={<GanttPage />} />
        <Route path="docks" element={<DockPage />} />
        <Route path="routes" element={<ComingSoon title="배송 경로" phase="Phase 3" />} />
        <Route path="journey" element={<ComingSoon title="통합 타임라인" phase="Phase 4" />} />
        <Route path="disruptions" element={<ComingSoon title="교란 시뮬레이터" phase="Phase 6" />} />
        <Route path="compare" element={<ComingSoon title="알고리즘 비교" phase="Phase 5" />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
