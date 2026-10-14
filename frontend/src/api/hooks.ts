/** TanStack Query hooks — every screen reads data only through these (no client-side fabrication). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  Algorithm,
  CompareOut,
  Dashboard,
  DockRes,
  Geo,
  InputValidation,
  MetricsOut,
  Order,
  Page,
  Run,
  Scenario,
  Schedule,
  ValidationReport,
  VehicleRes,
  Worker,
} from "../types/api";

const qs = (o: Record<string, unknown>) =>
  Object.entries(o)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join("&");

export const useScenarios = () =>
  useQuery({ queryKey: ["scenarios"], queryFn: () => api<Page<Scenario>>("/scenarios?limit=200") });

export const useScenario = (id: number | null) =>
  useQuery({ queryKey: ["scenario", id], queryFn: () => api<Scenario>(`/scenarios/${id}`), enabled: !!id });

export const useAlgorithms = () =>
  useQuery({ queryKey: ["algorithms"], queryFn: () => api<Algorithm[]>("/algorithms"), staleTime: 300_000 });

export const useDashboard = (scenarioId: number | null) =>
  useQuery({
    queryKey: ["dashboard", scenarioId],
    queryFn: () => api<Dashboard>(`/dashboard/summary?scenario_id=${scenarioId}`),
    enabled: !!scenarioId,
    refetchInterval: 10_000,
  });

export const useOrders = (p: { scenario_id?: number | null; status?: string; priority?: string; q?: string; limit: number; offset: number }) =>
  useQuery({
    queryKey: ["orders", p],
    queryFn: () => api<Page<Order>>(`/orders?${qs(p)}`),
    enabled: !!p.scenario_id,
    placeholderData: (prev) => prev,
  });

export const useWorkers = (facilityId?: number) =>
  useQuery({
    queryKey: ["workers", facilityId],
    queryFn: () => api<Worker[]>(`/resources/workers?facility_id=${facilityId}`),
    enabled: !!facilityId,
  });
export const useVehicles = (facilityId?: number) =>
  useQuery({
    queryKey: ["vehicles", facilityId],
    queryFn: () => api<VehicleRes[]>(`/resources/vehicles?facility_id=${facilityId}`),
    enabled: !!facilityId,
  });
export const useDocks = (facilityId?: number) =>
  useQuery({
    queryKey: ["docks", facilityId],
    queryFn: () => api<DockRes[]>(`/resources/docks?facility_id=${facilityId}`),
    enabled: !!facilityId,
  });

export const useRuns = (scenarioId: number | null, extra: Record<string, unknown> = {}) =>
  useQuery({
    queryKey: ["runs", scenarioId, extra],
    queryFn: () => api<Page<Run>>(`/runs?${qs({ scenario_id: scenarioId, limit: 100, ...extra })}`),
    enabled: !!scenarioId,
    refetchInterval: (q) => (q.state.data?.items.some((r) => r.status === "QUEUED" || r.status === "RUNNING") ? 1500 : false),
  });

/** Polls while the run is QUEUED/RUNNING (SSE is a documented later option). */
export const useRun = (id: number | null) =>
  useQuery({
    queryKey: ["run", id],
    queryFn: () => api<Run>(`/runs/${id}`),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data && ["QUEUED", "RUNNING"].includes(q.state.data.status) ? 1000 : false),
  });

export const useSchedule = (id: number | null, enabled = true) =>
  useQuery({
    queryKey: ["schedule", id],
    queryFn: () => api<Schedule>(`/runs/${id}/schedule`),
    enabled: !!id && enabled,
    staleTime: Infinity, // published schedules are immutable
  });

export const useValidation = (id: number | null, enabled = true) =>
  useQuery({
    queryKey: ["validation", id],
    queryFn: () => api<ValidationReport>(`/runs/${id}/validation`),
    enabled: !!id && enabled,
    retry: false,
  });

export const useMetrics = (id: number | null, enabled = true) =>
  useQuery({ queryKey: ["metrics", id], queryFn: () => api<MetricsOut>(`/runs/${id}/metrics`), enabled: !!id && enabled });

export const useCompare = (id: number | null, ids?: string) =>
  useQuery({
    queryKey: ["compare", id, ids],
    queryFn: () => api<CompareOut>(`/runs/${id}/compare${ids ? `?ids=${ids}` : ""}`),
    enabled: !!id,
  });

export const useGeo = (scenarioId: number | null) =>
  useQuery({ queryKey: ["geo", scenarioId], queryFn: () => api<Geo>(`/scenarios/${scenarioId}/geo`), enabled: !!scenarioId });

export function useCreateRun(scenarioId: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { problem_type: string; algorithm: string; time_limit_s: number; seed: number; params?: Record<string, unknown> }) =>
      api<Run>(`/scenarios/${scenarioId}/runs`, { body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs", scenarioId] });
      qc.invalidateQueries({ queryKey: ["dashboard", scenarioId] });
    },
  });
}

export function useCancelRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<Run>(`/runs/${id}/cancel`, { method: "POST" }),
    onSuccess: (r) => qc.invalidateQueries({ queryKey: ["run", r.id] }),
  });
}

export function useValidateScenario() {
  return useMutation({ mutationFn: (id: number) => api<InputValidation>(`/scenarios/${id}/validate`, { method: "POST" }) });
}

export function useInvalidate() {
  const qc = useQueryClient();
  return (...keys: unknown[][]) => keys.forEach((k) => qc.invalidateQueries({ queryKey: k }));
}
