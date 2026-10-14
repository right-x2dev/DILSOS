# Experiments

All tables here are produced by actual runs of `app.experiments.benchmark` — nothing is hand-edited.

```bash
cd backend
python -m app.experiments.benchmark --suite quick --out ../docs/experiments   # ~5 min on 8 CPUs
python -m app.experiments.benchmark --suite full  --out ../docs/experiments   # longer; medium/large + 10 seeds
```

Files per suite: `benchmark_<suite>_raw.csv` (one row per run), `benchmark_<suite>_summary.md`
(best / mean / std / infeasible rate / runtime / time-to-first-feasible / CP-SAT gap) and
`benchmark_<suite>_meta.json` (budgets, instances, hardware, library versions, timestamp).

Protocol: identical snapshot and shared evaluator per (instance, problem); fixed wall-clock budget;
stochastic algorithms repeated with seeds `0..runs-1` and bounded by evaluation/iteration budgets so
results are reproducible independent of hardware speed (wall-clock limits remain as a safety cap);
every result passes the independent validator before it is counted as feasible.
Costs use synthetic coefficients (KRW) and synthetic euclidean travel times — they are not business-impact claims.
