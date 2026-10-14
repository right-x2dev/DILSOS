/** TypeScript mirrors of the backend response models (app/schemas/api.py, optimization contracts). */

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export type Facility = { id: number; code: string; name: string; timezone: string };

export type ObjectiveWeights = {
  currency: string;
  late_penalty_per_min: number;
  unserved_penalty: number;
  overtime_premium: number;
  change_penalty_per_task: number;
  change_penalty_per_route: number;
};

export type ScenarioParams = {
  time_window_mode: "soft" | "hard";
  return_to_depot: boolean;
  load_base_min: number;
  load_per_order_min: number;
  aggregate_same_customer: boolean;
};

export type Scenario = {
  id: number;
  name: string;
  description: string;
  facility: Facility;
  operating_date: string;
  horizon_start: string;
  horizon_min: number;
  seed: number;
  status: string;
  version: number;
  parent_scenario_id: number | null;
  order_count: number;
  created_at: string;
  params: ScenarioParams;
  weights: ObjectiveWeights;
  task_model: Record<string, unknown>;
  travel_params: Record<string, unknown>;
  resource_counts: Record<string, number>;
  snapshot_versions: number;
};

export type InputIssue = { severity: "error" | "warning" | "info"; code: string; entity: string; message: string };
export type InputValidation = { ok: boolean; issues: InputIssue[]; summary: Record<string, unknown> };

export type OrderLine = { sku_code: string; qty: number };
export type Order = {
  id: number;
  code: string;
  facility_code: string;
  customer_code: string;
  customer_name: string;
  release_at: string;
  due_at: string;
  priority: number;
  status: string;
  units: number;
  weight_kg: number;
  lines: OrderLine[];
};

export type Worker = {
  id: number;
  facility_id: number;
  code: string;
  name: string;
  skills: string[];
  hourly_cost: number;
  shift_start_local_min: number;
  shift_end_local_min: number;
  regular_end_local_min: number | null;
  active: boolean;
};
export type VehicleRes = {
  id: number;
  facility_id: number;
  code: string;
  vehicle_class: "van" | "truck";
  capacity_kg: number;
  capacity_l: number;
  fixed_cost: number;
  cost_per_km: number;
  shift_start_local_min: number;
  shift_end_local_min: number;
  status: string;
};
export type DockRes = {
  id: number;
  facility_id: number;
  code: string;
  name: string;
  vehicle_classes: string[];
  open_start_local_min: number;
  open_end_local_min: number;
  active: boolean;
};

export type Algorithm = {
  name: string;
  problem_types: string[];
  kind: string;
  description: string;
  available: boolean;
  stochastic: boolean;
  phase: string;
};

export type CostBreakdown = {
  currency: string;
  transport_fixed: number;
  distance_cost: number;
  labor_cost: number;
  overtime_cost: number;
  late_delivery_penalty: number;
  unserved_penalty: number;
  schedule_change_penalty: number;
  total_cost: number;
  coefficients: Record<string, unknown>;
};

export type Kpis = {
  on_time_rate: number | null;
  total_lateness_min: number;
  orders_served: number;
  orders_unserved: number;
  warehouse_makespan_min: number | null;
  end_to_end_makespan_min: number | null;
  total_distance_km: number;
  vehicles_used: number;
  overtime_min: number;
  changed_tasks: number | null;
  changed_routes: number | null;
  stability_score: number | null;
  avg_utilization: Record<string, number>;
  cost: CostBreakdown;
};

export type RunStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
export type Run = {
  id: number;
  scenario_id: number;
  scenario_name: string;
  snapshot_id: number;
  snapshot_version: number;
  parent_run_id: number | null;
  schedule_version: number;
  problem_type: string;
  algorithm: string;
  params: Record<string, unknown>;
  seed: number;
  time_limit_s: number;
  status: RunStatus;
  solver_status: string | null;
  progress: number;
  cancel_requested: boolean;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  runtime_ms: number | null;
  is_feasible: boolean | null;
  objective_total: number | null;
  error_message: string | null;
  kpis: Kpis | null;
  validation_summary: Record<string, unknown> | null;
  solver_metadata: Record<string, unknown> | null;
  horizon_start: string;
  timezone: string;
};

export type Interval = { start: number; end: number };
export type TaskAssignment = {
  task_id: string;
  task_type: "PICK" | "PACK" | "LOAD";
  order_ids: string[];
  resource_id: string;
  resources: Record<string, string>;
  start_min: number;
  end_min: number;
  frozen: boolean;
};
export type RouteStop = {
  seq: number;
  customer_id: string;
  location_id: string;
  order_ids: string[];
  arrival_min: number;
  service_start_min: number;
  service_end_min: number;
  departure_min: number;
  wait_min: number;
  late_min: number;
  load_after_kg: number;
  load_after_l: number;
};
export type VehicleRoute = {
  vehicle_id: string;
  dock_id: string | null;
  order_ids: string[];
  ready_min: number;
  load_start_min: number | null;
  load_end_min: number | null;
  departure_min: number;
  return_min: number;
  stops: RouteStop[];
  distance_m: number;
  load_kg: number;
  load_l: number;
  geometry: string;
};
export type ResourceLane = {
  id: string;
  kind: string;
  name: string;
  available: Interval[];
  skills: string[];
  regular_end: number | null;
  vehicle_classes: string[];
};
export type OrderInfo = {
  id: string;
  customer_id: string;
  release_min: number;
  due_min: number;
  priority: number;
  weight_kg: number;
  tw_start: number;
  tw_end: number;
};
export type VehicleInfo = {
  id: string;
  vehicle_class: string;
  capacity_kg: number;
  capacity_l: number;
  shift_start: number;
  shift_end: number;
  available: boolean;
};
export type Unserved = { order_id: string; reason: string; penalty: number };
export type Schedule = {
  run_id: number;
  status: string;
  problem_type: string;
  algorithm: string;
  horizon_start: string;
  horizon_min: number;
  timezone: string;
  current_time_min: number;
  assignments: TaskAssignment[];
  routes: VehicleRoute[];
  unserved: Unserved[];
  resources: ResourceLane[];
  vehicles: VehicleInfo[];
  orders: OrderInfo[];
  travel_provenance: string;
  geometry_note: string;
};

export type Violation = {
  rule: string;
  severity: "error" | "warning" | "info";
  entity_type: string;
  entity_id: string;
  message: string;
  observed: Record<string, unknown>;
};
export type ValidationReport = {
  is_feasible: boolean;
  scope: string[];
  checked_rules: string[];
  violations: Violation[];
  unserved: Unserved[];
  stats: Record<string, unknown>;
};

export type MetricsOut = {
  run_id: number;
  algorithm: string;
  metrics: (Omit<Kpis, "cost"> & { cost: CostBreakdown; resource_utilization: Record<string, number> }) | null;
  solver_status: string | null;
  solver_objective: number | null;
  best_bound: number | null;
  gap: number | null;
  gap_note: string;
};

export type CompareRow = {
  run_id: number;
  algorithm: string;
  problem_type: string;
  status: string;
  solver_status: string | null;
  is_feasible: boolean | null;
  seed: number;
  runtime_ms: number | null;
  total_cost: number | null;
  cost: CostBreakdown | null;
  on_time_rate: number | null;
  total_lateness_min: number | null;
  total_distance_km: number | null;
  vehicles_used: number | null;
  orders_unserved: number | null;
  warehouse_makespan_min: number | null;
  end_to_end_makespan_min: number | null;
  avg_utilization: Record<string, number> | null;
  changed_tasks: number | null;
  stability_score: number | null;
  gap: number | null;
};
export type CompareOut = {
  scenario_id: number;
  snapshot_ids: number[];
  same_snapshot: boolean;
  objective_note: string;
  rows: CompareRow[];
};

export type Dashboard = {
  scenario_id: number;
  scenario_name: string;
  orders_by_status: Record<string, number>;
  orders_by_priority: Record<string, number>;
  resources: Record<string, number>;
  vehicles_by_status: Record<string, number>;
  runs_by_status: Record<string, number>;
  latest_runs: Run[];
  latest_success: Run | null;
  kpi_source: string;
  recent_events: { id: number; event_type: string; event_time_min: number; affected: string | null; created_at: string }[];
};

export type GeoPoint = {
  id: string;
  kind: "depot" | "customer";
  name: string;
  x_km: number;
  y_km: number;
  lat: number | null;
  lon: number | null;
  tw_start: number | null;
  tw_end: number | null;
};
export type Geo = { coordinate_provenance: string; travel_provenance: string; travel_notes: string; points: GeoPoint[] };
