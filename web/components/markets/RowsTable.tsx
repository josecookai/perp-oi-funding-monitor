import Link from "next/link";

import { TickerAvatar } from "@/components/ui/Badges";
import { marketSlug } from "@/lib/data";
import { pct, rate, tone, usdDelta, usdZh } from "@/lib/format";
import type { ReportRow, Venue } from "@/lib/types";

/** Compact server-rendered ranking table (OI gainers/losers). */
export function RowsTable({ venue, rows, empty }: { venue: Venue; rows: ReportRow[]; empty: string }) {
  if (rows.length === 0) return <p className="px-4 py-6 text-[13px] text-ink-3">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-[13.5px]">
        <thead>
          <tr className="border-b border-line text-[12px] text-ink-3">
            <th className="w-8 px-3 py-2 text-left font-normal">#</th>
            <th className="px-3 py-2 text-left font-normal">资产</th>
            <th className="px-3 py-2 text-right font-normal">ΔOI</th>
            <th className="px-3 py-2 text-right font-normal">ΔOI %</th>
            <th className="px-3 py-2 text-right font-normal">Δ合约数 %</th>
            <th className="px-3 py-2 text-right font-normal">OI</th>
            <th className="px-3 py-2 text-right font-normal">资金费率 / 8h</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.ticker} className="border-b border-line hover:bg-card-soft">
              <td className="num px-3 py-2 text-ink-3">{i + 1}</td>
              <td className="px-3 py-2">
                <Link href={`/t/${marketSlug(venue, r.ticker)}`} className="flex items-center gap-2 font-bold hover:underline">
                  <TickerAvatar ticker={r.ticker} size={22} />
                  {r.ticker}
                </Link>
              </td>
              <td className={`num px-3 py-2 text-right font-semibold tone-${tone(r.d_oi_usd)}`}>{usdDelta(r.d_oi_usd)}</td>
              <td className={`num px-3 py-2 text-right tone-${tone(r.d_oi_pct)}`}>{pct(r.d_oi_pct)}</td>
              <td className={`num px-3 py-2 text-right tone-${tone(r.d_contracts_pct)}`}>{pct(r.d_contracts_pct)}</td>
              <td className="num px-3 py-2 text-right">{usdZh(r.oi_usd)}</td>
              <td className={`num px-3 py-2 text-right tone-${tone(r.funding_8h)}`}>{rate(r.funding_8h)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
