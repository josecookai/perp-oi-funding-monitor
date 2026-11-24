import type { Metadata } from "next";
import Link from "next/link";

import { TickerAvatar } from "@/components/ui/Badges";
import { MobileTitle, PageHeader } from "@/components/ui/PageHeader";
import { marketSlug, report } from "@/lib/data";
import { rate, tone, usdZh } from "@/lib/format";

export const metadata: Metadata = { title: "跨所价差" };

export default function CrossPage() {
  const rows = report.cross_venue.toSorted(
    (a, b) => Math.abs(b.funding_spread_8h) - Math.abs(a.funding_spread_8h),
  );
  return (
    <div>
      <PageHeader title="跨所资金费率价差" />
      <MobileTitle title="跨所资金费率价差" />
      <p className="px-4 pt-3 text-[13px] text-ink-2 sm:px-5">
        两个交易所都上了的股票。价差 = Hyperliquid − Binance（都换算成每 8 小时）。价差为正：HL 多头付得更多，可以考虑 HL 做空、Binance 做多来收费率差；同时要看两边 OI 能不能撑住仓位。
      </p>
      <div className="overflow-x-auto px-4 py-4 sm:px-5">
        <table className="card w-full min-w-[640px] overflow-hidden text-[13.5px]">
          <thead>
            <tr className="border-b border-line text-[12px] text-ink-3">
              <th className="px-3 py-2 text-left font-normal">资产</th>
              <th className="px-3 py-2 text-right font-normal">Binance / 8h</th>
              <th className="px-3 py-2 text-right font-normal">HL / 8h</th>
              <th className="px-3 py-2 text-right font-normal">价差 HL−BN</th>
              <th className="px-3 py-2 text-right font-normal">Binance OI</th>
              <th className="px-3 py-2 text-right font-normal">HL OI</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.ticker} className="border-b border-line last:border-0 hover:bg-card-soft">
                <td className="px-3 py-2">
                  <span className="flex items-center gap-2 font-bold">
                    <TickerAvatar ticker={r.ticker} size={22} />
                    {r.ticker}
                    <Link href={`/t/${marketSlug("binance", r.ticker)}`} className="text-[11px] font-normal text-brand hover:underline">BN</Link>
                    <Link href={`/t/${marketSlug("hyperliquid", r.ticker)}`} className="text-[11px] font-normal text-brand hover:underline">HL</Link>
                  </span>
                </td>
                <td className={`num px-3 py-2 text-right tone-${tone(r.binance_funding_8h)}`}>{rate(r.binance_funding_8h)}</td>
                <td className={`num px-3 py-2 text-right tone-${tone(r.hyperliquid_funding_8h)}`}>{rate(r.hyperliquid_funding_8h)}</td>
                <td className={`num px-3 py-2 text-right font-bold tone-${tone(r.funding_spread_8h)}`}>{rate(r.funding_spread_8h)}</td>
                <td className="num px-3 py-2 text-right">{usdZh(r.binance_oi_usd)}</td>
                <td className="num px-3 py-2 text-right">{usdZh(r.hyperliquid_oi_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
