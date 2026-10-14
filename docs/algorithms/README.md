# Algorithm catalogue

Every algorithm implements `SchedulingAlgorithm.solve(snapshot, config, cancel) -> ScheduleResult`, is registered in
`app/optimization/catalog.py`, and is evaluated/validated by the same shared code (`common/objectives.py`,
`common/validator.py`). `GET /api/v1/algorithms` lists them with availability detection.

| Name | Problem | Kind | Idea | Determinism | Notes |
|---|---|---|---|---|---|
| `warehouse_fifo` / `_edd` / `_spt` | warehouse | heuristic | dispatch priority + serial SGS (multi-resource, gap filling) | deterministic | never `OPTIMAL` |
| `warehouse_cpsat` | warehouse | exact | optional intervals, NoOverlap, shifts/downtime, EDD warm start | 8 workers ⇒ time-limit dependent; `num_workers=1` deterministic | gap reported |
| `warehouse_sa` / `_tabu` / `_ga` | warehouse | metaheuristic | order-permutation encoding → SGS decoder; validator-checked incumbents | seed + `max_evaluations` ⇒ reproducible | P5 |
| `dock_fifo` / `dock_edd` | dock | heuristic | earliest feasible compatible dock, ready/slack order, hard repair | deterministic | fixed upstream & grouping |
| `dock_cpsat` | dock | exact (sub-problem) | dock NoOverlap + exact max-plus delivery timing | as CP-SAT | result `FEASIBLE` (conditional optimality) |
| `routing_nn` | routing | heuristic | time-oriented nearest neighbour (0.5 travel + 0.3 wait + 0.2 urgency) | deterministic | leftovers cheapest-inserted |
| `routing_insertion` | routing | heuristic | cheapest insertion with cached per-route deltas | deterministic | |
| `routing_ortools` | routing | metaheuristic | OR-Tools Routing, GLS, warm start | time-limit dependent | no gap |
| `routing_alns` | routing | metaheuristic | 4 destroy / 2 repair operators, adaptive weights, SA acceptance | seed + `max_iterations` ⇒ reproducible | P5 |
| `integrated_sequential` | integrated | decomposition | warehouse → VRPTW → docks (one pass) | deterministic with deterministic sub-solvers | params choose sub-solvers |
| `integrated_iterative` | integrated | decomposition | cutoff feedback loop, accept only feasible improvements | idem | P4 |
| `reschedule_keep` / `_partial` / `_full` | warehouse, integrated | decomposition | policy freeze + repair / re-optimise | idem | P6 |

## Solver availability & fallbacks

OR-Tools is detected with `importlib.util.find_spec`; unavailable algorithms are listed as `available=false` and
rejected at enqueue time (`422 solver_unavailable`). If CP-SAT finds no incumbent within the budget, the warehouse
model returns the EDD warm start flagged `fallback_used` (still independently validated). No commercial solver is
required; SciPy/Gurobi network models (spec P8) are not implemented.

## Honesty rules enforced in code

* Heuristic/metaheuristic/decomposition results are never labelled `OPTIMAL`.
* A run is `SUCCEEDED` only if the independent validator reports no error-severity violation.
* Unserved demand is always explicit (`unserved_order_ids` + reason + penalty) — validator rule U1/W1/R1.
* Travel provenance and schematic geometry are attached to every routed schedule.
