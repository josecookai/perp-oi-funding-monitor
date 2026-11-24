"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { TickerAvatar, VenueChip } from "@/components/ui/Badges";
import { pct, price, rate, tone, usdDelta, usdZh } from "@/lib/format";
import type { Venue } from "@/lib/types";

export interface MarketRow {
  venue: Venue;
  ticker: string;
  slug: string;
  price: number;
  funding8h: number;
  apr: number;
  oiUsd: number;
  dOiUsd: number | null;
  dOiPct: number | null;
  volume: number | null;
  isNew: boolean;
  inInsights: boolean;
}

type SortKey = "ticker" | "price" | "funding8h" | "oiUsd" | "dOiUsd" | "dOiPct" | "volume" | "turnover";
type VenueFilter = "all" | Venue;

const COLUMNS: { key: SortKey; label: string; align: "left" | "right" }[] = [
  { key: "ticker", label: "资产", align: "left" },
  { key: "price", label: "标记价", align: "right" },
  { key: "funding8h", label: "资金费率 / 8h", align: "right" },
  { key: "oiUsd", label: "持仓 OI", align: "right" },
  { key: "dOiUsd", label: "ΔOI（近 8h）", align: "right" },
  { key: "dOiPct", label: "ΔOI %", align: "right" },
  { key: "volume", label: "24h 成交", align: "right" },
  { key: "turnover", label: "成交 / OI", align: "right" },
];

function sortValue(r: MarketRow, key: SortKey): number | string {
  switch (key) {
    case "ticker":
      return r.ticker;
    case "turnover":
      return r.volume && r.oiUsd ? r.volume / r.oiUsd : -Infinity;
    default:
      return r[key] ?? -Infinity;
  }
}

export function MarketsTable({ rows }: { rows: MarketRow[] }) {
  const [venue, setVenue] = useState<VenueFilter>("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "oiUsd", desc: true });

  const shown = useMemo(() => {
    const q = query.trim().toUpperCase();
    const filtered = rows.filter((r) => (venue === "all" || r.venue === venue) && (!q || r.ticker.includes(q)));
    return filtered.toSorted((a, b) => {
      const av = sortValue(a, sort.key);
      const bv = sortValue(b, sort.key);
      const cmp = typeof av === "string" ? av.localeCompare(String(bv)) : av - (bv as number);
      return sort.desc ? -cmp : cmp;
    });
  }, [rows, venue, query, sort]);

  function toggleSort(key: SortKey) {
    setSort((s) => (s.key === key ? { key, desc: !s.desc } : { key, desc: key !== "ticker" }));
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2 sm:px-5">
        {(["all", "binance", "hyperliquid"] as const).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setVenue(v)}
            aria-pressed={venue === v}
            className={`rounded-full px-3 py-1 text-[13px] ${
              venue === v ? "bg-ink font-semibold text-card" : "text-ink-2 hover:bg-chip"
            }`}
          >
            {v === "all" ? "全部" : v === "binance" ? "Binance" : "Hyperliquid"}
          </button>
        ))}
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索 ticker"
          aria-label="搜索 ticker"
          className="ml-auto w-40 rounded-full border border-line bg-card px-3 py-1 text-[13px] outline-none focus:border-brand"
        />
        <span className="num text-[12px] text-ink-3">{shown.length} 个市场</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] text-[13.5px]">
          <thead>
            <tr className="border-b border-line text-[12px] text-ink-3">
              <th className="w-10 px-3 py-2 text-left font-normal">#</th>
              {COLUMNS.map((c) => (
                <th key={c.key} className={`px-3 py-2 font-normal text-${c.align}`} aria-sort={sort.key === c.key ? (sort.desc ? "descending" : "ascending") : "none"}>
                  <button type="button" onClick={() => toggleSort(c.key)} className="hover:text-ink">
                    {c.label}
                    <span className="ml-0.5 text-[10px]">{sort.key === c.key ? (sort.desc ? "▼" : "▲") : "⇅"}</span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={`${r.venue}:${r.ticker}`} className="border-b border-line hover:bg-card-soft">
                <td className="num px-3 py-2.5 text-ink-3">{i + 1}</td>
                <td className="px-3 py-2">
                  <Link href={`/t/${r.slug}`} className="flex items-center gap-2 hover:underline">
                    <TickerAvatar ticker={r.ticker} size={24} />
                    <span className="font-bold">{r.ticker}</span>
                    <VenueChip venue={r.venue} />
                    {r.isNew && <span className="text-[11px] font-semibold text-brand">新</span>}
                    {r.inInsights && <span className="text-[11px] text-warn" title="资金费率 Top 10，有催化剂卡片">★</span>}
                  </Link>
                </td>
                <td className="num px-3 py-2 text-right">{price(r.price)}</td>
                <td className={`num px-3 py-2 text-right font-semibold tone-${tone(r.funding8h)}`}>
                  {rate(r.funding8h)}
                  <span className="block text-[11px] font-normal text-ink-3">年化 {pct(r.apr, 0)}</span>
                </td>
                <td className="num px-3 py-2 text-right">{usdZh(r.oiUsd)}</td>
                <td className={`num px-3 py-2 text-right tone-${tone(r.dOiUsd)}`}>{usdDelta(r.dOiUsd)}</td>
                <td className={`num px-3 py-2 text-right tone-${tone(r.dOiPct)}`}>{pct(r.dOiPct)}</td>
                <td className="num px-3 py-2 text-right">{usdZh(r.volume)}</td>
                <td className="num px-3 py-2 text-right text-ink-2">
                  {r.volume && r.oiUsd ? `${(r.volume / r.oiUsd).toFixed(1)}x` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
