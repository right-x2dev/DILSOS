/** UI-only state (selected scenario / run). Server state lives in TanStack Query. */
import { create } from "zustand";

const KEY = "dilsos.ui";

type Persisted = { scenarioId: number | null; runId: number | null };

function load(): Persisted {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return { scenarioId: null, runId: null, ...JSON.parse(raw) };
  } catch {
    /* ignore */
  }
  return { scenarioId: null, runId: null };
}

function save(p: Persisted) {
  try {
    localStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    /* ignore */
  }
}

type UiState = Persisted & {
  setScenario: (id: number | null) => void;
  setRun: (id: number | null) => void;
};

export const useUi = create<UiState>((set, get) => ({
  ...load(),
  setScenario(id) {
    set({ scenarioId: id, runId: get().scenarioId === id ? get().runId : null });
    save({ scenarioId: id, runId: get().runId });
  },
  setRun(id) {
    set({ runId: id });
    save({ scenarioId: get().scenarioId, runId: id });
  },
}));
