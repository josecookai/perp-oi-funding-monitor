# PerpRadar dashboard

Next.js 16 (App Router, Cache Components) + Tailwind 4. Every page is prerendered from
`data/*.json`, which `perp-monitor site` writes after each scan (see the repo README).

```bash
npm install
npm run dev     # http://localhost:3000
npm run build   # what Vercel runs; Root Directory = web
```

Layout: `app/` routes (负费率 `/`, 正费率 `/positive`, `/markets`, `/oi`, `/cross`,
`/t/[venue-ticker]`, `/about`), `components/` (feed cards, charts, rail, ui), `lib/`
(data access, formatting, treemap layout, JSON types).
