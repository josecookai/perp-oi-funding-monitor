"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { ThemeToggle } from "./ThemeToggle";

const NAV = [
  { href: "/", label: "负费率", icon: "▼" },
  { href: "/positive", label: "正费率", icon: "▲" },
  { href: "/markets", label: "全部市场", icon: "▦" },
  { href: "/oi", label: "OI 变动", icon: "◆" },
  { href: "/cross", label: "跨所价差", icon: "⇄" },
  { href: "/about", label: "方法说明", icon: "ⓘ" },
];

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

function Brand() {
  return (
    <Link href="/" className="block px-3 leading-tight">
      <span className="bg-gradient-to-r from-[#4d7cff] to-[#5ba0ff] bg-clip-text text-[22px] font-extrabold tracking-tight text-transparent">
        PerpRadar
      </span>
      <span className="block text-[11px] font-medium text-ink-3">美股永续 · 资金费率雷达</span>
    </Link>
  );
}

export function RailNav() {
  const pathname = usePathname();
  return (
    <aside className="sticky top-0 hidden h-screen w-[232px] shrink-0 flex-col justify-between px-4 py-6 lg:flex">
      <div className="space-y-6">
        <Brand />
        <nav className="space-y-1" aria-label="主导航">
          {NAV.map((item) => {
            const active = isActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-3 rounded-full px-4 py-2.5 text-[15px] transition-colors ${
                  active
                    ? "bg-brand-soft font-bold text-ink"
                    : "text-ink-2 hover:bg-chip hover:text-ink"
                }`}
              >
                <span className="w-4 text-center text-[13px] opacity-80" aria-hidden>
                  {item.icon}
                </span>
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="flex items-center gap-2 px-3">
        <ThemeToggle />
        <span className="text-[11px] text-ink-3">每 8 小时更新</span>
      </div>
    </aside>
  );
}

export function MobileNav() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-card/95 backdrop-blur lg:hidden">
      <div className="flex items-center justify-between px-3 py-2">
        <Brand />
        <ThemeToggle />
      </div>
      <nav className="flex gap-1 overflow-x-auto px-2 pb-2" aria-label="主导航">
        {NAV.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`shrink-0 rounded-full px-3 py-1 text-[13px] ${
                active ? "bg-brand-soft font-bold text-ink" : "text-ink-2"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
