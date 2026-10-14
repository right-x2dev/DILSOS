# Demo recording script (≈6 minutes)

Preparation (fresh database):
```bash
cd backend && alembic upgrade head && python -m app.seed.cli demo-scenarios
uvicorn app.main:app --port 8000  &  python -m app.tasks.db_worker  &  (cd ../frontend && npm run dev)
python ../scripts/demo_populate.py          # prints the run ids used below (e.g. integrated #6, breakdown base #19)
```

| Time | Screen | Say / show |
|---|---|---|
| 0:00 | Login | Demo banner: synthetic data, development account. |
| 0:20 | Scenarios | Four seeded scenarios; builder creates a deterministic world from a seed; input validation shows snapshot version + hash. |
| 0:50 | Optimisation console | Run `warehouse_cpsat` on *warehouse_bottleneck*: 202 → QUEUED → RUNNING → SUCCEEDED only after independent validation; solver metadata incl. gap/time-to-first-feasible. |
| 1:40 | Warehouse Gantt | Worker / station / forklift lanes, hatched off-shift & maintenance, filter an order → pick→pack arrow; red outline = cutoff missed. |
| 2:10 | Dock timeline | Integrated run #6: loading only after all co-loaded orders are packed; integrity warnings = 0. |
| 2:40 | Routes | Schematic map (synthetic km) + optional OSM view with labels; stop table with waits/lateness. |
| 3:10 | Journey | Release → pick → pack → dock wait → load → transit → delivery; heuristic main-cause attribution. |
| 3:40 | Compare | Routing experiment on one snapshot: insertion vs OR-Tools vs ALNS × 3 seeds; stats, stacked cost terms, CSV. |
| 4:20 | Disruption simulator | Vehicle breakdown 08:30 → KEEP / PARTIAL / FULL; recommendation with reason; before/after Gantt (frozen = dashed) and route diff. |
| 5:20 | Runs & audit | Parent run → v2 versions, seed, params, validation findings, audit log; export CSV/JSON. |
| 5:50 | Close | Tests/CI, honesty rules (no optimality claims, explicit unserved, provenance labels). |

Screenshots in `docs/screenshots/` are captured from this flow with
`SCREENSHOTS=1 SHOT_SCENARIO=4 SHOT_RUN=6 SHOT_BD_SCENARIO=3 SHOT_BD_BASE=19 npx playwright test e2e/screenshots.spec.ts`.
