# Case study — DILSOS: coupled warehouse–dock–delivery scheduling with stable rescheduling

*All numbers below come from runs in this repository on synthetic data (seeded generator, synthetic euclidean travel
times, synthetic KRW coefficients). They demonstrate method behaviour, not real-world business impact.*

## 1. Problem
A distribution center must decide, for one operating day, **who picks and packs which order when**, **which dock and when
each vehicle is loaded**, and **which vehicle visits which customers in what order** — under shifts, downtime, skills,
forklift needs, pack-station and dock capacity, vehicle weight/volume, and customer time windows. These decisions are
coupled: a truck cannot depart until *every* order on it is packed and loaded, so warehouse sequencing directly
determines delivery lateness. During the day, disruptions (absences, outages, breakdowns, urgent orders, traffic) require
re-planning without rewriting work already executed.

## 2. What I built
* A full-stack platform (React/TypeScript, FastAPI, MySQL 8, Celery/Redis or a DB-polling worker, Docker Compose, CI).
* An optimisation engine with a **single contract** (`ScenarioSnapshot → ScheduleResult`), a **shared evaluator**
  (7 explicit cost terms + KPIs) and an **independent validator** implementing the spec's feasibility rules
  (coverage, precedence, eligibility, availability, unit capacity, inventory, frozen history, dock readiness, capacity,
  time propagation, windows, shifts, distance consistency). Publication is gated by the validator.
* 19 registered algorithms: dispatch rules + serial SGS, CP-SAT (warehouse and dock), SA/Tabu/GA, nearest neighbour,
  cheapest insertion, OR-Tools Routing, ALNS, sequential and iterative integrated coordination, and three rescheduling
  policies.
* Immutable, hashed scenario snapshots so every run is reproducible after master data changes; append-only outputs;
  versioned rescheduled schedules linked to their parent.

## 3. Key engineering decisions
| Decision | Why |
|---|---|
| Integer minutes from a UTC horizon start; integer meters/kg/liters | exact validation, integral CP models, explicit timezone conversion only at the edges |
| Feasible-by-construction encodings (SGS decoder) for SA/Tabu/GA | metaheuristics never produce infeasible incumbents; validator still checks every new best |
| Dock CP-SAT models the max-plus delivery propagation exactly | dock choices are evaluated by their real downstream lateness, not a proxy |
| Iterative coordination accepts only validated improvements | keeps the best feasible incumbent; diversification is controlled and logged |
| PARTIAL/FULL evaluate the KEEP plan as a candidate | a re-optimiser can never make the published plan worse than minimal repair under the same freeze |
| Min-max normalised policy scores | found in a browser check that raw ratios let a 3 ms runtime dominate a 4.8× cost difference; fixed + regression test |

## 4. Evidence (measured)
**Warehouse (quick benchmark, 5 s budget, 8 CPUs):** CP-SAT achieves the lowest cost on every instance and proves
optimality on `small-s1` (gap 0); Tabu/SA/GA (≤600 evaluations, ≈0.3 s) beat all dispatch rules on the small instances;
on the bottleneck scenario SPT is 77 % more expensive than EDD because of 207 min of cutoff lateness.

**Routing:** on the bottleneck instance OR-Tools (8 s) 676,598 KRW; ALNS (200 iterations, ≈1 s) best-of-3 678,819
(+0.3 %) with mean 691,488; cheapest insertion 974,978; nearest neighbour 1,093,226. On `peak_demand` (10 s) ALNS found
4,557,891 vs OR-Tools 4,618,214 with 7 instead of 8 vehicles.

**Coupling:** integrated sequential vs iterative coordination on the same snapshot — bottleneck 2,369,928 → 2,123,237
(−10.4 %, lateness 995 → 845 min), peak 6,046,396 → 5,974,396, vehicle_breakdown 1,204,656 → 1,191,656, normal day
590,576 → 589,559. The order-journey view attributes most remaining lateness to waiting for co-loaded orders at the dock.

**Rescheduling (vehicle breakdown at 08:30, no spare vehicle):**
| Policy | Total cost | Unserved | Changed tasks / routes | Stability |
|---|---|---|---|---|
| KEEP | 6,996,387 | 16 | 1 / 1 | 0.98 |
| PARTIAL (recommended) | 1,449,577 | 0 | 3 / 5 | 0.93 |
| FULL | 1,514,949 | 0 | 35 / 5 | 0.64 |

PARTIAL keeps the whole warehouse plan and re-routes the unstarted routes; FULL re-plans the warehouse as well and pays
change penalties for it. Across 7 event types × 3 policies, every result passed validation, executed history was
byte-identical and nothing was re-planned into the past (automated tests).

## 5. Quality
Backend: unit, solver, property-based (Hypothesis corrupts schedules — the validator must catch every corruption),
API integration (auth, validation errors, idempotency, optimistic concurrency, queue claim/cancel/failure, immutability),
run on SQLite locally and MySQL 8.4 in CI. Frontend: Vitest + Testing Library for every screen's data logic, and a
Playwright E2E smoke covering login → warehouse run → Gantt → routing → map → disruption → comparison against the real
stack.

## 6. Trade-offs & limitations
* No global optimality claims for routing, integrated or rescheduled plans (local search / decomposition).
* Synthetic travel model; straight-line geometry is labelled schematic. A routing provider (OSRM) would slot in as a new
  `TravelMatrix.provenance`.
* Single DC, one route per vehicle, no preemption, breakdown after departure reported rather than recovered.
* The rate limiter is per process; multiple API replicas need a shared limiter.
* Docker images are verified in CI, not on the development laptop (no Docker installed there).

## 7. What I would do next
Rolling multi-trip vehicles, OSRM travel times with provenance, an integrated ALNS spanning warehouse and routing moves,
the full benchmark suite on medium/large instances, and the optional MILP inventory/network planner.
