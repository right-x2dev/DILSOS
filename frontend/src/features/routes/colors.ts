export const ROUTE_COLORS = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#4d7c0f", "#9333ea", "#ea580c"];

export function routeColor(i: number): string {
  return ROUTE_COLORS[i % ROUTE_COLORS.length];
}
