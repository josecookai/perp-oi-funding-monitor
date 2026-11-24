import type { Metadata } from "next";

import { FeedPage } from "@/components/feed/FeedPage";

export const metadata: Metadata = { title: "量没意义 · 负资金费率" };

export default function ThinNegativePage() {
  return <FeedPage side="negative" bucket="illiquid" />;
}
