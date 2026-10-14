import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";

export function renderWithProviders(ui: ReactElement, route = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        {ui}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Route-table fetch mock: keys are "METHOD /path" (path after /api/v1, without query). */
export function mockFetch(routes: Record<string, unknown | ((body: unknown) => unknown)>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const key = `${init?.method ?? "GET"} ${path}`;
    const hit = routes[key];
    if (hit === undefined) {
      return new Response(JSON.stringify({ error: { code: "not_found", message: `no mock for ${key}` } }), {
        status: 404,
        headers: { "content-type": "application/json" },
      });
    }
    const body = init?.body && typeof init.body === "string" ? JSON.parse(init.body) : undefined;
    const data = typeof hit === "function" ? (hit as (b: unknown) => unknown)(body) : hit;
    if (data instanceof Response) return data;
    return new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });
  });
}
