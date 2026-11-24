import type { Metadata } from "next";

import { MarketsTable, type MarketRow } from "@/components/markets/MarketsTable";
import { MobileTitle, PageHeader } from "@/components/ui/PageHeader";
import { allMarkets, insightFor, marketSlug, report } from "@/lib/data";
import { utcStamp } from "@/lib/format";

export const metadata: Metadata = { title: "全部市场" };

export default function MarketsPage() {
  const rows: MarketRow[] = allMarkets().map(({ venue, row }) => ({
    venue,
    ticker: row.ticker,
    slug: marketSlug(venue, row.ticker),
    price: row.mark_price,
    funding8h: row.funding_8h,
    apr: row.funding_apr,
    oiUsd: row.oi_usd,
    dOiUsd: row.d_oi_usd,
    dOiPct: row.d_oi_pct,
    volume: row.volume_24h_usd,
    isNew: row.is_new,
    inInsights: insightFor(venue, row.ticker) !== undefined,
  }));
  return (
    <div>
      <PageHeader title="全部市场" aside={<span className="num">{utcStamp(report.generated_at)}</span>} />
      <MobileTitle title="全部市场" />
      <p className="px-4 pt-3 text-[13px] text-ink-2 sm:px-5">
        只收美股个股和 ADR 的永续合约（不含 ETF、加密）。点表头排序；★ 表示进了资金费率 Top 10，有催化剂卡片。
      </p>
      <MarketsTable rows={rows} />
    </div>
  );
}
