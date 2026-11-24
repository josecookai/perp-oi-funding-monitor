import Link from "next/link";

import { FundingTreemap, type TreemapMarket } from "@/components/charts/FundingTreemap";
import { TickerAvatar, VenueChip } from "@/components/ui/Badges";
import { VENUES, marketSlug, report, section } from "@/lib/data";
import { pct, tone, usdDelta, usdZh, utcStamp } from "@/lib/format";
import type { ReportRow, Venue } from "@/lib/types";

const HEATMAP_PER_VENUE = 24;

function Snapshot() {
  return (
    <section className="card p-4">
      <h2 className="text-[15px] font-extrabold">最新快照</h2>
      <div className="num mt-1 text-[12px] text-ink-3">
        {utcStamp(report.generated_at)}
        {report.manual ? " · 手动" : ""}
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-3">
        {VENUES.map((v) => {
          const s = section(v);
          return (
            <div key={v} className="rounded-lg bg-card-soft p-2.5">
              <dt className="text-[12px] text-ink-3">{v === "binance" ? "Binance" : "Hyperliquid xyz"}</dt>
              <dd className="num mt-0.5 text-[16px] font-bold">{s ? usdZh(s.total_oi_usd) : "—"}</dd>
              <dd className="text-[11px] text-ink-3">
                {s?.error ? "本次抓取失败" : `${s?.rows.length ?? 0} 个市场 · ΔOI 窗口 ${s?.window.hours?.toFixed(1) ?? "—"}h`}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}

function movers(kind: "oi_gain" | "oi_loss"): { venue: Venue; row: ReportRow }[] {
  return VENUES.flatMap((venue) => {
    const s = section(venue);
    if (!s) return [];
    return s.rankings[kind]
      .map((t) => s.rows.find((r) => r.ticker === t))
      .filter((r): r is ReportRow => !!r)
      .map((row) => ({ venue, row }));
  })
    .toSorted((a, b) =>
      kind === "oi_gain" ? (b.row.d_oi_usd ?? 0) - (a.row.d_oi_usd ?? 0) : (a.row.d_oi_usd ?? 0) - (b.row.d_oi_usd ?? 0),
    )
    .slice(0, 8);
}

function Movers({ kind }: { kind: "oi_gain" | "oi_loss" }) {
  const list = movers(kind);
  return (
    <section className="card p-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-[15px] font-extrabold">{kind === "oi_gain" ? "OI 增幅榜" : "OI 降幅榜"}</h2>
        <Link href="/oi" className="text-[12px] text-ink-3 hover:text-ink">
          近 8h ΔOI · 全部 →
        </Link>
      </div>
      {list.length === 0 ? (
        <p className="mt-3 text-[13px] text-ink-3">数据积累中，8 小时后开始有变化数据。</p>
      ) : (
        <ol className="mt-2">
          {list.map(({ venue, row }, i) => (
            <li key={`${venue}:${row.ticker}`}>
              <Link
                href={`/t/${marketSlug(venue, row.ticker)}`}
                className="-mx-2 flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-chip"
              >
                <span className="num w-4 text-right text-[11px] text-ink-3">{i + 1}</span>
                <TickerAvatar ticker={row.ticker} size={26} />
                <span className="text-[14px] font-semibold">{row.ticker}</span>
                <VenueChip venue={venue} />
                <span className="ml-auto text-right">
                  <span className={`num block text-[13px] font-bold tone-${tone(row.d_oi_usd)}`}>
                    {usdDelta(row.d_oi_usd)}
                  </span>
                  <span className="num block text-[11px] text-ink-3">{pct(row.d_oi_pct)}</span>
                </span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function Heatmap() {
  const markets: TreemapMarket[] = VENUES.flatMap((venue) =>
    (section(venue)?.rows ?? [])
      .toSorted((a, b) => b.oi_usd - a.oi_usd)
      .slice(0, HEATMAP_PER_VENUE)
      .map((r) => ({
        venue,
        ticker: r.ticker,
        slug: marketSlug(venue, r.ticker),
        oiUsd: r.oi_usd,
        funding8h: r.funding_8h,
      })),
  );
  return (
    <section className="card p-4">
      <h2 className="text-[15px] font-extrabold">资金费率热力图</h2>
      <p className="mb-2 text-[11px] text-ink-3">面积 = OI（两所各取前 {HEATMAP_PER_VENUE}），颜色 = 8h 资金费率</p>
      <FundingTreemap markets={markets} />
    </section>
  );
}

export function RightRail() {
  return (
    <aside className="space-y-4 px-4 py-4 xl:sticky xl:top-0 xl:max-h-screen xl:w-[360px] xl:shrink-0 xl:overflow-y-auto xl:px-0 xl:pr-4">
      <Snapshot />
      <Heatmap />
      <Movers kind="oi_gain" />
      <Movers kind="oi_loss" />
    </aside>
  );
}
