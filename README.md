# Dip Scanner

Scans every stock in the S&P 500 and TSX 60 after each weekday close and
flags the ones that look like dips. Results publish to a dashboard on
GitHub Pages.

**Signals, not recommendations.** A rule firing means a price moved, not that
the stock is a good buy. Check why it fell before acting.

## The four rules

| Rule | Fires when |
|---|---|
| 52w | Price is 20%+ below its 52-week high |
| 5d | Price fell 10%+ over the last 5 trading days |
| RSI | 14-day RSI is under 30 |
| 200d | Price is below its 200-day moving average |

Each stock gets a score of 0–4. The dashboard opens on stocks hitting 3+.

Flagged stocks get one of three labels:

- **Pullback** — still above its 200-day average, but oversold or down hard
  this week. A dip inside an uptrend.
- **Downtrend** — below its 200-day *and* 20%+ off its high. Cheaper, but this
  is where falling knives live.
- **Mixed** — anything else that hit two or more rules. Often a sharp drop
  that just broke below the 200-day.

To change the thresholds, edit `RULES` at the top of `scan.py`.

## Setup (one time)

1. **Create the repo.** On GitHub, create a new **public** repository named
   `dip-scanner`. Free GitHub Pages needs a public repo. Nothing personal goes
   in here — only code and public market data.
2. **Push these files** to the `main` branch.
3. **Turn on the dashboard.** Repo → Settings → Pages → Source: *Deploy from a
   branch* → Branch: `main`, folder: `/docs` → Save.
4. **Run the first scan.** Repo → Actions → *Daily dip scan* → *Run workflow*.
   Takes 3–5 minutes.
5. **Open the dashboard** at `https://<your-username>.github.io/dip-scanner/`.
   Add it to your iPhone home screen from Safari's share menu.

After that it runs on its own every weekday at 22:30 UTC (5:30pm Toronto in
winter, 6:30pm in summer).

## If something breaks

- **Dashboard shows a "data is N days old" banner.** The scan failed. Open the
  Actions tab, click the red run, and read the log. Most often Yahoo changed
  something and `yfinance` needs a newer version.
- **Dashboard says only a few Canadian stocks were scanned.** Wikipedia's TSX 60
  page changed layout. The S&P 500 side still works.
- If the Wikipedia fetch fails entirely, the scanner falls back to
  `universe_cache.csv` from the last good run.

## Files

- `scan.py` — fetches the stock lists and prices, computes the rules, writes results
- `docs/index.html` — the dashboard
- `docs/data.json` — today's results (written by the scan)
- `docs/history/` — one file per day of flagged stocks, used for the NEW badge
- `.github/workflows/scan.yml` — the daily schedule
- `tests/test_signals.py` — checks the signal math on synthetic stocks

Prices come from Yahoo Finance through the unofficial `yfinance` library:
adjusted daily closes, free, and occasionally flaky.
