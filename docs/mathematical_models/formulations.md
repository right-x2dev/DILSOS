# Mathematical models and solver-to-domain mapping

Notation: time in integer minutes from the scenario horizon start `t = 0` (a UTC instant), horizon `H`.
`P(j)` processing time, `Pred(j)` predecessors, `R_q(j)` eligible resources of requirement `q` of task `j`.

## 1. Shared objective (evaluator — identical for every algorithm)

```
total_cost = Σ_v∈used fixed_v                              (transport_fixed)
           + Σ_v km_v · cost_per_km_v                        (distance_cost)
           + Σ_j Σ_worker∈j  P(j) · hourly_cost/60           (labor_cost)
           + Σ_j Σ_worker∈j  max(0, e_j − max(s_j, reg_end)) · hourly·premium/60   (overtime_cost)
           + Σ_o served  late_o · late_penalty_per_min · priority_o                 (late_delivery_penalty)
           + Σ_o unserved (≠cancelled) unserved_penalty · priority_o                (unserved_penalty)
           + changed_tasks · change_penalty_task + changed_routes · change_penalty_route (schedule_change_penalty)
late_o = max(0, delivery_start_o − tw_end_c(o))   if the scope routes orders
       = max(0, pack_end_o − due_o)                 for the warehouse-only scope
```
Solver-internal objectives (CP-SAT, OR-Tools Routing) approximate these terms with integer coefficients; reported
`gap` refers to the solver's own objective and is shown only for CP-SAT. Comparisons always use `total_cost`.

## 2. Warehouse scheduling (multi-resource RCPSP) — `warehouse_cpsat`

Tasks: per order one PICK (worker with `pick` [+ zone skill, e.g. `cold`] [+ forklift if weight > 120 kg]) and one
PACK (worker with `pack` **and** a pack station); PICK → PACK.

```
vars   s_j ∈ [max(r_j, now), H − P(j)],  e_j = s_j + P(j)
       x_{j,q,k} ∈ {0,1}  (optional interval [s_j, e_j) on resource k),  served_o ∈ {0,1}
s.t.   Σ_{k∈R_q(j)} x_{j,q,k} = served_{o(j)}            ∀ j, q        (exactly one eligible resource)
       NoOverlap_k({optional intervals} ∪ {blocked off-shift/downtime} ∪ {frozen work})   ∀ k
       s_j ≥ e_i                                         ∀ i ∈ Pred(j)
       late_o ≥ max_j∈o e_j − due_o   (if served_o)
       ot_{j,k} ≥ e_j − reg_end_k     (if x_{j,·,k})
min    100·Σ labor + Σ overtime(×100 scale) + 100·Σ late·pen + 100·Σ (1−served)·unserved_pen + 100·Σ C_o
```
The last term (1 KRW per completion minute) is a compaction tie-break. Warm start: EDD serial-SGS schedule.
Status mapping: CP-SAT OPTIMAL → `OPTIMAL`; FEASIBLE at time limit → `TIME_LIMIT` with incumbent; no incumbent →
documented fallback to the EDD warm start (`fallback_used`).

**Dispatch rules (FIFO/EDD/SPT)** and the **SA/Tabu/GA decoder** use the same serial schedule-generation scheme:
take the highest-priority eligible task, place it at the earliest time where one eligible resource per
requirement is simultaneously free inside its availability windows (gap filling, no preemption); if impossible
within `H` the order becomes explicitly unserved and its placed tasks are rolled back.

## 3. Dock appointments — `dock_cpsat`

For each route `r` (fixed stop sequence, vehicle `v`):
```
served_r ∈ {0,1};  s_r ≥ max(ready_r, shift_start_v, now)  with ready_r = max_{o∈r} pack_end_o
e_r = s_r + load_base + load_per_order·|r|;  dep_r = e_r
Σ_{d compatible} x_{r,d} = served_r;  NoOverlap_d(loads ∪ dock-closed ∪ frozen loads)
A_1 = dep_r + T(depot, c_1);  S_k = max(A_k, a_k);  A_{k+1} = S_k + svc_k + T(c_k, c_{k+1})
late_k ≥ S_k − b_k (soft)  or  S_k ≤ b_k (hard);   S_last + svc + T(c_last, depot) ≤ shift_end_v
min Σ late·pen·priority + Σ (1−served_r)·unserved_pen + Σ e_r
```
The max-plus delivery propagation is modelled exactly (`AddMaxEquality`), so the dock decision is optimal *for the
given upstream plan and stop sequences* — the integrated result is still reported as `FEASIBLE`.

## 4. VRPTW — `routing_*`

Units: orders of one customer (aggregated stop; split if larger than the biggest vehicle). For each vehicle `v`:
route `depot → u_1 … u_n → depot`, capacity in kg and liters, `start_v ≥ max(shift_start_v, now, ready_u + load(n_u))`,
arrival/service propagation as above with waiting allowed, `return ≤ min(shift_end_v, H)`, time windows hard
(`[a,b]`) or soft (`[a, ∞)` + penalty per minute late × priority). Dropping a unit costs the unserved penalty
(disjunction) → infeasible demand becomes explicit, never silent.
* **OR-Tools Routing**: weight/volume dimensions, time dimension with slack, soft upper bounds, per-vehicle arc cost
  (`cost_per_km`), fixed vehicle cost, conditional readiness `start_v ≥ need_u·[VehicleVar(u)=v]`, PATH_CHEAPEST_ARC +
  Guided Local Search, warm start from cheapest insertion. No optimality proof → `FEASIBLE`.
* **Routing-only readiness assumption**: goods ready at order release (warehouse instantaneous).
  In `integrated`, readiness is the real packing completion plus estimated loading time; the dock stage then adds the
  true loading time and dock contention.

## 5. Integrated coordination — `integrated_iterative`

```
x⁰ = sequential(warehouse → readiness → VRPTW → docks)
repeat k = 1..K:
   cutoff_o = min(latest on-time departure of route(o), departure_r − observed_late_r) − load_r − margin
   due'_o  = min(due_o, cutoff_o)                 (working copy only; evaluation always on the original)
   x' = sequential(warehouse(due'), VRPTW warm-started from x^{k−1}, docks)
   accept x' iff validate(x') ∧ cost(x') < cost(x^{k−1});  else margin ← margin ± diversification
stop: K, time budget, cancellation, 2 non-improving iterations
```

## 6. Rescheduling

`executed` = work started before the event time `t` (frozen forever, copied verbatim). `affected` = non-executed work
invalidated by the event (+ closure: tasks of an affected order, its route). KEEP freezes everything unaffected;
PARTIAL additionally opens tasks on disrupted workers/stations/equipment and every not-yet-loading route; FULL freezes only
executed work plus the committed window `[t, t+w)`. PARTIAL/FULL evaluate the KEEP plan (valid under their looser freeze)
as a candidate and adopt the re-optimised plan only if not more expensive. Stability:
`stability = 1 − (changed tasks + changed routes) / (tasks + routes in either version)`.

## 7. Assumptions & known limitations (also shown in the UI)

Single DC; deterministic durations; one delivery window per customer; no split delivery; one route per vehicle per
day; no preemption; travel times are synthetic euclidean × 1.3 at 30 km/h (not road data); breakdown after departure
is reported, not recovered; no global optimality is claimed for any integrated, routing or metaheuristic result.
