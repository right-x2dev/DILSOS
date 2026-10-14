import { screen } from "@testing-library/react";
import { DockPage, dockView } from "../features/docks/DockPage";
import { useUi } from "../store/ui";
import { useAuth } from "../features/auth/authStore";
import type { Schedule, VehicleRoute } from "../types/api";
import { RUN, SCHEDULE } from "./fixtures";
import { mockFetch, renderWithProviders } from "./utils";

const route = (vid: string, dock: string, ls: number, le: number, extra: Partial<VehicleRoute> = {}): VehicleRoute => ({
  vehicle_id: vid,
  dock_id: dock,
  order_ids: ["O1"],
  ready_min: 40,
  load_start_min: ls,
  load_end_min: le,
  departure_min: le,
  return_min: le + 120,
  stops: [
    { seq: 1, customer_id: "C1", location_id: "L-C1", order_ids: ["O1"], arrival_min: le + 30, service_start_min: le + 30, service_end_min: le + 38, departure_min: le + 38, wait_min: 0, late_min: 0, load_after_kg: 0, load_after_l: 0 },
  ],
  distance_m: 20000,
  load_kg: 5,
  load_l: 10,
  geometry: "schematic_straight_line",
  ...extra,
});

const DOCK_SCHED: Schedule = {
  ...SCHEDULE,
  problem_type: "dock",
  vehicles: [
    { id: "V1", vehicle_class: "van", capacity_kg: 100, capacity_l: 1000, shift_start: 60, shift_end: 900, available: true },
    { id: "V2", vehicle_class: "van", capacity_kg: 100, capacity_l: 1000, shift_start: 60, shift_end: 900, available: true },
  ],
  routes: [route("V1", "D1", 60, 72), route("V2", "D1", 72, 84)],
};

test("dockView derives lanes, waiting bars and utilization from routes", () => {
  const v = dockView(DOCK_SCHED);
  expect(v.dockLanes.map((l) => l.id)).toEqual(["D1"]);
  expect(v.dockBars).toHaveLength(2);
  expect(v.vehBars.filter((b) => b.id.startsWith("W-"))).toHaveLength(2); // ready 40 < load start
  expect(v.warnings).toEqual([]);
  expect(v.utilization[0].util).toBeCloseTo(24 / 840);
});

test("dockView flags overlaps, early loading and capacity breaches", () => {
  const bad: Schedule = {
    ...DOCK_SCHED,
    routes: [route("V1", "D1", 60, 72), route("V2", "D1", 70, 82, { ready_min: 75, load_kg: 150 })],
  };
  const kinds = dockView(bad).warnings.map((w) => w.kind).sort();
  expect(kinds).toEqual(["capacity", "early_load", "overlap"]);
});

test("Dock page renders both timelines from API data", async () => {
  useAuth.setState({ token: "t", user: null });
  useUi.setState({ scenarioId: 1, runId: 7 });
  mockFetch({
    "GET /runs": { items: [{ ...RUN, problem_type: "dock" }], total: 1, limit: 100, offset: 0 },
    "GET /runs/7/schedule": DOCK_SCHED,
  });
  renderWithProviders(<DockPage />);
  expect(await screen.findByRole("img", { name: "도크 적재 타임라인" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "차량 운행 타임라인" })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
