# PerpRadar dashboard

Next.js 16 (App Router, Cache Components) + Tailwind 4. Every page is prerendered from
`data/*.json`, which `perp-monitor site` writes after each hourly scan (see the repo
README). `data/` is git-ignored; production is deployed from the server with
`../scheduler/deploy_site.sh`, and git-triggered Vercel builds are off (`vercel.json`).

```bash
npm install
npm run dev     # http://localhost:3000
npm run build   # needs data/*.json (run `perp-monitor site` first)
```

Layout: `app/` routes (负费率 `/`, 正费率 `/positive`, `/markets`, `/oi`, `/cross`,
`/t/[venue-ticker]`, `/about`), `components/` (feed cards, charts, rail, ui), `lib/`
(data access, formatting, treemap layout, JSON types).
