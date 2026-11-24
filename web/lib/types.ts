// Shapes of the JSON files written by `perp-monitor site` (schema_version 1).

export type Venue = "binance" | "hyperliquid";

export interface ReportRow {
  ticker: string;
  market: string;
  source: string;
  is_new: boolean;
  oi_contracts: number;
  mark_price: number;
  oi_usd: number;
  prior_oi_usd: number | null;
  d_oi_usd: number | null;
  d_oi_pct: number | null;
  d_contracts_pct: number | null;
  funding_rate: number;
  funding_interval_hours: number;
  funding_8h: number;
  funding_apr: number;
  d_funding_8h: number | null;
  volume_24h_usd: number | null;
}

export interface ReportSection {
  venue: Venue;
  label: string;
  error: string | null;
  window: {
    hours: number | null;
    expected_hours: number;
    in_range: boolean;
    origin: string | null;
  };
  total_oi_usd: number;
  matched_d_oi_usd: number | null;
  rankings: {
    oi_gain: string[];
    oi_loss: string[];
    funding_negative: string[];
    funding_positive: string[];
  };
  rows: ReportRow[];
}

export interface CrossVenueRow {
  ticker: string;
  binance_funding_8h: number;
  hyperliquid_funding_8h: number;
  funding_spread_8h: number;
  binance_oi_usd: number;
  hyperliquid_oi_usd: number;
}

export interface Report {
  schema_version: number;
  generated_at: string;
  manual: boolean;
  top_n: number;
  allowlist_size: number;
  sections: ReportSection[];
  cross_venue: CrossVenueRow[];
}

export type Side = "negative" | "positive";
export type Bucket = "liquid" | "illiquid";
export type VolumeTier = "meaningful" | "thin" | "noise";
export type FundingPattern = "persistent" | "spike" | "mixed" | "insufficient";
export type ShortLevel = "high" | "elevated" | "moderate" | "low" | "unknown";
export type AnswerKey = "what" | "funding" | "catalyst" | "volume" | "short";

export interface Insight {
  key: string;
  venue: Venue;
  ticker: string;
  market: string;
  side: Side;
  bucket: Bucket;
  rank: number;
  funding_8h: number;
  funding_apr: number;
  profile: {
    name: string;
    sector: string | null;
    industry: string | null;
    description: string | null;
  } | null;
  spot: {
    as_of: string;
    close: number;
    ret_1d: number | null;
    ret_5d: number | null;
    ret_20d: number | null;
    adv_usd_20d: number | null;
    shares_outstanding: number | null;
    multi_class: boolean;
  } | null;
  catalysts: {
    news: { title: string; url: string; published_at: string; source: string; summary: string }[];
    filings: { form: string; filed: string; items: string[]; labels_zh: string[]; url: string }[];
    earnings: { day: string; timing: "bmo" | "amc" | null } | null;
  };
  short_interest: {
    settlement_date: string;
    shares: number;
    prev_shares: number | null;
    days_to_cover: number | null;
    pct_of_shares: number | null;
    change_pct: number | null;
  } | null;
  short_level: ShortLevel;
  persistence: {
    pattern: FundingPattern;
    buckets: { time: string; rate_8h: number }[];
    same_sign_share: number | null;
    mean_8h: number | null;
    multiple_of_mean: number | null;
  };
  volume: {
    tier: VolumeTier;
    oi_usd: number;
    volume_24h_usd: number;
    oi_to_spot_adv: number | null;
  };
  headline: string;
  answers: Record<AnswerKey, string>;
  errors: string[];
}

export interface InsightsFile {
  schema_version: number;
  generated_at: string;
  /** US-Eastern calendar day that "N 天后/前" is counted from. */
  market_date: string;
  report_generated_at: string;
  thresholds: Record<string, number>;
  errors: string[];
  items: Insight[];
}

// [run index, funding_8h, oi_usd, price, volume_24h_usd]
export type HistoryPoint = [number, number, number, number, number];

export interface HistoryFile {
  schema_version: number;
  runs: string[];
  fields: string[];
  series: Record<string, { market: string; points: HistoryPoint[] }>;
}

export interface MetaFile {
  schema_version: number;
  built_at: string;
  report_generated_at: string | null;
  insights_generated_at: string | null;
  insights_error: string | null;
  history_days: number;
}
