import { RightRail } from "@/components/rail/RightRail";
import { MobileTitle, PageHeader } from "@/components/ui/PageHeader";
import { insights, insightsBySide, marketSlug, meta, report } from "@/lib/data";
import { utcStamp } from "@/lib/format";
import type { Side } from "@/lib/types";

import { InsightCard } from "./InsightCard";
import { VenueFilter } from "./VenueFilter";

const INTRO: Record<Side, string> = {
  negative: "资金费率为负 = 空头每 8 小时付钱给多头，说明做空的一方更拥挤。",
  positive: "资金费率为正 = 多头每 8 小时付钱给空头，说明做多的一方更拥挤。",
};

export function FeedPage({ side }: { side: Side }) {
  const items = insightsBySide(side);
  const title = side === "negative" ? "负资金费率 Top 10" : "正资金费率 Top 10";
  const asOf = insights.market_date;
  const stale = insights.report_generated_at !== report.generated_at;
  const counts = {
    all: items.length,
    binance: items.filter((i) => i.venue === "binance").length,
    hyperliquid: items.filter((i) => i.venue === "hyperliquid").length,
  };
  return (
    <div className="xl:flex xl:gap-4">
      <div className="min-w-0 flex-1 xl:border-r xl:border-line">
        <PageHeader
          title="资金费率异动"
          tabs={[
            { href: "/", label: "负费率", active: side === "negative" },
            { href: "/positive", label: "正费率", active: side === "positive" },
          ]}
          aside={<span className="num">更新于 {utcStamp(insights.generated_at)}</span>}
        />
        <MobileTitle title={title} />
        <p className="px-4 pt-3 text-[13px] text-ink-2 sm:px-5">
          {INTRO[side]}每张卡片回答 5 个问题：这是什么公司、费率是否持续、最近有什么催化剂、交易量够不够大、是不是热门做空股。
        </p>
        {(stale || meta.insights_error) && (
          <p className="mx-4 mt-3 rounded-lg bg-warn-soft px-3 py-2 text-[12px] text-warn sm:mx-5">
            最新一次催化剂卡片没有更新成功，下方是 {utcStamp(insights.report_generated_at)} 的卡片；费率和 OI 以“全部市场”页为准。
          </p>
        )}
        <VenueFilter counts={counts}>
          {items.length === 0 ? (
            <p className="px-5 py-10 text-center text-[14px] text-ink-3">目前没有{side === "negative" ? "负" : "正"}费率市场。</p>
          ) : (
            items.map((item) => (
              <InsightCard key={item.key} item={item} slug={marketSlug(item.venue, item.ticker)} asOf={asOf} />
            ))
          )}
        </VenueFilter>
      </div>
      <RightRail />
    </div>
  );
}
