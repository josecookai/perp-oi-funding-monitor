import Link from "next/link";

import { rate, usdZh } from "@/lib/format";
import { squarify } from "@/lib/treemap";
import type { Venue } from "@/lib/types";

export interface TreemapMarket {
  venue: Venue;
  ticker: string;
  slug: string;
  oiUsd: number;
  funding8h: number;
}

// Funding at or beyond this magnitude gets the full diverging colour.
const FULL_SCALE = 0.001; // 0.1% per 8h

function fill(f: number): string {
  const share = Math.round(Math.min(1, Math.abs(f) / FULL_SCALE) * 85 + (f === 0 ? 0 : 15));
  const pole = f > 0 ? "var(--up)" : "var(--down)";
  return f === 0 ? "var(--mid)" : `color-mix(in oklab, ${pole} ${share}%, var(--mid))`;
}

/** Tile area = open interest; colour = 8h funding (red negative, teal positive). */
export function FundingTreemap({
  markets,
  width = 340,
  height = 260,
}: {
  markets: TreemapMarket[];
  width?: number;
  height?: number;
}) {
  const tiles = squarify(
    markets.map((m) => ({ value: m.oiUsd, data: m })),
    width,
    height,
  );
  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="block h-auto w-full"
        role="img"
        aria-label="资金费率热力图：面积为 OI，颜色为 8 小时资金费率"
      >
        {tiles.map((t) => {
          const m = t.data;
          const big = t.w > 46 && t.h > 30;
          const strong = Math.abs(m.funding8h) >= FULL_SCALE * 0.6;
          const ink = strong ? "#ffffff" : "var(--ink)";
          return (
            <Link key={`${m.venue}:${m.ticker}`} href={`/t/${m.slug}`}>
              <rect
                x={t.x + 1}
                y={t.y + 1}
                width={Math.max(0, t.w - 2)}
                height={Math.max(0, t.h - 2)}
                rx={4}
                fill={fill(m.funding8h)}
              >
                <title>{`${m.ticker} (${m.venue === "binance" ? "Binance" : "HL"})  资金费率 ${rate(m.funding8h)}/8h  OI ${usdZh(m.oiUsd)}`}</title>
              </rect>
              {big && (
                <text x={t.x + 6} y={t.y + 16} fontSize={11} fontWeight={700} fill={ink} pointerEvents="none">
                  {m.ticker}
                  {t.w > m.ticker.length * 7.5 + 26 && (
                    <tspan fontSize={8} fontWeight={500} opacity={0.75} dx={3}>
                      {m.venue === "binance" ? "BN" : "HL"}
                    </tspan>
                  )}
                </text>
              )}
              {big && t.h > 42 && (
                <text x={t.x + 6} y={t.y + 30} fontSize={10} fill={ink} opacity={0.85} pointerEvents="none" className="num">
                  {rate(m.funding8h, 3)}
                </text>
              )}
            </Link>
          );
        })}
      </svg>
      <div className="mt-2 flex items-center justify-between text-[11px] text-ink-3">
        <span className="flex items-center gap-1">
          <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: "var(--down)" }} />
          负费率（空头付钱）
        </span>
        <span className="flex items-center gap-1">
          <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: "var(--mid)" }} />0
        </span>
        <span className="flex items-center gap-1">
          正费率（多头付钱）
          <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: "var(--up)" }} />
        </span>
      </div>
    </div>
  );
}
