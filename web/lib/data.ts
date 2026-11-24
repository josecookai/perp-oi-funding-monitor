import "server-only";

import historyJson from "@/data/history.json";
import insightsJson from "@/data/insights.json";
import metaJson from "@/data/meta.json";
import reportJson from "@/data/report.json";

import type {
  Bucket,
  HistoryFile,
  Insight,
  InsightsFile,
  MetaFile,
  Report,
  ReportRow,
  ReportSection,
  Side,
  Venue,
} from "./types";

// The JSON is bundled at build time; every page is prerendered from it.
export const report = reportJson as unknown as Report;
export const insights = insightsJson as unknown as InsightsFile;
export const history = historyJson as unknown as HistoryFile;
export const meta = metaJson as unknown as MetaFile;

export const VENUES: Venue[] = ["binance", "hyperliquid"];

export function section(venue: Venue): ReportSection | undefined {
  return report.sections.find((s) => s.venue === venue);
}

export function marketKey(venue: Venue, ticker: string): string {
  return `${venue}:${ticker}`;
}

/** URL slug for a market page: "binance-FWDI". */
export function marketSlug(venue: Venue, ticker: string): string {
  return `${venue}-${encodeURIComponent(ticker)}`;
}

export function parseSlug(slug: string): { venue: Venue; ticker: string } | null {
  const decoded = decodeURIComponent(slug);
  const dash = decoded.indexOf("-");
  if (dash < 0) return null;
  const venue = decoded.slice(0, dash);
  if (venue !== "binance" && venue !== "hyperliquid") return null;
  return { venue, ticker: decoded.slice(dash + 1) };
}

export function findRow(venue: Venue, ticker: string): ReportRow | undefined {
  return section(venue)?.rows.find((r) => r.ticker === ticker);
}

export function insightFor(venue: Venue, ticker: string): Insight | undefined {
  return insights.items.find((i) => i.venue === venue && i.ticker === ticker);
}

/** Funding top-N cards for one side and volume bucket, both venues, most extreme first. */
export function insightsFor(side: Side, bucket: Bucket): Insight[] {
  return insights.items
    .filter((i) => i.side === side && i.bucket === bucket)
    .toSorted((a, b) => Math.abs(b.funding_8h) - Math.abs(a.funding_8h));
}

export function feedPath(side: Side, bucket: Bucket): string {
  const base = bucket === "liquid" ? "" : "/thin";
  return side === "negative" ? base || "/" : `${base}/positive`;
}

export function rowsByTickers(venue: Venue, tickers: string[]): ReportRow[] {
  const rows = section(venue)?.rows ?? [];
  return tickers
    .map((t) => rows.find((r) => r.ticker === t))
    .filter((r): r is ReportRow => r !== undefined);
}

export function allMarkets(): { venue: Venue; row: ReportRow }[] {
  return report.sections.flatMap((s) => s.rows.map((row) => ({ venue: s.venue, row })));
}
