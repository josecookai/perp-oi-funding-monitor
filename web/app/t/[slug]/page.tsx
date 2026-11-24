import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { FundingBars } from "@/components/charts/FundingBars";
import { LineChart } from "@/components/charts/LineChart";
import { InsightCard } from "@/components/feed/InsightCard";
import { TickerAvatar, VenueChip } from "@/components/ui/Badges";
import { allMarkets, findRow, history, insightFor, insights, marketKey, marketSlug, parseSlug } from "@/lib/data";
import { pct, price, rate, tone, usdDelta, usdZh } from "@/lib/format";
import type { ReactNode } from "react";

export function generateStaticParams() {
  const slugs = allMarkets().map(({ venue, row }) => ({ slug: marketSlug(venue, row.ticker) }));
  // Cache Components rejects an empty list; a placeholder renders notFound().
  return slugs.length > 0 ? slugs : [{ slug: "binance-__none__" }];
}

export async function generateMetadata({ params }: PageProps<"/t/[slug]">): Promise<Metadata> {
  const parsed = parseSlug((await params).slug);
  return { title: parsed ? `${parsed.ticker} 资金费率与 OI` : "市场" };
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-lg bg-card-soft p-3">
      <div className="text-[11px] text-ink-3">{label}</div>
      <div className="num mt-0.5 text-[16px] font-bold">{children}</div>
    </div>
  );
}

export default async function MarketPage({ params }: PageProps<"/t/[slug]">) {
  const parsed = parseSlug((await params).slug);
  if (!parsed) notFound();
  const { venue, ticker } = parsed;
  const row = findRow(venue, ticker);
  if (!row) notFound();

  const insight = insightFor(venue, ticker);
  const series = history.series[marketKey(venue, ticker)]?.points ?? [];
  const funding = series.map(([run, f]) => ({ time: history.runs[run], rate: f }));
  const oi = series.map(([run, , o]) => ({ time: history.runs[run], value: o }));
  const other = venue === "binance" ? "hyperliquid" : "binance";
  const otherRow = findRow(other, ticker);

  return (
    <div className="px-4 py-5 sm:px-5">
      <Link href="/markets" className="text-[12px] text-ink-3 hover:text-ink">
        ← 全部市场
      </Link>
      <header className="mt-3 flex flex-wrap items-center gap-3">
        <TickerAvatar ticker={ticker} size={44} />
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-[22px] font-extrabold">{ticker}</h1>
            <VenueChip venue={venue} />
            <span className="num text-[12px] text-ink-3">{row.market}</span>
          </div>
          <div className="text-[13px] text-ink-2">{insight?.profile?.name ?? "美股永续合约"}</div>
        </div>
        {otherRow && (
          <Link href={`/t/${marketSlug(other, ticker)}`} className="ml-auto rounded-full border border-line px-3 py-1 text-[12px] text-ink-2 hover:bg-chip">
            {other === "binance" ? "Binance" : "Hyperliquid"} 也有 · {rate(otherRow.funding_8h)}/8h →
          </Link>
        )}
      </header>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="资金费率 / 8h">
          <span className={`tone-${tone(row.funding_8h)}`}>{rate(row.funding_8h)}</span>
        </Stat>
        <Stat label="年化">
          <span className={`tone-${tone(row.funding_apr)}`}>{pct(row.funding_apr, 0)}</span>
        </Stat>
        <Stat label="持仓 OI">{usdZh(row.oi_usd)}</Stat>
        <Stat label="ΔOI（近 8h）">
          <span className={`tone-${tone(row.d_oi_usd)}`}>{usdDelta(row.d_oi_usd)}</span>
        </Stat>
        <Stat label="标记价">{price(row.mark_price)}</Stat>
        <Stat label="24h 成交">{usdZh(row.volume_24h_usd)}</Stat>
        <Stat label="结算周期">{row.funding_interval_hours}h</Stat>
        <Stat label="Δ合约数 %">
          <span className={`tone-${tone(row.d_contracts_pct)}`}>{pct(row.d_contracts_pct)}</span>
        </Stat>
      </div>

      <section className="card mt-5 p-4">
        <h2 className="text-[15px] font-extrabold">资金费率走势（本站每期快照）</h2>
        <div className="mt-3 overflow-x-auto">
          {funding.length > 1 ? (
            <FundingBars bars={funding} width={Math.max(320, funding.length * 10)} height={90} label={`${ticker} 每期资金费率`} />
          ) : (
            <p className="text-[12px] text-ink-3">历史数据积累中（每小时一个点）。下方卡片里的 7 天柱状图来自交易所的历史结算记录。</p>
          )}
        </div>
      </section>

      <section className="card mt-4 p-4">
        <h2 className="text-[15px] font-extrabold">持仓 OI 走势（美元）</h2>
        <div className="mt-3">
          <LineChart points={oi} format={usdZh} label={`${ticker} 持仓 OI 走势`} />
        </div>
      </section>

      {insight ? (
        <section className="card mt-4 overflow-hidden">
          <h2 className="px-5 pt-4 text-[15px] font-extrabold">催化剂卡片</h2>
          <InsightCard item={insight} slug={marketSlug(venue, ticker)} asOf={insights.market_date} />
        </section>
      ) : (
        <p className="mt-4 text-[12px] text-ink-3">
          这只票目前不在资金费率正负 Top 10 里，所以没有生成催化剂卡片。
        </p>
      )}
    </div>
  );
}
