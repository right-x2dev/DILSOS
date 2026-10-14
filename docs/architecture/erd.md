# Entity-relationship diagram (MySQL 8, migrations `0001`, `0002`)

All timestamps are stored as naive UTC `DATETIME` through the `UTCDateTime` type (naive input is rejected).
Durations/distances are integers (minutes / meters / kg / liters); money is `DECIMAL(14,2)`.
Published outputs (`schedule_assignments`, `routes`, `route_stops`, `shipments`, `scenario_snapshots`) are
append-only — an ORM guard raises on UPDATE/DELETE. Foreign keys use `RESTRICT` to preserve history, except
children of a run/snapshot/route (`CASCADE`).

```mermaid
erDiagram
  users ||--o{ audit_logs : writes
  facilities ||--o{ customers : has
  facilities ||--o{ skus : has
  facilities ||--o{ inventory_balances : has
  skus ||--o{ inventory_balances : stocked
  facilities ||--o{ orders : receives
  customers ||--o{ orders : places
  orders ||--o{ order_lines : contains
  skus ||--o{ order_lines : references
  facilities ||--o{ workers : employs
  facilities ||--o{ equipment : owns
  facilities ||--o{ pack_stations : has
  facilities ||--o{ docks : has
  facilities ||--o{ vehicles : operates
  facilities ||--o{ resource_calendars : schedules
  facilities ||--o{ travel_matrices : versions
  travel_matrices ||--o{ travel_matrix_entries : contains
  facilities ||--o{ scenarios : plans
  scenarios ||--o{ scenario_orders : selects
  orders ||--o{ scenario_orders : selected_in
  scenarios ||--o{ scenario_snapshots : "immutable versions"
  scenario_snapshots ||--o{ tasks : derives
  scenario_snapshots ||--o{ task_dependencies : derives
  scenarios ||--o{ schedule_runs : runs
  scenario_snapshots ||--o{ schedule_runs : input_of
  schedule_runs ||--o{ schedule_runs : "parent (reschedule version)"
  schedule_runs ||--o{ schedule_assignments : publishes
  schedule_runs ||--o{ routes : publishes
  routes ||--o{ route_stops : visits
  schedule_runs ||--o{ shipments : "served/unserved per order"
  scenarios ||--o{ disruption_events : "idempotent events"
  schedule_runs ||--o{ reschedule_runs : base
  disruption_events ||--o{ reschedule_runs : triggers

  schedule_runs {
    bigint id PK
    bigint scenario_id FK
    bigint snapshot_id FK
    bigint parent_run_id FK
    int schedule_version
    string problem_type
    string algorithm
    json params
    int seed
    float time_limit_s
    string status "QUEUED|RUNNING|SUCCEEDED|FAILED|CANCELLED"
    string solver_status "FEASIBLE|OPTIMAL|INFEASIBLE|TIME_LIMIT|ERROR"
    bool cancel_requested
    bool is_feasible
    decimal objective_total
    json metrics
    json validation
    json solver_metadata
    int lock_version "optimistic concurrency"
  }
  scenario_snapshots {
    bigint id PK
    bigint scenario_id FK
    int version
    json content "full ScenarioSnapshot"
    string content_hash "sha256"
    string reason
  }
  disruption_events {
    bigint id PK
    bigint scenario_id FK
    string idempotency_key "unique per scenario"
    string event_type
    int event_time_min
    string affected_code
    json payload
  }
  reschedule_runs {
    bigint id PK
    bigint base_run_id FK
    bigint event_id FK
    string policy "KEEP|PARTIAL|FULL"
    int frozen_until_min
    bigint new_run_id FK
    float stability_score
    json summary
  }
```

Key indexes: `orders(facility_id, status)`, `orders(due_at)`, `schedule_runs(status, queued_at)`,
`schedule_runs(scenario_id, queued_at)`, `schedule_assignments(run_id, resource_code)`, `routes(run_id, vehicle_code)`,
`disruption_events(scenario_id, event_time_min)`, unique `(facility_id, code)` on every master table,
unique `(scenario_id, version)` on snapshots, unique `(scenario_id, idempotency_key)` on events.
