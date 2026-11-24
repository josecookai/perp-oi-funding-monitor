# perp-oi-funding-monitor

A scanner for **US stock perps** on **Binance USDT-M** and **Hyperliquid** (HIP-3 dex `xyz`).
Every 8 hours it records open interest (OI) and funding for each market, compares them with
the previous run, and reports:

1. OI change for every ticker (USD, %, contract %)
2. OI gain, top 10
3. OI loss, top 10
4. Most negative funding, top 10
5. Most positive funding, top 10

The report also has a cross-venue table for tickers listed on both venues.

A **dashboard** (`web/`, Next.js on Vercel) shows the same data plus a catalyst card for
every ticker in each venue's funding top 10. See [Dashboard](#dashboard).

It only collects public data: no API keys, no orders.

## Quick start

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e ".[dev]"
cp .env.example .env          # optional: Telegram, paths, window settings
./run.sh --no-store           # dry run: print a live report, write and store nothing
./run.sh --manual             # full ad-hoc cycle: report files + SQLite + Telegram
```

Each run writes `reports/YYYY-MM-DD/HHMMZ.md` (human report), `HHMMZ.json` (same data for
a dashboard), and refreshes `reports/latest.md` / `latest.json`.

## Schedule

Runs from **this server's crontab** at 00:00, 08:00 and 16:00 UTC (`scheduler/crontab.example`):

```
0 0,8,16 * * * /home/ubuntu/perp-oi-funding-monitor/scheduler/run_and_push.sh
```

`scheduler/run_and_push.sh` appends its own log to `logs/cron.log`. It takes a lock, so
overlapping runs (including a manual `./run.sh`) are skipped. It runs one cycle, then
`perp-monitor site` to refresh `web/data/`, and commits and pushes `reports/` and
`web/data/`. Each push to `main` redeploys the dashboard. If a push fails, the commits stay local and
the next run pushes them.

**Why not a GitHub Actions cron?** Binance answers US IP addresses with HTTP 451, and
GitHub's hosted runners are mostly in the US. GitHub Actions only runs lint and tests
(`.github/workflows/test.yml`).

Exit codes:

| Code | Meaning |
|---|---|
| `0` | ok |
| `1` | a venue or Telegram failed; the rest of the report still goes out |
| `2` | aborted (bad config, the crypto check fired, or a crash); nothing is stored and a Telegram alert is sent |
| `3` | another run holds the lock |
| `4` | git commit or push failed; retried next run |

If every venue fails, nothing is stored, `latest.*` is left as it was, and Telegram gets an
alert instead of a report.

## Keeping crypto out

The hard rule is that no crypto perp may appear in any report. Several stock tickers are
also crypto perps: on Binance, `BB`, `CVX`, `QNT` and `STX` are crypto, and `CAT` is close
to `1000CAT`. On Hyperliquid xyz, `CL` is crude oil and `GOLD` is gold. Matching on names
would mix these up, so there are four layers:

| Layer | Where | Rule |
|---|---|---|
| Venue market type | `binance_client.select_equity_symbols`, `hyperliquid_client` | Binance: `underlyingType=EQUITY`, `contractType=TRADIFI_PERPETUAL`, USDT, `TRADING`. Hyperliquid: only the HIP-3 dexes named in `HL_DEXES`. The main (crypto) dex is never read. |
| Venue overrides | `assets/symbol_overrides.toml` | Aliases (`BRKB` → `BRK.B`) and per-venue exclusions (`CL`, `GOLD`, `SILVER` on Hyperliquid) |
| Allowlist | `assets/stocks_allowlist.txt` | The canonical ticker must be listed |
| Final check | `guard.py` | Every row must come from `binance:EQUITY` or `hl:<dex>`, and no table row may contain a symbol from `assets/crypto_denylist.txt`. Otherwise the run aborts before anything is stored or sent. |

## Allowlist maintenance

`assets/stocks_allowlist.txt` holds one ticker per line: US-listed single stocks and ADRs.
It excludes ETFs, leveraged ETFs, preferreds, and non-US stocks. The file header records
its source and every deliberate exclusion.

```bash
.venv/bin/perp-monitor allowlist suggest           # venue stock perps not on the list yet
.venv/bin/perp-monitor allowlist validate --sec    # format, duplicates, denylist, SEC listing check
.venv/bin/perp-monitor allowlist add PLTR CRWD
.venv/bin/perp-monitor allowlist remove XYZ
```

`suggest` lists everything a venue calls a stock that the allowlist doesn't have yet.
Review each name before adding it: many are ETFs (QQQ, SOXL…) or non-US. `--sec` checks
each ticker against SEC's `company_tickers_exchange.json`. That file covers operating
companies and ADRs but not most ETFs, so a miss is a warning to review, not an error.
Set `SEC_USER_AGENT` to your own contact string.

## How the numbers are computed

| Metric | Definition |
|---|---|
| OI (USD) | contracts × mark price (Binance `premiumIndex.markPrice`, Hyperliquid `markPx`) |
| ΔOI | current OI USD − previous OI USD. Rankings use this. |
| Δ contracts % | change in contracts, which removes the effect of the price move |
| Funding 8h | converted to 8h. Hyperliquid: the market's current hourly `funding` × 8. Binance: `premiumIndex.lastFundingRate`, using each symbol's interval from `/fapi/v1/fundingInfo` (8h unless listed). Rankings use this. |
| APR | funding × periods per year, simple (not compounded) |
| Window | actual time since the previous observation, flagged if outside `EXPECTED_WINDOW_HOURS ± WINDOW_TOLERANCE_HOURS` |
| Previous observation | the latest stored run at least `EXPECTED − TOLERANCE` hours old (7h by default), so a manual run just before a scheduled one does not shrink its window. If no run is that old, the latest earlier run is used. |

Edge cases:
- **First run.** Binance's previous OI is backfilled from `/futures/data/openInterestHist`, so 8h changes show at once. Hyperliquid has no OI history endpoint, so its OI rankings start at the second run.
- **Listing changes.** Markets seen for the first time are marked `new` and left out of OI rankings. Delisted markets disappear.
- **Zero funding.** Funding of exactly 0 (common on Binance stock perps) is left out of the funding rankings, so a list can have fewer than 10 rows, and the report says so.

## Layout

```
src/perp_monitor/
  models.py              frozen+slots dataclasses (MarketSnapshot, PriorPoint, MarketChange, Window)
  config.py              env vars -> Config
  http.py                JSON over HTTP with bounded retries
  allowlist.py           allowlist load/validate/edit/suggest
  overrides.py           venue aliases and exclusions
  binance_client.py      Binance stock perps + OI history
  hyperliquid_client.py  Hyperliquid HIP-3 dex markets
  funding.py             8h / APR normalization
  store.py               SQLite snapshots
  delta.py, ranking.py   changes vs previous run, top-N
  report.py              report model
  render_md.py / render_tg.py / render_json.py
  guard.py               stock-only checks
  notify.py              Telegram sender (token redacted from errors)
  sec.py                 SEC listing lookup for allowlist validation
  pipeline.py            one full cycle
  site_export.py         web/data/*.json for the dashboard
  cli.py                 `perp-monitor run|site|allowlist ...`
  insights/              catalyst cards: sources (nasdaq, news, sec_filings, finra,
                         funding_history), rules (analysis), text (narrative),
                         orchestration (collect, live_source), cache, serialize
web/                     Next.js dashboard (reads web/data/*.json)
```

## Tests

```bash
.venv/bin/python -m pytest --cov                   # deterministic tests (recorded real API responses)
RUN_LIVE=1 .venv/bin/python -m pytest tests/live   # real Binance + Hyperliquid calls (non-US host)
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

`tests/fixtures/` holds real API responses recorded on 2026-11-24, trimmed to a few
markets. They include the crypto name collisions.

## Telegram

Set `TELEGRAM_CHAT_ID`, plus either `TELEGRAM_BOT_TOKEN` or `TELEGRAM_TOKEN_FILE` (a dotenv
file containing `TELEGRAM_BOT_TOKEN=`), in `.env`. Each run sends one message per venue
and a cross-venue message, then the full report as a `.md` document. The token is never
logged: httpx request logging is turned down and errors redact it.

## Adding a Hyperliquid dex

`HL_DEXES` accepts any HIP-3 dex that exists. The allowlist still applies, so a
non-stock dex can only leak a market whose name equals an allowlisted ticker. Check a
new dex's market list before adding it. As of 2026-11, `io` and `para` also list some
stocks, but `para` is mostly crypto indices and rates.

## Dashboard

`web/` is a Next.js 16 app (App Router, Tailwind 4). It reads `web/data/*.json` at build
time, so every page is static. The Vercel project's Root Directory is `web`.

```bash
.venv/bin/perp-monitor site                  # write web/data: report, history, insights, meta
.venv/bin/perp-monitor site --skip-insights  # same, but keep the previous insights.json
cd web && npm install && npm run dev         # local preview on :3000
```

| File | Content |
|---|---|
| `report.json` | copy of `reports/latest.json` |
| `history.json` | last 30 days of runs from SQLite: per market `[run, funding_8h, oi_usd, price, volume]` |
| `insights.json` | one card per ticker in each venue's funding top 10 (below) |
| `meta.json` | build time, and `insights_error` if the cards could not be refreshed |

### Catalyst cards

Each card answers five questions in Chinese: what the company is, whether the funding
skew is persistent, recent catalysts, whether the perp volume means anything, and whether
the stock is a crowded short. Sources, all public and keyless:

| Data | Source | Cache |
|---|---|---|
| Company profile, market cap | Nasdaq `api.nasdaq.com` (`/company/{s}/company-profile`, `/quote/{s}/summary`) | 7 days / 20 h |
| Daily bars (returns, 20-session dollar volume) | Nasdaq `/quote/{s}/historical` | none |
| Earnings dates (−7 to +14 days) | Nasdaq `/calendar/earnings?date=` | none |
| News (last 7 days) | Yahoo Finance RSS, kept only if the headline or summary names the ticker or company | none |
| Filings (last 14 days): 8-K items, 424B offerings, 10-Q/K, 6-K | SEC `data.sec.gov/submissions` | CIK map 7 days |
| Short interest | FINRA consolidated short interest (twice monthly) | none |
| 7-day funding history | Binance `/fapi/v1/fundingRate`, Hyperliquid `fundingHistory` | none |

The cache lives in `data/cache/insights.json` (git-ignored). A failed source is recorded
on the card (`errors`) and the card is still built. If the whole step fails, the previous
`insights.json` is kept and the site shows a notice.

Rules (constants in `src/perp_monitor/insights/analysis.py`, shown on the site's
方法说明 page):

| Question | Rule |
|---|---|
| Volume meaningful? | noise: OI < $250K or 24h volume < $100K; meaningful: OI ≥ $1M and volume ≥ $1M; otherwise thin |
| Funding persistent? | share of 8h buckets in the last 7 days with the current sign: ≥ 60% persistent, ≤ 25% spike, else mixed; < 3 buckets: insufficient |
| Crowded short? | short shares ÷ shares outstanding (market cap ÷ close): ≥ 15% high, ≥ 8% elevated, ≥ 4% moderate; a lower share with ≥ 7 days to cover also counts as moderate |
