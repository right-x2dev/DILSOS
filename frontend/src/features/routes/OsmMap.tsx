/**
 * Optional OpenStreetMap view. Coordinates are SYNTHETIC (derived from generated km offsets) and the
 * polylines are straight schematic segments — clearly labelled; no road geometry is invented.
 * Tile usage follows the OSM tile policy (attribution, light interactive use only).
 */
import "leaflet/dist/leaflet.css";
import { useState } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from "react-leaflet";
import type { Geo, Schedule } from "../../types/api";
import { routeColor } from "./colors";

export default function OsmMap({ geo, s, focus }: { geo: Geo; s: Schedule; focus: string | null }) {
  const [tileError, setTileError] = useState(false);
  const pts = geo.points.filter((p) => p.lat !== null && p.lon !== null);
  if (!pts.length) return <div className="text-sm text-ink-600">위경도 정보가 없어 지도를 표시할 수 없습니다. 도식 보기를 사용하세요.</div>;
  const byId = new Map(pts.map((p) => [p.id, p]));
  const depot = byId.get("DEPOT")!;
  const lats = pts.map((p) => p.lat!);
  const lons = pts.map((p) => p.lon!);
  return (
    <div className="relative">
      {tileError && (
        <div role="alert" className="absolute left-2 top-2 z-[1000] rounded bg-white/95 p-2 text-xs text-red-800 shadow">
          지도 타일을 불러오지 못했습니다 (오프라인/차단). 도식 보기와 경로 표는 계속 사용할 수 있습니다.
        </div>
      )}
      <div className="absolute bottom-2 left-2 z-[1000] rounded bg-white/90 px-2 py-1 text-[11px] text-amber-900 shadow">
        합성 좌표(표시용) · 점선 = 직선 도식(실제 도로 아님)
      </div>
      <MapContainer
        bounds={[
          [Math.min(...lats), Math.min(...lons)],
          [Math.max(...lats), Math.max(...lons)],
        ]}
        style={{ height: 520, width: "100%" }}
        scrollWheelZoom
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          eventHandlers={{ tileerror: () => setTileError(true) }}
        />
        {s.routes.map((r, i) => {
          const returned = r.stops.length > 0 && r.return_min > r.stops[r.stops.length - 1].departure_min;
          const line = [depot, ...r.stops.map((st) => byId.get(st.customer_id)).filter(Boolean), ...(returned ? [depot] : [])].map(
            (p) => [p!.lat!, p!.lon!] as [number, number],
          );
          const dim = focus && focus !== r.vehicle_id;
          return <Polyline key={r.vehicle_id} positions={line} pathOptions={{ color: routeColor(i), weight: dim ? 1 : 3, opacity: dim ? 0.2 : 0.85, dashArray: "6 4" }} />;
        })}
        {s.routes.flatMap((r, i) =>
          r.stops.map((st) => {
            const p = byId.get(st.customer_id);
            if (!p) return null;
            return (
              <CircleMarker key={`${r.vehicle_id}-${st.seq}`} center={[p.lat!, p.lon!]} radius={6} pathOptions={{ color: st.late_min ? "#dc2626" : "#ffffff", fillColor: routeColor(i), fillOpacity: 0.95, weight: 2 }}>
                <Tooltip>
                  {r.vehicle_id} #{st.seq} {p.name}
                  {st.late_min ? ` · 지연 ${st.late_min}분` : ""}
                </Tooltip>
              </CircleMarker>
            );
          }),
        )}
        <CircleMarker center={[depot.lat!, depot.lon!]} radius={9} pathOptions={{ color: "#0b2036", fillColor: "#0b2036", fillOpacity: 1 }}>
          <Tooltip permanent>DC</Tooltip>
        </CircleMarker>
      </MapContainer>
    </div>
  );
}
