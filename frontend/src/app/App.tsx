import { lazy, Suspense, useEffect, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "../features/auth/authStore";
import { LoginPage } from "../features/auth/LoginPage";
import { Spinner } from "../components/ui";
import { Layout } from "./Layout";

// Route-level code splitting keeps the initial bundle small (charts/maps load with their screens).
const DashboardPage = lazy(() => import("../features/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const ScenariosPage = lazy(() => import("../features/scenarios/ScenariosPage").then((m) => ({ default: m.ScenariosPage })));
const OrdersPage = lazy(() => import("../features/orders/OrdersPage").then((m) => ({ default: m.OrdersPage })));
const OptimizePage = lazy(() => import("../features/optimize/OptimizePage").then((m) => ({ default: m.OptimizePage })));
const GanttPage = lazy(() => import("../features/gantt/GanttPage").then((m) => ({ default: m.GanttPage })));
const DockPage = lazy(() => import("../features/docks/DockPage").then((m) => ({ default: m.DockPage })));
const RoutesPage = lazy(() => import("../features/routes/RoutesPage").then((m) => ({ default: m.RoutesPage })));
const JourneyPage = lazy(() => import("../features/journey/JourneyPage").then((m) => ({ default: m.JourneyPage })));
const DisruptionPage = lazy(() => import("../features/disruptions/DisruptionPage").then((m) => ({ default: m.DisruptionPage })));
const ComparePage = lazy(() => import("../features/compare/ComparePage").then((m) => ({ default: m.ComparePage })));
const RunsPage = lazy(() => import("../features/runs/RunsPage").then((m) => ({ default: m.RunsPage })));

function RequireAuth({ children }: { children: ReactNode }) {
  const { token, user, loadMe } = useAuth();
  useEffect(() => {
    if (token && !user) void loadMe();
  }, [token, user, loadMe]);
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

const page = (el: ReactNode) => <Suspense fallback={<Spinner label="화면 로딩…" />}>{el}</Suspense>;

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
        <Route index element={page(<DashboardPage />)} />
        <Route path="scenarios" element={page(<ScenariosPage />)} />
        <Route path="orders" element={page(<OrdersPage />)} />
        <Route path="optimize" element={page(<OptimizePage />)} />
        <Route path="gantt" element={page(<GanttPage />)} />
        <Route path="docks" element={page(<DockPage />)} />
        <Route path="routes" element={page(<RoutesPage />)} />
        <Route path="journey" element={page(<JourneyPage />)} />
        <Route path="disruptions" element={page(<DisruptionPage />)} />
        <Route path="compare" element={page(<ComparePage />)} />
        <Route path="runs" element={page(<RunsPage />)} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
