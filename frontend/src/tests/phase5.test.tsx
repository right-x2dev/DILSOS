import { algoStats, toCsv } from "../features/compare/ComparePage";
import type { CompareRow } from "../types/api";

const row = (id: number, alg: string, cost: number | null, extra: Partial<CompareRow> = {}): CompareRow => ({
  run_id: id,
  algorithm: alg,
  problem_type: "routing",
  status: "SUCCEEDED",
  solver_status: "FEASIBLE",
  is_feasible: true,
  seed: id,
  runtime_ms: 1000,
  total_cost: cost,
  cost: null,
  on_time_rate: 1,
  total_lateness_min: 0,
  total_distance_km: 10,
  vehicles_used: 2,
  orders_unserved: 0,
  warehouse_makespan_min: null,
  end_to_end_makespan_min: 300,
  avg_utilization: null,
  changed_tasks: null,
  stability_score: null,
  gap: null,
  ...extra,
});

test("algoStats computes best/mean/std over feasible successful runs only", () => {
  const s = algoStats([
    row(1, "routing_alns", 100),
    row(2, "routing_alns", 120),
    row(3, "routing_alns", null, { status: "FAILED", is_feasible: false }),
    row(4, "routing_nn", 150),
  ]);
  expect(s[0]).toMatchObject({ algorithm: "routing_alns", n: 3, feasible: 2, best: 100, mean: 110, std: 10 });
  expect(s[1]).toMatchObject({ algorithm: "routing_nn", n: 1, feasible: 1, std: 0 });
});

test("toCsv escapes values and keeps one line per run", () => {
  const csv = toCsv([row(1, 'a,"b"', 5), row(2, "x", null)]);
  const lines = csv.split("\n");
  expect(lines).toHaveLength(3);
  expect(lines[0].startsWith("run_id,algorithm,problem_type")).toBe(true);
  expect(lines[1]).toContain('"a,""b"""');
  expect(lines[2].split(",")[8]).toBe(""); // null total_cost → empty cell
});
