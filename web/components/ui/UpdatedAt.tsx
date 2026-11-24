import { hktStamp, utcStamp } from "@/lib/format";

/** Two-line update time: UTC, then Hong Kong time. */
export function UpdatedAt({ iso, className = "" }: { iso: string; className?: string }) {
  return (
    <span className={`num block leading-5 ${className}`}>
      <span className="block">更新于 {utcStamp(iso)}</span>
      <span className="block">香港时间 {hktStamp(iso)}</span>
    </span>
  );
}
