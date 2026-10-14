import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RoutesPage } from "../features/routes/RoutesPage";
import { useUi } from "../store/ui";
import { useAuth } from "../features/auth/authStore";
import type { Geo, Schedule } from "../types/api";
import { RUN, SCHEDULE } from "./fixtures";
import { mockFetch, renderWithProviders } from "./utils";

const GEO: Geo = {
  coordinate_provenance: "synthetic (generated km offsets; lat/lon derived for display only)",
  travel_provenance: "synthetic_euclidean",
  travel_notes: "SYNTHETIC: euclidean × 1.3 at 30 km/h — not real road travel time",
  points: [
    { id: "DEPOT", kind: "depot", name: "DC", x_km: 0, y_km: 0, lat: 37.45, lon: 126.7, tw_start: null, tw_end: null },
    { id: "C1", kind: "customer", name: "c1", x_km: 3, y_km: 4, lat: 37.49, lon: 126.73, tw_start: 100, tw_end: 300 },
    { id: "C2", kind: "customer", name: "c2", x_km: -5, y_km: 2, lat: 37.47, lon: 126.64, tw_start: 100, tw_end: 300 },
  ],
};

const ROUTED: Schedule = {
  ...SCHEDULE,
  problem_type: "routing",
  assignments: [],
  vehicles: [{ id: "V1", vehicle_class: "van", capacity_kg: 100, capacity_l: 1000, shift_start: 60, shift_end: 900, available: true }],
  routes: [
    {
      vehicle_id: "V1",
      dock_id: null,
      order_ids: ["O1", "O2"],
      ready_min: 0,
      load_start_min: null,
      load_end_min: null,
      departure_min: 60,
      return_min: 400,
      distance_m: 25000,
      load_kg: 10,
      load_l: 20,
      geometry: "schematic_straight_line",
      stops: [
        { seq: 1, customer_id: "C1", location_id: "L-C1", order_ids: ["O1"], arrival_min: 80, service_start_min: 100, service_end_min: 108, departure_min: 108, wait_min: 20, late_min: 0, load_after_kg: 5, load_after_l: 10 },
        { seq: 2, customer_id: "C2", location_id: "L-C2", order_ids: ["O2"], arrival_min: 320, service_start_min: 320, service_end_min: 328, departure_min: 328, wait_min: 0, late_min: 20, load_after_kg: 0, load_after_l: 0 },
      ],
    },
  ],
};

test("Routes page shows provenance banner, schematic map and route table with lateness", async () => {
  useAuth.setState({ token: "t", user: null });
  useUi.setState({ scenarioId: 1, runId: 7 });
  mockFetch({
    "GET /runs": { items: [{ ...RUN, problem_type: "routing" }], total: 1, limit: 100, offset: 0 },
    "GET /runs/7/schedule": ROUTED,
    "GET /scenarios/1/geo": GEO,
  });
  renderWithProviders(<RoutesPage />);
  const note = await screen.findByRole("note");
  expect(note).toHaveTextContent("synthetic_euclidean");
  expect(note).toHaveTextContent("실제 도로 주행시간이 아닙니다");
  const svg = screen.getByRole("img", { name: "배송 경로 도식" });
  expect(within(svg).getByText(/실제 도로 경로\/거리 아님/)).toBeInTheDocument();
  expect(screen.getByText("지연 1")).toBeInTheDocument();
  expect(screen.getByText("20분", { selector: "td.font-medium" })).toBeInTheDocument();
  // focusing a vehicle via legend button toggles aria-pressed on the table header
  await userEvent.click(screen.getAllByRole("button", { name: /V1/ })[0]);
  expect(screen.getAllByRole("button", { pressed: true }).length).toBeGreaterThan(0);
});
