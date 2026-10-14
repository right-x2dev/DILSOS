import { screen } from "@testing-library/react";
import { JourneyPage, buildJourneys } from "../features/journey/JourneyPage";
import { useUi } from "../store/ui";
import { useAuth } from "../features/auth/authStore";
import type { Schedule } from "../types/api";
import { RUN, SCHEDULE } from "./fixtures";
import { mockFetch, renderWithProviders } from "./utils";

const INTEG: Schedule = {
  ...SCHEDULE,
  problem_type: "integrated",
  unserved: [],
  orders: [
    { id: "O1", customer_id: "C1", release_min: 0, due_min: 30, priority: 1, weight_kg: 5, tw_start: 60, tw_end: 300 },
    { id: "O2", customer_id: "C2", release_min: 0, due_min: 30, priority: 3, weight_kg: 5, tw_start: 60, tw_end: 120 },
  ],
  assignments: [
    ...SCHEDULE.assignments,
    { task_id: "LOAD-V1", task_type: "LOAD", order_ids: ["O1", "O2"], resource_id: "D1", resources: { dock: "D1" }, start_min: 90, end_min: 104, frozen: false },
  ],
  vehicles: [{ id: "V1", vehicle_class: "van", capacity_kg: 100, capacity_l: 1000, shift_start: 60, shift_end: 900, available: true }],
  routes: [
    {
      vehicle_id: "V1",
      dock_id: "D1",
      order_ids: ["O1", "O2"],
      ready_min: 40,
      load_start_min: 90,
      load_end_min: 104,
      departure_min: 104,
      return_min: 200,
      distance_m: 10000,
      load_kg: 10,
      load_l: 20,
      geometry: "schematic_straight_line",
      stops: [
        { seq: 1, customer_id: "C1", location_id: "L-C1", order_ids: ["O1"], arrival_min: 120, service_start_min: 120, service_end_min: 128, departure_min: 128, wait_min: 0, late_min: 0, load_after_kg: 5, load_after_l: 10 },
        { seq: 2, customer_id: "C2", location_id: "L-C2", order_ids: ["O2"], arrival_min: 140, service_start_min: 140, service_end_min: 148, departure_min: 148, wait_min: 0, late_min: 20, load_after_kg: 0, load_after_l: 0 },
      ],
    },
  ],
};

test("buildJourneys chains pick→pack→load→delivery and attributes delay", () => {
  const js = buildJourneys(INTEG);
  expect(js.map((j) => j.order)).toEqual(["O2", "O1"]); // late first
  const o2 = js[0];
  expect(o2.late).toBe(20);
  expect(o2.segments).toEqual({ wait_pick: 5, wait_pack: 0, wait_load: 50, transit: 36 });
  expect(o2.cause).toBe("wait_load");
  expect(js[1].cause).toBeNull();
});

test("Journey page renders KPI, causes and the timeline", async () => {
  useAuth.setState({ token: "t", user: null });
  useUi.setState({ scenarioId: 1, runId: 7 });
  mockFetch({
    "GET /runs": { items: [{ ...RUN, problem_type: "integrated" }], total: 1, limit: 100, offset: 0 },
    "GET /runs/7/schedule": INTEG,
  });
  renderWithProviders(<JourneyPage />);
  expect(await screen.findByRole("img", { name: "주문 여정 타임라인" })).toBeInTheDocument();
  expect(screen.getByText(/도크\/차량 대기\(동승 주문 준비·도크 경합\): 1건/)).toBeInTheDocument();
  expect(screen.getByText(/인과 추론 아님/)).toBeInTheDocument();
});
