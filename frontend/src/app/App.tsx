import { useEffect, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "../features/auth/authStore";
import { LoginPage } from "../features/auth/LoginPage";
import { ComingSoon } from "../features/placeholder/ComingSoon";
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
        <Route index element={<ComingSoon title="대시보드" phase="Phase 1" />} />
        <Route path="scenarios" element={<ComingSoon title="시나리오" phase="Phase 1" />} />
        <Route path="orders" element={<ComingSoon title="주문·자원" phase="Phase 1" />} />
        <Route path="optimize" element={<ComingSoon title="최적화 실행" phase="Phase 1" />} />
        <Route path="gantt" element={<ComingSoon title="창고 간트" phase="Phase 1" />} />
        <Route path="docks" element={<ComingSoon title="도크 타임라인" phase="Phase 2" />} />
        <Route path="routes" element={<ComingSoon title="배송 경로" phase="Phase 3" />} />
        <Route path="journey" element={<ComingSoon title="통합 타임라인" phase="Phase 4" />} />
        <Route path="disruptions" element={<ComingSoon title="교란 시뮬레이터" phase="Phase 6" />} />
        <Route path="compare" element={<ComingSoon title="알고리즘 비교" phase="Phase 5" />} />
        <Route path="runs" element={<ComingSoon title="실행 이력·감사" phase="Phase 1" />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
