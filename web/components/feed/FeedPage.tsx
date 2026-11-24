import Link from "next/link";

import { RightRail } from "@/components/rail/RightRail";
import { MobileTitle, PageHeader } from "@/components/ui/PageHeader";
import { feedPath, insights, insightsFor, marketSlug, meta, report } from "@/lib/data";
import { usdZh, utcStamp } from "@/lib/format";
import type { Bucket, Side } from "@/lib/types";

import { InsightCard } from "./InsightCard";
import { VenueFilter } from "./VenueFilter";

const SIDE_TEXT: Record<Side, string> = {
  negative: "资金费率为负 = 空头每 8 小时付钱给多头，做空的一方更拥挤。",
  positive: "资金费率为正 = 多头每 8 小时付钱给空头，做多的一方更拥挤。",
};

export const BUCKET_TITLE: Record<Bucket, string> = {
  liquid: "量有意义",
  illiquid: "量没意义",
};

function bucketText(bucket: Bucket): string {
  const t = insights.thresholds;
  const oi = usdZh(t.meaningful_oi_usd);
  const vol = usdZh(t.meaningful_volume_usd);
  return bucket === "liquid"
    ? `这里只看 OI ≥ ${oi} 且 24h 成交 ≥ ${vol} 的市场，费率能反映真实的多空需求。`
    : `这里是 OI < ${oi} 或 24h 成交 < ${vol} 的市场（量偏薄 / 量太小），几笔单就能把费率推到极端，参考意义有限。`;
}

export function FeedPage({ side, bucket }: { side: Side; bucket: Bucket }) {
  const items = insightsFor(side, bucket);
  const sideTitle = side === "negative" ? "负费率" : "正费率";
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
          title={BUCKET_TITLE[bucket]}
          tabs={[
            { href: feedPath("negative", bucket), label: "负费率 Top 10", active: side === "negative" },
            { href: feedPath("positive", bucket), label: "正费率 Top 10", active: side === "positive" },
          ]}
          aside={<span className="num">更新于 {utcStamp(insights.generated_at)}</span>}
        />
        <MobileTitle title={`${BUCKET_TITLE[bucket]} · ${sideTitle} Top 10`} />
        <p className="px-4 pt-3 text-[13px] text-ink-2 sm:px-5">
          {bucketText(bucket)}
          {SIDE_TEXT[side]}每张卡片回答 5 个问题：这是什么公司、费率是否持续、最近有什么催化剂、交易量够不够大、是不是热门做空股。
        </p>
        <nav className="flex gap-2 px-4 pt-2 lg:hidden" aria-label="正负费率">
          {(["negative", "positive"] as const).map((s) => (
            <Link
              key={s}
              href={feedPath(s, bucket)}
              aria-current={s === side ? "page" : undefined}
              className={`rounded-full px-3 py-1 text-[13px] ${s === side ? "bg-brand-soft font-bold" : "text-ink-2"}`}
            >
              {s === "negative" ? "负费率" : "正费率"}
            </Link>
          ))}
        </nav>
        {(stale || meta.insights_error) && (
          <p className="mx-4 mt-3 rounded-lg bg-warn-soft px-3 py-2 text-[12px] text-warn sm:mx-5">
            最新一次催化剂卡片没有更新成功，下方是 {utcStamp(insights.report_generated_at)} 的卡片；费率和 OI 以“全部市场”页为准。
          </p>
        )}
        <VenueFilter counts={counts}>
          {items.length === 0 ? (
            <p className="px-5 py-10 text-center text-[14px] text-ink-3">
              目前没有{BUCKET_TITLE[bucket]}的{sideTitle}市场。
            </p>
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
