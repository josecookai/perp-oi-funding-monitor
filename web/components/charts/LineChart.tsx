import { utcStamp } from "@/lib/format";

export interface LinePoint {
  time: string;
  value: number;
}

/** Single-series line with recessive grid, end-point label and hover titles per point. */
export function LineChart({
  points,
  format,
  label,
  width = 640,
  height = 160,
}: {
  points: LinePoint[];
  format: (x: number) => string;
  label: string;
  width?: number;
  height?: number;
}) {
  if (points.length < 2) {
    return (
      <div className="grid h-[120px] place-items-center rounded-lg bg-card-soft text-[12px] text-ink-3">
        历史数据积累中（每小时一个点）
      </div>
    );
  }
  const pad = { l: 8, r: 72, t: 12, b: 20 };
  const values = points.map((p) => p.value);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || Math.abs(hi) || 1;
  const x = (i: number) => pad.l + (i / (points.length - 1)) * (width - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - lo) / span) * (height - pad.t - pad.b);
  const d = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const last = points[points.length - 1];

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="block h-auto w-full" role="img" aria-label={label}>
      {[0, 0.5, 1].map((f) => {
        const gy = pad.t + f * (height - pad.t - pad.b);
        return <line key={f} x1={pad.l} x2={width - pad.r} y1={gy} y2={gy} stroke="var(--line)" strokeWidth={1} />;
      })}
      <text x={width - pad.r + 6} y={pad.t + 4} fontSize={10} fill="var(--ink-3)" className="num">
        {format(hi)}
      </text>
      <text x={width - pad.r + 6} y={height - pad.b + 4} fontSize={10} fill="var(--ink-3)" className="num">
        {format(lo)}
      </text>
      <path d={d} fill="none" stroke="var(--brand)" strokeWidth={2} strokeLinejoin="round" />
      <circle cx={x(points.length - 1)} cy={y(last.value)} r={4} fill="var(--brand)" stroke="var(--card)" strokeWidth={2} />
      <text x={width - pad.r + 6} y={y(last.value) + 4} fontSize={11} fontWeight={700} fill="var(--ink)" className="num">
        {format(last.value)}
      </text>
      <text x={pad.l} y={height - 4} fontSize={10} fill="var(--ink-3)">
        {utcStamp(points[0].time)}
      </text>
      {points.map((p, i) => (
        <rect
          key={p.time}
          x={x(i) - (width - pad.l - pad.r) / (points.length - 1) / 2}
          y={0}
          width={(width - pad.l - pad.r) / (points.length - 1)}
          height={height}
          fill="transparent"
        >
          <title>{`${utcStamp(p.time)}  ${format(p.value)}`}</title>
        </rect>
      ))}
    </svg>
  );
}
