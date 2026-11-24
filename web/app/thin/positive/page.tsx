import type { Metadata } from "next";

import { FeedPage } from "@/components/feed/FeedPage";

export const metadata: Metadata = { title: "量没意义 · 正资金费率" };

export default function ThinPositivePage() {
  return <FeedPage side="positive" bucket="illiquid" />;
}
