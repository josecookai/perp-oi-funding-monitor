import type { Metadata } from "next";

import { RowsTable } from "@/components/markets/RowsTable";
import { MobileTitle, PageHeader } from "@/components/ui/PageHeader";
import { VENUES, rowsByTickers, section } from "@/lib/data";
import { usdDelta } from "@/lib/format";

export const metadata: Metadata = { title: "OI 变动" };

export default function OiPage() {
  return (
    <div>
      <PageHeader title="OI 变动" />
      <MobileTitle title="OI 变动" />
      <p className="px-4 pt-3 text-[13px] text-ink-2 sm:px-5">
        与上一期（约 8 小时前）相比的持仓变化，按美元 ΔOI 排名。Δ合约数 % 剔除了价格涨跌的影响：合约数增加才说明真有新仓位进场。
      </p>
      <div className="space-y-6 px-4 py-4 sm:px-5">
        {VENUES.map((venue) => {
          const s = section(venue);
          if (!s) return null;
          const empty = s.error ? `本期失败：${s.error}` : "首期运行，下一期开始有变化数据。";
          return (
            <section key={venue} className="card overflow-hidden">
              <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-4 py-3">
                <h2 className="text-[16px] font-extrabold">{s.label}</h2>
                <span className="num text-[12px] text-ink-3">
                  窗口 {s.window.hours?.toFixed(1) ?? "—"}h · 匹配市场净 ΔOI {usdDelta(s.matched_d_oi_usd)}
                </span>
              </header>
              <h3 className="px-4 pt-3 text-[13px] font-bold text-up">增仓 Top {s.rankings.oi_gain.length}</h3>
              <RowsTable venue={venue} rows={rowsByTickers(venue, s.rankings.oi_gain)} empty={empty} />
              <h3 className="px-4 pt-4 text-[13px] font-bold text-down">减仓 Top {s.rankings.oi_loss.length}</h3>
              <RowsTable venue={venue} rows={rowsByTickers(venue, s.rankings.oi_loss)} empty={empty} />
            </section>
          );
        })}
      </div>
    </div>
  );
}
