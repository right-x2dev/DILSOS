import { useEffect, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "../features/auth/authStore";
import { LoginPage } from "../features/auth/LoginPage";
import { ComparePage } from "../features/compare/ComparePage";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { DisruptionPage } from "../features/disruptions/DisruptionPage";
import { DockPage } from "../features/docks/DockPage";
import { GanttPage } from "../features/gantt/GanttPage";
import { JourneyPage } from "../features/journey/JourneyPage";
import { OptimizePage } from "../features/optimize/OptimizePage";
import { OrdersPage } from "../features/orders/OrdersPage";
import { RoutesPage } from "../features/routes/RoutesPage";
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
        <Route path="routes" element={<RoutesPage />} />
        <Route path="journey" element={<JourneyPage />} />
        <Route path="disruptions" element={<DisruptionPage />} />
        <Route path="compare" element={<ComparePage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
