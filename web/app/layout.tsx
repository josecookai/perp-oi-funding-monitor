import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { MobileNav, RailNav } from "@/components/shell/Nav";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const jetbrains = JetBrains_Mono({ variable: "--font-jetbrains", subsets: ["latin"] });

export const metadata: Metadata = {
  title: {
    default: "Stock Perp Radar · 美股永续资金费率雷达",
    template: "%s · Stock Perp Radar",
  },
  description:
    "Binance 与 Hyperliquid 美股永续合约：资金费率、OI 变化、催化剂与交易量是否有意义，每小时更新。",
};

// Runs before paint so the saved theme never flashes.
const THEME_SCRIPT = `try{var t=localStorage.getItem("theme");if(t==="dark"||t==="light")document.documentElement.dataset.theme=t;}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="zh-CN"
      data-theme="light"
      suppressHydrationWarning
      className={`${inter.variable} ${jetbrains.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-screen">
        <MobileNav />
        <div className="mx-auto flex max-w-[1500px]">
          <RailNav />
          <main className="min-w-0 flex-1 border-line lg:border-l">{children}</main>
        </div>
      </body>
    </html>
  );
}
