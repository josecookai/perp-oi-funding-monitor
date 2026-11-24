import { rate, utcStamp } from "@/lib/format";

export interface FundingBar {
  time: string;
  rate: number;
}

/**
 * Funding per 8h period as bars above/below a zero line. Position carries the sign,
 * colour repeats it, and every bar has a hover title with the exact value.
 */
export function FundingBars({
  bars,
  width = 220,
  height = 56,
  label,
}: {
  bars: FundingBar[];
  width?: number;
  height?: number;
  label: string;
}) {
  if (bars.length === 0) {
    return <div className="text-[11px] text-ink-3">暂无历史</div>;
  }
  const maxAbs = Math.max(...bars.map((b) => Math.abs(b.rate)), 1e-9);
  const gap = 2;
  const barW = Math.max(2, (width - gap * (bars.length - 1)) / bars.length);
  const mid = height / 2;
  const scale = (mid - 2) / maxAbs;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={label}
      className="block overflow-visible"
    >
      <line x1={0} x2={width} y1={mid} y2={mid} stroke="var(--line-strong)" strokeWidth={1} />
      {bars.map((b, i) => {
        const h = Math.max(1, Math.abs(b.rate) * scale);
        const x = i * (barW + gap);
        const y = b.rate >= 0 ? mid - h : mid;
        const fill = b.rate > 0 ? "var(--up)" : b.rate < 0 ? "var(--down)" : "var(--ink-3)";
        return (
          <g key={b.time}>
            <rect x={x} y={y} width={barW} height={h} rx={Math.min(2, barW / 2)} fill={fill} />
            {/* larger invisible hit target for the hover title */}
            <rect x={x - gap / 2} y={0} width={barW + gap} height={height} fill="transparent">
              <title>{`${utcStamp(b.time)}  ${rate(b.rate)}/8h`}</title>
            </rect>
          </g>
        );
      })}
    </svg>
  );
}
