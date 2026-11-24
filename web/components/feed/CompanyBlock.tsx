import { plainPct, usdZh } from "@/lib/format";
import type { Insight } from "@/lib/types";

import { RichText } from "./RichText";

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-baseline gap-1 rounded-md bg-chip px-2 py-0.5 text-[12px]">
      <span className="text-ink-3">{label}</span>
      <span className="num font-semibold text-ink">{value}</span>
    </span>
  );
}

/** "这是什么公司？": Chinese line, English line, then market cap / revenue / margin. */
export function CompanyBlock({ item }: { item: Insight }) {
  const p = item.profile;
  const f = item.fundamentals;
  if (!p) return <span className="text-ink-3">{item.answers.what}</span>;
  const kind = p.industry ?? p.sector;
  return (
    <div className="space-y-1.5">
      {p.name_zh && p.description_zh ? (
        <p>
          <b>{p.name_zh}</b>
          <span className="text-ink-2">（{p.name}）</span>：{p.description_zh}
        </p>
      ) : (
        <p>
          <b>{p.name}</b>
          {kind && <span className="text-ink-3"> · {kind}</span>}
        </p>
      )}
      {item.summary_en && (
        <p className="text-[12.5px] leading-5 text-ink-3">
          <RichText text={item.summary_en} ticker={item.ticker} />
        </p>
      )}
      <div className="flex flex-wrap gap-1.5 pt-0.5">
        {f?.market_cap_usd ? <Chip label="市值" value={usdZh(f.market_cap_usd)} /> : null}
        {f?.revenue_ttm_usd ? (
          <Chip label={f.quarters >= 4 ? "近四季营收" : `近 ${f.quarters} 季营收`} value={usdZh(f.revenue_ttm_usd)} />
        ) : null}
        {f?.gross_margin !== null && f?.gross_margin !== undefined ? (
          <Chip label="毛利率" value={plainPct(f.gross_margin)} />
        ) : null}
        {f?.period_end ? (
          <span className="self-center text-[11px] text-ink-3">财报截至 {f.period_end.slice(0, 7).replace("-", "/")}</span>
        ) : null}
        {!f?.revenue_ttm_usd && <span className="text-[12px] text-ink-3">暂无财务数据（外国发行人、基金或新上市公司常见）</span>}
      </div>
    </div>
  );
}
