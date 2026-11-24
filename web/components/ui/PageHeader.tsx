import Link from "next/link";
import type { ReactNode } from "react";

export interface Tab {
  href: string;
  label: string;
  active: boolean;
}

export function PageHeader({ title, tabs = [], aside }: { title: string; tabs?: Tab[]; aside?: ReactNode }) {
  return (
    <div className="sticky top-0 z-10 hidden items-center gap-5 border-b border-line bg-bg/90 px-5 py-3 backdrop-blur lg:flex">
      <h1 className="text-[20px] font-extrabold">{title}</h1>
      {tabs.length > 0 && (
        <nav className="flex gap-4" aria-label={`${title}分类`}>
          {tabs.map((t) => (
            <Link
              key={t.href}
              href={t.href}
              aria-current={t.active ? "page" : undefined}
              className={`border-b-2 pb-1 text-[14px] ${
                t.active ? "border-brand font-bold text-ink" : "border-transparent text-ink-2 hover:text-ink"
              }`}
            >
              {t.label}
            </Link>
          ))}
        </nav>
      )}
      {aside && <div className="ml-auto text-[12px] text-ink-3">{aside}</div>}
    </div>
  );
}

export function MobileTitle({ title }: { title: string }) {
  return <h1 className="px-4 pt-4 text-[18px] font-extrabold lg:hidden">{title}</h1>;
}
