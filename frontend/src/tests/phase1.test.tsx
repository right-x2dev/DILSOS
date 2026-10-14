import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GanttPage, warehouseBars } from "../features/gantt/GanttPage";
import { OptimizePage } from "../features/optimize/OptimizePage";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { useUi } from "../store/ui";
import { useAuth } from "../features/auth/authStore";
import { clock, localMin } from "../utils/time";
import { zonedToIso } from "../utils/zoned";
import { RUN, SCENARIO, SCHEDULE } from "./fixtures";
import { mockFetch, renderWithProviders } from "./utils";

const ALGOS = [
  { name: "warehouse_edd", problem_types: ["warehouse"], kind: "heuristic", description: "EDD", available: true, stochastic: false, phase: "P1" },
  { name: "warehouse_cpsat", problem_types: ["warehouse"], kind: "exact", description: "CP-SAT", available: true, stochastic: false, phase: "P1" },
];

beforeEach(() => {
  useAuth.setState({ token: "t", user: null });
  useUi.setState({ scenarioId: 1, runId: 7 });
});

test("time helpers use the scenario timezone, not the browser's", () => {
  expect(clock("2026-10-14T21:00:00Z", "Asia/Seoul", 0)).toBe("06:00");
  expect(clock("2026-10-14T21:00:00Z", "Asia/Seoul", 135)).toBe("08:15");
  expect(localMin(1500)).toBe("01:00(+1)");
  expect(zonedToIso("2026-10-15", "08:00", "Asia/Seoul")).toBe("2026-10-14T23:00:00.000Z");
});

test("warehouseBars builds one bar per (task, resource) and flags late orders", () => {
  const v = warehouseBars(SCHEDULE, new Set(["worker", "pack_station"]), "");
  expect(v.lanes.map((l) => l.id)).toEqual(["W1", "W2", "P1"]); // dock lanes excluded
  expect(v.bars).toHaveLength(6); // 2 PICK (1 res) + 2 PACK (2 res)
  const late = v.bars.filter((b) => b.warn).map((b) => b.id);
  expect(late.every((id) => id.startsWith("O2"))).toBe(true); // O2 packed at 40 > due 30
  const focused = warehouseBars(SCHEDULE, new Set(["worker", "pack_station"]), "O1");
  expect(focused.links).toHaveLength(1);
  expect(focused.bars.filter((b) => !b.faded).every((b) => b.id.startsWith("O1"))).toBe(true);
});

test("Gantt page renders API schedule, legend and unserved orders", async () => {
  mockFetch({
    "GET /runs": { items: [RUN], total: 1, limit: 100, offset: 0 },
    "GET /runs/7/schedule": SCHEDULE,
  });
  renderWithProviders(<GanttPage />);
  const chart = await screen.findByRole("img", { name: "창고 작업 간트 차트" });
  expect(within(chart).getAllByText(/^PICK O1/).length).toBe(1); // accessible <title> tooltip per bar
  expect(within(chart).getAllByText(/^PACK O2/).length).toBe(2); // packer lane + station lane
  expect(screen.getByText(/O3: insufficient_inventory/)).toBeInTheDocument();
  expect(screen.getByText("피킹")).toBeInTheDocument();
});

test("Gantt page shows typed error when schedule is not published", async () => {
  mockFetch({
    "GET /runs": { items: [RUN], total: 1, limit: 100, offset: 0 },
    "GET /runs/7/schedule": new Response(JSON.stringify({ error: { code: "no_schedule", message: "run is FAILED" } }), {
      status: 409,
      headers: { "content-type": "application/json" },
    }),
  });
  renderWithProviders(<GanttPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("no_schedule");
});

test("Optimize console enqueues a run and shows the validated result", async () => {
  const calls: unknown[] = [];
  mockFetch({
    "GET /scenarios": { items: [SCENARIO], total: 1, limit: 200, offset: 0 },
    "GET /algorithms": ALGOS,
    "POST /scenarios/1/runs": (b: unknown) => (calls.push(b), { ...RUN, status: "QUEUED", kpis: null, validation_summary: null }),
    "GET /runs/7": RUN,
  });
  renderWithProviders(<OptimizePage />);
  const btn = await screen.findByRole("button", { name: "실행 (비동기 큐)" });
  await waitFor(() => expect(btn).toBeEnabled());
  await userEvent.click(btn);
  expect(calls[0]).toMatchObject({ problem_type: "warehouse", algorithm: "warehouse_edd", time_limit_s: 10, seed: 0 });
  expect(await screen.findByText("실행가능 (검증 통과)")).toBeInTheDocument();
  expect(screen.getByText("₩12,345")).toBeInTheDocument();
});

test("Optimize console marks unimplemented problem types as not available", async () => {
  mockFetch({ "GET /scenarios": { items: [SCENARIO], total: 1, limit: 200, offset: 0 }, "GET /algorithms": ALGOS });
  renderWithProviders(<OptimizePage />);
  await screen.findByRole("button", { name: "실행 (비동기 큐)" });
  await userEvent.selectOptions(screen.getByLabelText("문제 유형"), "routing");
  expect(screen.getByText(/아직 구현되지 않았습니다/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "실행 (비동기 큐)" })).toBeDisabled();
});

test("Dashboard shows honest empty state without successful runs", async () => {
  mockFetch({
    "GET /scenarios": { items: [SCENARIO], total: 1, limit: 200, offset: 0 },
    "GET /dashboard/summary": {
      scenario_id: 1,
      scenario_name: "normal_day",
      orders_by_status: { OPEN: 2 },
      orders_by_priority: { "1": 2 },
      resources: { vehicles: 2 },
      vehicles_by_status: { AVAILABLE: 2 },
      runs_by_status: {},
      latest_runs: [],
      latest_success: null,
      kpi_source: "아직 성공한 실행이 없습니다 — KPI 없음",
      recent_events: [],
    },
  });
  renderWithProviders(<DashboardPage />);
  expect(await screen.findByText(/성공한 실행이 없습니다\./)).toBeInTheDocument();
  expect(screen.getByText("정시율").nextSibling).toHaveTextContent("–");
});
