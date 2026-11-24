import type { Metadata } from "next";
import type { ReactNode } from "react";

import { MobileTitle, PageHeader } from "@/components/ui/PageHeader";
import { insights, meta, report } from "@/lib/data";
import { usdZh, utcStamp } from "@/lib/format";

export const metadata: Metadata = { title: "方法说明" };

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="card p-5">
      <h2 className="text-[16px] font-extrabold">{title}</h2>
      <div className="mt-2 space-y-2 text-[14px] leading-7 text-ink-2">{children}</div>
    </section>
  );
}

export default function AboutPage() {
  const t = insights.thresholds;
  return (
    <div>
      <PageHeader title="方法说明" />
      <MobileTitle title="方法说明" />
      <div className="max-w-3xl space-y-4 px-4 py-4 sm:px-5">
        <Block title="数据从哪来">
          <p>
            每 8 小时（UTC 00:00 / 08:00 / 16:00）抓一次 Binance USDT 本位美股永续（EQUITY 类型）和 Hyperliquid HIP-3
            的 xyz 市场。只收美股个股和 ADR（白名单 {report.allowlist_size} 只），不含 ETF、杠杆 ETF、加密货币。
          </p>
          <p>
            催化剂卡片：公司资料、现货价格和成交量、财报日历来自 Nasdaq；新闻来自 Yahoo Finance；公告来自 SEC EDGAR；空头持仓来自 FINRA（每月两次）；7 天资金费率历史来自两家交易所的结算记录。
          </p>
          <p className="num text-[12px] text-ink-3">
            本期报告 {utcStamp(report.generated_at)} · 卡片 {utcStamp(insights.generated_at)} · 网站构建 {utcStamp(meta.built_at)}
          </p>
        </Block>
        <Block title="资金费率">
          <p>
            所有费率都换算成每 8 小时（Hyperliquid 每小时结算，乘以 8）。年化 = 8h 费率 × 1095，不复利。负费率：空头付给多头；正费率：多头付给空头。
          </p>
          <p>
            <b className="text-ink">是否持续</b>：把过去 7 天的结算记录按 8 小时分桶，看和当前同方向的时段占多少。≥ {Math.round(t.persistent_share * 100)}% 记为“持续”，≤ {Math.round(t.spike_share * 100)}% 记为“单期异动”，中间是“多空来回”，少于 3 个时段记为数据不足。
          </p>
        </Block>
        <Block title="交易量是否有意义">
          <p>
            <b className="text-ink">量太小</b>：OI &lt; {usdZh(t.noise_oi_usd)} 或 24h 成交 &lt; {usdZh(t.noise_volume_usd)}，几笔单就能推动费率。
            <br />
            <b className="text-ink">量有意义</b>：OI ≥ {usdZh(t.meaningful_oi_usd)} 且 24h 成交 ≥ {usdZh(t.meaningful_volume_usd)}。
            <br />
            <b className="text-ink">量偏薄</b>：介于两者之间。
          </p>
          <p>卡片还会给出 “OI / 现货日均成交额”（20 个交易日均值），看永续仓位相对现货市场有多大。</p>
        </Block>
        <Block title="是否热门做空">
          <p>
            空头股数 ÷ 总股本（总股本 = Nasdaq 市值 ÷ 收盘价，多类股公司按全部类别算）：≥ {Math.round(t.short_high * 100)}% 热门做空，≥ {Math.round(t.short_elevated * 100)}% 空头偏多，≥ {Math.round(t.short_moderate * 100)}% 空头中等。占比低但回补天数 ≥ {t.long_days_to_cover} 天的（流通盘小）也算中等。
          </p>
        </Block>
        <Block title="注意">
          <p>
            这是公开数据的整理，不构成投资建议。新闻按“标题或摘要提到 ticker 或公司名”过滤，偶尔会混进榜单类文章；催化剂只列事实，不判断因果。
          </p>
        </Block>
      </div>
    </div>
  );
}
