import type { ReactNode } from "react";

// Signed percentages ("-0.342%", "+12.2%") and the ticker get tradingbeats-style emphasis.
const TOKEN = /([+-]\d[\d,]*(?:\.\d+)?%)/g;

export function RichText({ text, ticker }: { text: string; ticker: string }) {
  const parts: ReactNode[] = [];
  text.split(TOKEN).forEach((chunk, i) => {
    if (i % 2 === 1) {
      const cls = chunk.startsWith("-") ? "tone-down" : "tone-up";
      parts.push(
        <span key={i} className={`num ${cls}`}>
          {chunk}
        </span>,
      );
      return;
    }
    chunk.split(new RegExp(`(\\b${ticker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b)`)).forEach((piece, j) => {
      parts.push(
        piece === ticker ? (
          <span key={`${i}-${j}`} className="text-brand">
            {piece}
          </span>
        ) : (
          piece
        ),
      );
    });
  });
  return <>{parts}</>;
}
