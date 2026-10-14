/** Time helpers. Backend schedules use integer minutes from the scenario horizon start (UTC instant). */

export function minuteToDate(horizonStartIso: string, minute: number): Date {
  return new Date(new Date(horizonStartIso).getTime() + minute * 60_000);
}

const fmtCache = new Map<string, Intl.DateTimeFormat>();
function fmt(tz: string): Intl.DateTimeFormat {
  let f = fmtCache.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat("ko-KR", { timeZone: tz, hour: "2-digit", minute: "2-digit", hour12: false });
    fmtCache.set(tz, f);
  }
  return f;
}

/** Wall-clock "HH:MM" in the scenario timezone for a horizon-relative minute. */
export function clock(horizonStartIso: string, tz: string, minute: number): string {
  return fmt(tz).format(minuteToDate(horizonStartIso, minute));
}

/** Local minutes-of-day (e.g. 1500 = 01:00 next day) → "HH:MM(+1)". */
export function localMin(m: number): string {
  const day = Math.floor(m / 1440);
  const mm = ((m % 1440) + 1440) % 1440;
  const s = `${String(Math.floor(mm / 60)).padStart(2, "0")}:${String(mm % 60).padStart(2, "0")}`;
  return day > 0 ? `${s}(+${day})` : s;
}

export function parseHHMM(s: string): number | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(s.trim());
  if (!m) return null;
  const h = Number(m[1]);
  const mi = Number(m[2]);
  if (h > 47 || mi > 59) return null;
  return h * 60 + mi;
}

export function fmtDuration(min: number | null | undefined): string {
  if (min === null || min === undefined) return "–";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h ? `${h}시간 ${m}분` : `${m}분`;
}

export function fmtDateTime(iso: string | null | undefined, tz = "Asia/Seoul"): string {
  if (!iso) return "–";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: tz,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

export function krw(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  return `₩${Math.round(n).toLocaleString("ko-KR")}`;
}

export function pct(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined) return "–";
  return `${(n * 100).toFixed(digits)}%`;
}
