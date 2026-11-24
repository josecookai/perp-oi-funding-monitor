import type { Metadata } from "next";

import { FeedPage } from "@/components/feed/FeedPage";

export const metadata: Metadata = { title: "正资金费率" };

export default function PositivePage() {
  return <FeedPage side="positive" />;
}
