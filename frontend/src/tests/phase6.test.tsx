import { hhmmToHorizonMin, routeDiff } from "../features/disruptions/DisruptionPage";
import { warehouseBars } from "../features/gantt/GanttPage";
import type { Schedule } from "../types/api";
import { SCHEDULE } from "./fixtures";

test("local HH:MM converts to minutes from the horizon start in the scenario timezone", () => {
  // horizon starts 06:00 KST (= 21:00Z previous day)
  expect(hhmmToHorizonMin("2026-10-15", "09:30", "Asia/Seoul", "2026-10-14T21:00:00Z")).toBe(210);
  expect(hhmmToHorizonMin("2026-10-15", "06:00", "Asia/Seoul", "2026-10-14T21:00:00Z")).toBe(0);
});

test("routeDiff lists only vehicles whose sequence or departure changed", () => {
  const mk = (vid: string, custs: string[], dep: number) => ({
    vehicle_id: vid,
    dock_id: null,
    order_ids: [],
    ready_min: 0,
    load_start_min: null,
    load_end_min: null,
    departure_min: dep,
    return_min: dep + 100,
    distance_m: 0,
    load_kg: 0,
    load_l: 0,
    geometry: "schematic_straight_line",
    stops: custs.map((c, i) => ({ seq: i + 1, customer_id: c, location_id: c, order_ids: [], arrival_min: 0, service_start_min: 0, service_end_min: 0, departure_min: 0, wait_min: 0, late_min: 0, load_after_kg: 0, load_after_l: 0 })),
  });
  const before: Schedule = { ...SCHEDULE, routes: [mk("V1", ["C1", "C2"], 100), mk("V2", ["C3"], 100)] };
  const after: Schedule = { ...SCHEDULE, routes: [mk("V1", ["C1", "C2"], 100), mk("V3", ["C3"], 130)] };
  const d = routeDiff(before, after);
  expect(d.map((x) => x.vehicle)).toEqual(["V2", "V3"]);
  expect(d[0].after).toBe("(없음)");
});

test("warehouseBars marks changed tasks against the previous version", () => {
  const next: Schedule = {
    ...SCHEDULE,
    assignments: SCHEDULE.assignments.map((a) => (a.task_id === "O2-PACK" ? { ...a, start_min: a.start_min + 10, end_min: a.end_min + 10 } : a)),
  };
  const v = warehouseBars(next, new Set(["worker", "pack_station"]), "", SCHEDULE);
  const changed = v.bars.filter((b) => b.outline === "#7c3aed").map((b) => b.id);
  expect(changed.sort()).toEqual(["O2-PACK@P1", "O2-PACK@W1"]);
});
