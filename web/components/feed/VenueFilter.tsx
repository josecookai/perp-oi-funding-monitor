"use client";

import { useState, type ReactNode } from "react";

type Filter = "all" | "binance" | "hyperliquid";

const OPTIONS: { value: Filter; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "binance", label: "Binance" },
  { value: "hyperliquid", label: "Hyperliquid" },
];

/**
 * Venue tabs for server-rendered cards: children carry data-venue, and CSS hides the
 * other venue, so switching never re-renders or re-downloads the cards.
 */
export function VenueFilter({ children, counts }: { children: ReactNode; counts: Record<Filter, number> }) {
  const [filter, setFilter] = useState<Filter>("all");
  return (
    <div data-venue-filter={filter}>
      <div role="tablist" aria-label="交易所" className="flex gap-1 border-b border-line px-4 py-2 sm:px-5">
        {OPTIONS.map((o) => (
          <button
            key={o.value}
            type="button"
            role="tab"
            aria-selected={filter === o.value}
            onClick={() => setFilter(o.value)}
            className={`rounded-full px-3 py-1 text-[13px] transition-colors ${
              filter === o.value ? "bg-ink text-card font-semibold" : "text-ink-2 hover:bg-chip"
            }`}
          >
            {o.label}
            <span className="num ml-1 text-[11px] opacity-70">{counts[o.value]}</span>
          </button>
        ))}
      </div>
      {children}
    </div>
  );
}
