// Number and date formatting shared by server and client components.

function zhAmount(x: number): string {
  const a = Math.abs(x);
  if (a < 1e4) return a.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (a < 1e6) return `${(a / 1e4).toFixed(1)}万`;
  if (a < 1e8) return `${Math.round(a / 1e4).toLocaleString("en-US")}万`;
  return `${(a / 1e8).toFixed(1)}亿`;
}

/** $36.2万, $4,112万, $16.2亿 */
export function usdZh(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return `${x < 0 ? "-" : ""}$${zhAmount(x)}`;
}

/** Signed USD change: +$12.3万 */
export function usdDelta(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  return `${x >= 0 ? "+" : "-"}$${zhAmount(x)}`;
}

export function countZh(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  return zhAmount(x);
}

/** 8h funding rate as a signed percent with 4 decimals: -0.3419% */
export function rate(x: number | null | undefined, digits = 4): string {
  if (x === null || x === undefined) return "—";
  const s = (x * 100).toFixed(digits);
  return `${x > 0 ? "+" : ""}${s}%`;
}

export function pct(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  return `${x > 0 ? "+" : ""}${(x * 100).toFixed(digits)}%`;
}

export function plainPct(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

export function price(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  const digits = x >= 1000 ? 2 : x >= 1 ? 2 : 4;
  return x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Tone class for a signed number: up (teal), down (red) or flat. */
export function tone(x: number | null | undefined): "up" | "down" | "flat" {
  if (x === null || x === undefined || x === 0) return "flat";
  return x > 0 ? "up" : "down";
}

const UTC_FMT = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "UTC",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** "11/24 03:26 UTC" */
export function utcStamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  return `${UTC_FMT.format(new Date(iso)).replace(/\//g, "/")} UTC`;
}

const HKT_FMT = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Hong_Kong",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** "11/24 13:13" in Hong Kong time (UTC+8). */
export function hktStamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  return HKT_FMT.format(new Date(iso));
}

export function monthDay(isoDate: string): string {
  const [, m, d] = isoDate.slice(0, 10).split("-");
  return `${m}/${d}`;
}

/** Only http(s) links from external feeds are rendered as hrefs. */
export function safeHref(url: string): string | undefined {
  return /^https?:\/\//i.test(url) ? url : undefined;
}

export function daysBetween(fromIso: string, toIso: string): number {
  const a = Date.parse(fromIso.slice(0, 10));
  const b = Date.parse(toIso.slice(0, 10));
  return Math.round((b - a) / 86_400_000);
}
