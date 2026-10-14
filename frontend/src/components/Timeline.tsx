/**
 * Generic SVG lane timeline (warehouse Gantt, dock timeline, journey view).
 * Every bar/lane is passed in from API data; the component draws, it never invents values.
 */
import { useMemo, useState, type ReactNode } from "react";
import type { Interval } from "../types/api";

export type Lane = { id: string; label: string; sublabel?: string; available?: Interval[]; group?: string };
export type Bar = {
  id: string;
  lane: string;
  start: number;
  end: number;
  color: string;
  label?: string;
  tooltip: string[];
  frozen?: boolean;
  faded?: boolean;
  outline?: string;
  warn?: boolean;
};
export type Link = { from: string; to: string; color?: string };
export type Marker = { at: number; label: string; color: string; dashed?: boolean };

type Props = {
  lanes: Lane[];
  bars: Bar[];
  links?: Link[];
  markers?: Marker[];
  min: number;
  max: number;
  pxPerMin: number;
  tickLabel: (m: number) => string;
  onBarClick?: (b: Bar) => void;
  rowH?: number;
  ariaLabel: string;
  legend?: ReactNode;
};

const LABEL_W = 132;
const AXIS_H = 26;

export function Timeline({ lanes, bars, links = [], markers = [], min, max, pxPerMin, tickLabel, onBarClick, rowH = 26, ariaLabel, legend }: Props) {
  const [hover, setHover] = useState<Bar | null>(null);
  const width = Math.max(200, (max - min) * pxPerMin);
  const height = AXIS_H + lanes.length * rowH + 4;
  const laneIdx = useMemo(() => new Map(lanes.map((l, i) => [l.id, i])), [lanes]);
  const barById = useMemo(() => new Map(bars.map((b) => [b.id, b])), [bars]);
  const x = (m: number) => (m - min) * pxPerMin;
  const tickStep = pxPerMin >= 4 ? 30 : pxPerMin >= 1.5 ? 60 : 120;
  const ticks: number[] = [];
  for (let t = Math.ceil(min / tickStep) * tickStep; t <= max; t += tickStep) ticks.push(t);

  return (
    <div className="rounded-lg border border-ink-200 bg-white">
      <div className="flex min-h-[2.25rem] flex-wrap items-center justify-between gap-2 border-b border-ink-100 px-3 py-1.5 text-xs text-ink-600" aria-live="polite">
        <div className="min-w-0 truncate">
          {hover ? (
            <span>
              <b className="text-ink-900">{hover.tooltip[0]}</b> {hover.tooltip.slice(1).join(" · ")}
            </span>
          ) : (
            <span className="text-ink-400">막대에 마우스를 올리면 상세가 표시됩니다</span>
          )}
        </div>
        {legend}
      </div>
      <div className="flex">
        <div className="shrink-0 border-r border-ink-100" style={{ width: LABEL_W }}>
          <div style={{ height: AXIS_H }} />
          {lanes.map((l) => (
            <div key={l.id} className="flex flex-col justify-center truncate px-2 text-xs" style={{ height: rowH }} title={l.sublabel}>
              <span className="truncate font-medium text-ink-800">{l.label}</span>
              {l.sublabel && rowH >= 26 && <span className="-mt-0.5 truncate text-[10px] text-ink-400">{l.sublabel}</span>}
            </div>
          ))}
        </div>
        <div className="overflow-x-auto">
          <svg role="img" aria-label={ariaLabel} width={width} height={height} className="block">
            {/* axis */}
            {ticks.map((t) => (
              <g key={t}>
                <line x1={x(t)} x2={x(t)} y1={AXIS_H - 4} y2={height} stroke="#e9edf3" />
                <text x={x(t) + 2} y={14} fontSize={10} fill="#4a5568">
                  {tickLabel(t)}
                </text>
              </g>
            ))}
            {/* lanes + unavailability shading */}
            {lanes.map((l, i) => {
              const y = AXIS_H + i * rowH;
              const gaps: Interval[] = [];
              if (l.available) {
                let cur = min;
                for (const w of [...l.available].sort((a, b) => a.start - b.start)) {
                  if (w.start > cur) gaps.push({ start: cur, end: Math.min(w.start, max) });
                  cur = Math.max(cur, w.end);
                }
                if (cur < max) gaps.push({ start: cur, end: max });
              }
              return (
                <g key={l.id}>
                  <rect x={0} y={y} width={width} height={rowH} fill={i % 2 ? "#fafbfc" : "#ffffff"} />
                  {gaps.map((g, k) => (
                    <rect key={k} x={x(g.start)} y={y + 1} width={Math.max(0, x(g.end) - x(g.start))} height={rowH - 2} fill="url(#offshift)">
                      <title>{`${l.label}: 비가용 (교대 외/정비) ${tickLabel(g.start)}–${tickLabel(g.end)}`}</title>
                    </rect>
                  ))}
                </g>
              );
            })}
            <defs>
              <pattern id="offshift" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width="6" height="6" fill="#eef1f5" />
                <line x1="0" y1="0" x2="0" y2="6" stroke="#d5dbe4" strokeWidth="2" />
              </pattern>
              <marker id="arrow" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                <path d="M0,0 L6,3 L0,6 z" fill="#64748b" />
              </marker>
            </defs>
            {/* bars */}
            {bars.map((b) => {
              const li = laneIdx.get(b.lane);
              if (li === undefined) return null;
              const y = AXIS_H + li * rowH + 3;
              const w = Math.max(1.5, x(b.end) - x(b.start));
              return (
                <g
                  key={b.id}
                  onMouseEnter={() => setHover(b)}
                  onMouseLeave={() => setHover(null)}
                  onClick={() => onBarClick?.(b)}
                  style={{ cursor: onBarClick ? "pointer" : "default" }}
                  opacity={b.faded ? 0.25 : 1}
                >
                  <rect
                    x={x(b.start)}
                    y={y}
                    width={w}
                    height={rowH - 6}
                    rx={3}
                    fill={b.color}
                    stroke={b.warn ? "#dc2626" : (b.outline ?? (b.frozen ? "#111827" : "none"))}
                    strokeWidth={b.warn || b.outline || b.frozen ? 1.5 : 0}
                    strokeDasharray={b.frozen ? "3 2" : undefined}
                  >
                    <title>{b.tooltip.join("\n")}</title>
                  </rect>
                  {b.label && w > 34 && (
                    <text x={x(b.start) + 3} y={y + (rowH - 6) / 2 + 3.5} fontSize={10} fill="#fff" pointerEvents="none">
                      {b.label}
                    </text>
                  )}
                </g>
              );
            })}
            {/* dependency links */}
            {links.map((lk, i) => {
              const a = barById.get(lk.from);
              const b = barById.get(lk.to);
              if (!a || !b) return null;
              const ya = AXIS_H + (laneIdx.get(a.lane) ?? 0) * rowH + rowH / 2;
              const yb = AXIS_H + (laneIdx.get(b.lane) ?? 0) * rowH + rowH / 2;
              const xa = x(a.end);
              const xb = x(b.start);
              return (
                <path
                  key={i}
                  d={`M${xa},${ya} C${xa + 12},${ya} ${xb - 12},${yb} ${xb},${yb}`}
                  fill="none"
                  stroke={lk.color ?? "#64748b"}
                  strokeWidth={1.2}
                  markerEnd="url(#arrow)"
                />
              );
            })}
            {markers.map((mk, i) => (
              <g key={i}>
                <line x1={x(mk.at)} x2={x(mk.at)} y1={AXIS_H - 6} y2={height} stroke={mk.color} strokeWidth={1.5} strokeDasharray={mk.dashed ? "4 3" : undefined} />
                <text x={x(mk.at) + 3} y={AXIS_H - 8} fontSize={10} fill={mk.color}>
                  {mk.label}
                </text>
              </g>
            ))}
          </svg>
        </div>
      </div>
    </div>
  );
}

export function LegendDot({ color, children }: { color: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
      {children}
    </span>
  );
}

export function ZoomControl({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const steps = [0.5, 0.75, 1, 1.5, 2, 3, 4, 6];
  const idx = Math.max(0, steps.findIndex((s) => s >= value));
  return (
    <div className="inline-flex items-center gap-1 text-xs" role="group" aria-label="확대/축소">
      <button className="rounded border border-ink-200 px-2 py-0.5 hover:bg-ink-50" onClick={() => onChange(steps[Math.max(0, idx - 1)])} aria-label="축소">
        −
      </button>
      <span className="w-14 text-center tabular-nums">{value}px/분</span>
      <button className="rounded border border-ink-200 px-2 py-0.5 hover:bg-ink-50" onClick={() => onChange(steps[Math.min(steps.length - 1, idx + 1)])} aria-label="확대">
        +
      </button>
    </div>
  );
}
