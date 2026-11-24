import Link from "next/link";
import type { ReactNode } from "react";

import { FundingBars } from "@/components/charts/FundingBars";
import { PatternBadge, ShortBadge, TickerAvatar, VenueChip, VolumeBadge } from "@/components/ui/Badges";
import { daysBetween, monthDay, pct, plainPct, rate, safeHref, tone, usdZh } from "@/lib/format";
import type { AnswerKey, Insight } from "@/lib/types";

import { RichText } from "./RichText";

const QUESTIONS: { key: AnswerKey; q: string }[] = [
  { key: "what", q: "这是什么公司？" },
  { key: "funding", q: "资金费率怎么看？" },
  { key: "catalyst", q: "最近有什么催化剂？" },
  { key: "volume", q: "交易量有意义吗？" },
  { key: "short", q: "是热门做空股吗？" },
];

function Metric({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] text-ink-3">{label}</div>
      <div className="num truncate text-[15px] font-bold">{children}</div>
    </div>
  );
}

function Signed({ value, fmt }: { value: number | null | undefined; fmt: (x: number | null | undefined) => string }) {
  return <span className={`tone-${tone(value)}`}>{fmt(value)}</span>;
}

function CatalystLinks({ item, asOf }: { item: Insight; asOf: string }) {
  const { earnings, filings, news } = item.catalysts;
  if (!earnings && filings.length === 0 && news.length === 0) return null;
  return (
    <ul className="mt-2 space-y-1.5 text-[12.5px]">
      {earnings && (
        <li className="flex gap-2">
          <span className="num shrink-0 text-ink-3">{monthDay(earnings.day)}</span>
          <span className="font-semibold text-warn">
            财报
            {earnings.timing === "bmo" ? "（盘前）" : earnings.timing === "amc" ? "（盘后）" : ""}
            {(() => {
              const d = daysBetween(asOf, earnings.day);
              return d === 0 ? " · 今天" : d > 0 ? ` · ${d} 天后` : ` · ${-d} 天前`;
            })()}
          </span>
        </li>
      )}
      {filings.slice(0, 3).map((f, i) => (
        <li key={`f${i}`} className="flex gap-2">
          <span className="num shrink-0 text-ink-3">{monthDay(f.filed)}</span>
          <a href={safeHref(f.url)} target="_blank" rel="noopener noreferrer" className="min-w-0 hover:underline">
            <span className="font-semibold text-brand">SEC {f.form}</span>{" "}
            <span className="text-ink-2">{f.labels_zh.join("、")}</span>
          </a>
        </li>
      ))}
      {news.slice(0, 3).map((n, i) => (
        <li key={`n${i}`} className="flex gap-2">
          <span className="num shrink-0 text-ink-3">{monthDay(n.published_at)}</span>
          <a href={safeHref(n.url)} target="_blank" rel="noopener noreferrer" className="min-w-0 hover:underline">
            <span className="text-ink">{n.title}</span>{" "}
            <span className="text-[11px] text-ink-3">{n.source}</span>
          </a>
        </li>
      ))}
    </ul>
  );
}

export function InsightCard({ item, slug, asOf }: { item: Insight; slug: string; asOf: string }) {
  const bars = item.persistence.buckets.map((b) => ({ time: b.time, rate: b.rate_8h }));
  const sideLabel = item.side === "negative" ? "负费率" : "正费率";
  return (
    <article data-venue={item.venue} className="border-b border-line px-4 py-4 sm:px-5">
      <header className="flex items-start gap-3">
        <TickerAvatar ticker={item.ticker} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <Link href={`/t/${slug}`} className="text-[16px] font-extrabold hover:underline">
              {item.ticker}
            </Link>
            <VenueChip venue={item.venue} />
            <span className="truncate text-[13px] text-ink-2">{item.profile?.name ?? ""}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-ink-3">
              {sideLabel} #{item.rank}
            </span>
            <PatternBadge pattern={item.persistence.pattern} />
            <VolumeBadge tier={item.volume.tier} />
            <ShortBadge level={item.short_level} />
          </div>
        </div>
        <div className="text-right">
          <div className={`num text-[18px] font-extrabold tone-${tone(item.funding_8h)}`}>
            {rate(item.funding_8h)}
          </div>
          <div className="num text-[11px] text-ink-3">年化 {pct(item.funding_apr, 0)}</div>
        </div>
      </header>

      <p className="mt-3 text-[15px] font-bold leading-6">
        <RichText text={item.headline} ticker={item.ticker} />
      </p>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <div className="grid w-full grid-cols-3 gap-3 sm:w-auto sm:flex-1 sm:grid-cols-5">
          <Metric label="持仓 OI">{usdZh(item.volume.oi_usd)}</Metric>
          <Metric label="24h 成交">{usdZh(item.volume.volume_24h_usd)}</Metric>
          <Metric label="OI / 现货日成交">{plainPct(item.volume.oi_to_spot_adv, 2)}</Metric>
          <Metric label="现货 1 日">
            <Signed value={item.spot?.ret_1d} fmt={pct} />
          </Metric>
          <Metric label="空头 / 总股本">{plainPct(item.short_interest?.pct_of_shares)}</Metric>
        </div>
        <div>
          <div className="mb-1 text-[11px] text-ink-3">近 7 天资金费率（每 8h）</div>
          <FundingBars bars={bars} label={`${item.ticker} 近 7 天每 8 小时资金费率`} />
        </div>
      </div>

      <div className="mt-3 rounded-xl border border-line bg-card-soft px-4 py-3">
        <dl className="space-y-2.5">
          {QUESTIONS.map(({ key, q }) => (
            <div key={key} className="grid gap-0.5 sm:grid-cols-[120px_1fr] sm:gap-3">
              <dt className="text-[12.5px] font-semibold text-ink-3">{q}</dt>
              <dd className="text-[13.5px] leading-[1.6] text-ink">
                <RichText text={item.answers[key]} ticker={item.ticker} />
                {key === "catalyst" && <CatalystLinks item={item} asOf={asOf} />}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      <footer className="mt-2 flex items-center justify-between text-[12px] text-ink-3">
        <span>
          {item.spot ? `现货数据截至 ${monthDay(item.spot.as_of)}` : "暂无现货数据"}
          {item.errors.length > 0 && ` · ${item.errors.length} 个数据源未响应`}
        </span>
        <Link href={`/t/${slug}`} className="font-semibold text-brand hover:underline">
          历史走势 →
        </Link>
      </footer>
    </article>
  );
}
