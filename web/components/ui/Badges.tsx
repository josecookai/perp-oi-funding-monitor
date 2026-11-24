import type { FundingPattern, ShortLevel, Venue, VolumeTier } from "@/lib/types";

const PILL = "inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-semibold leading-4";

export function VenueChip({ venue }: { venue: Venue }) {
  const label = venue === "binance" ? "Binance" : "HL xyz";
  return <span className={`${PILL} bg-chip font-medium text-ink-3`}>{label}</span>;
}

const VOLUME: Record<VolumeTier, { label: string; cls: string }> = {
  meaningful: { label: "量有意义", cls: "bg-up-soft text-up" },
  thin: { label: "量偏薄", cls: "bg-warn-soft text-warn" },
  noise: { label: "量太小", cls: "bg-chip text-ink-3" },
};

export function VolumeBadge({ tier }: { tier: VolumeTier }) {
  const v = VOLUME[tier];
  return <span className={`${PILL} ${v.cls}`}>{v.label}</span>;
}

const SHORT: Partial<Record<ShortLevel, { label: string; cls: string }>> = {
  high: { label: "热门做空", cls: "bg-down-soft text-down" },
  elevated: { label: "空头偏多", cls: "bg-warn-soft text-warn" },
  moderate: { label: "空头中等", cls: "bg-chip text-ink-2" },
  low: { label: "空头很少", cls: "bg-chip text-ink-3" },
};

export function ShortBadge({ level }: { level: ShortLevel }) {
  const s = SHORT[level];
  return s ? <span className={`${PILL} ${s.cls}`}>{s.label}</span> : null;
}

const PATTERN: Partial<Record<FundingPattern, { label: string; cls: string }>> = {
  persistent: { label: "持续", cls: "bg-brand-soft text-brand" },
  spike: { label: "单期异动", cls: "bg-warn-soft text-warn" },
  mixed: { label: "多空来回", cls: "bg-chip text-ink-2" },
};

export function PatternBadge({ pattern }: { pattern: FundingPattern }) {
  const p = PATTERN[pattern];
  return p ? <span className={`${PILL} ${p.cls}`}>{p.label}</span> : null;
}

/** Round monogram standing in for a logo (no third-party logo hotlinking). */
export function TickerAvatar({ ticker, size = 36 }: { ticker: string; size?: number }) {
  let hash = 0;
  for (const ch of ticker) hash = (hash * 31 + ch.charCodeAt(0)) % 360;
  return (
    <span
      aria-hidden
      className="grid shrink-0 place-items-center rounded-full font-bold text-white"
      style={{
        width: size,
        height: size,
        fontSize: size * (ticker.length >= 4 ? 0.25 : 0.32),
        letterSpacing: "-0.02em",
        background: `oklch(0.62 0.13 ${hash})`,
      }}
    >
      {ticker.slice(0, 4)}
    </span>
  );
}
