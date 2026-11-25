#!/usr/bin/env python3
"""Daily dip scanner for the S&P 500 and TSX 60.

Scores every stock 0-4 against four dip rules and writes docs/data.json,
which the dashboard (docs/index.html) reads. Runs once per weekday after
the close via GitHub Actions.

These are signals that a price moved, not recommendations to buy.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
HISTORY = DOCS / "history"
UNIVERSE_CACHE = ROOT / "universe_cache.csv"

# ---------------------------------------------------------------- rules --
# Edit these to change what counts as a dip.
RULES = {
    "dd52": -0.20,   # price at least 20% below its 52-week high
    "ret5": -0.10,   # down at least 10% over the last 5 trading days
    "rsi": 30.0,     # 14-day RSI under 30 ("oversold")
    # "below200": price under its 200-day moving average (no threshold)
}
MIN_SCORE_FOR_HISTORY = 2   # names saved to history and used for the NEW badge

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
TSX60_URL = "https://en.wikipedia.org/wiki/S%26P/TSX_60"
HTTP_HEADERS = {"User-Agent": "dip-scanner/1.0 (personal stock screener)"}


# ------------------------------------------------------------- universe --
def _pick(df: pd.DataFrame, *candidates: str) -> str | None:
    """Return the first column whose name contains any candidate string."""
    for cand in candidates:
        for col in df.columns:
            if cand.lower() in str(col).lower():
                return col
    return None


def _read_tables(url: str) -> list[pd.DataFrame]:
    import requests

    resp = requests.get(url, headers=HTTP_HEADERS, timeout=30)
    resp.raise_for_status()
    return pd.read_html(StringIO(resp.text))


def fetch_universe() -> pd.DataFrame:
    """S&P 500 + TSX 60 from Wikipedia, as yfinance tickers."""
    rows = []

    sp = _read_tables(SP500_URL)[0]
    sym, name, sector = _pick(sp, "Symbol"), _pick(sp, "Security"), _pick(sp, "GICS Sector")
    for _, r in sp.iterrows():
        t = str(r[sym]).strip().replace(".", "-")
        rows.append({"ticker": t, "name": r[name], "sector": r[sector], "market": "US"})

    for tbl in _read_tables(TSX60_URL):
        sym = _pick(tbl, "Symbol", "Ticker")
        name = _pick(tbl, "Company", "Name")
        if sym is None or name is None or len(tbl) < 40:
            continue
        sector = _pick(tbl, "Sector")
        for _, r in tbl.iterrows():
            raw = str(r[sym]).split(":")[-1].strip()
            if not raw or raw.lower() == "nan":
                continue
            t = raw.replace(".", "-") + ".TO"
            rows.append({
                "ticker": t,
                "name": r[name],
                "sector": r[sector] if sector else "",
                "market": "CA",
            })
        break

    df = pd.DataFrame(rows).drop_duplicates("ticker")
    n_us, n_ca = int((df.market == "US").sum()), int((df.market == "CA").sum())
    if n_us < 400:
        raise RuntimeError(f"S&P 500 list looks incomplete ({n_us} names)")
    if n_ca < 50:
        print(f"WARNING: TSX 60 list looks incomplete ({n_ca} names); "
              "Wikipedia's table layout may have changed", file=sys.stderr)
    return df


def load_universe() -> pd.DataFrame:
    """Fetch the universe, falling back to the cached copy if Wikipedia fails."""
    try:
        df = fetch_universe()
        df.to_csv(UNIVERSE_CACHE, index=False)
        print(f"universe: {len(df)} names (fresh)")
        return df
    except Exception as exc:  # network, layout change, etc.
        if UNIVERSE_CACHE.exists():
            df = pd.read_csv(UNIVERSE_CACHE).fillna("")
            print(f"universe: {len(df)} names (cached; fetch failed: {exc})")
            return df
        raise


# --------------------------------------------------------------- prices --
def fetch_prices(tickers: list[str], chunk: int = 100) -> dict[str, pd.Series]:
    """Daily adjusted closes for ~14 months, keyed by ticker."""
    import yfinance as yf

    out: dict[str, pd.Series] = {}
    for i in range(0, len(tickers), chunk):
        batch = tickers[i : i + chunk]
        df = yf.download(
            batch, period="14mo", interval="1d", auto_adjust=True,
            group_by="ticker", threads=True, progress=False,
        )
        if df is None or df.empty:
            continue
        for t in batch:
            try:
                if isinstance(df.columns, pd.MultiIndex):
                    if t not in df.columns.get_level_values(0):
                        continue
                    s = df[t]["Close"]
                else:
                    s = df["Close"]
            except KeyError:
                continue
            s = s.dropna()
            if len(s):
                out[t] = s
    return out


# -------------------------------------------------------------- signals --
def rsi_wilder(close: pd.Series, n: int = 14) -> pd.Series:
    """Relative Strength Index with Wilder's smoothing."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.where(avg_loss != 0, 100.0)                       # no losses
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)  # flat
    return rsi


def compute(close: pd.Series) -> dict | None:
    """All four signals for one price series, or None if too little data."""
    close = close.dropna()
    if len(close) < 30:
        return None

    price = float(close.iloc[-1])
    high52 = float(close.iloc[-252:].max())
    dd52 = price / high52 - 1
    ret5 = price / float(close.iloc[-6]) - 1 if len(close) >= 6 else None
    rsi = float(rsi_wilder(close).iloc[-1])
    sma200 = float(close.iloc[-200:].mean()) if len(close) >= 200 else None
    vs200 = price / sma200 - 1 if sma200 else None

    hits = {
        "dd52": dd52 <= RULES["dd52"],
        "ret5": ret5 is not None and ret5 <= RULES["ret5"],
        "rsi": not np.isnan(rsi) and rsi < RULES["rsi"],
        "below200": sma200 is not None and price < sma200,
    }
    score = sum(hits.values())

    if score == 0:
        label = ""
    elif hits["below200"] and hits["dd52"]:
        label = "Downtrend"
    elif sma200 is not None and not hits["below200"] and (hits["rsi"] or hits["ret5"]):
        label = "Pullback"
    else:
        label = "Mixed"

    return {
        "asof": close.index[-1].strftime("%Y-%m-%d"),
        "price": round(price, 2),
        "high52": round(high52, 2),
        "dd52": round(dd52, 4),
        "ret5": None if ret5 is None else round(ret5, 4),
        "rsi": None if np.isnan(rsi) else round(rsi, 1),
        "vs200": None if vs200 is None else round(vs200, 4),
        "hits": [k for k, v in hits.items() if v],
        "score": score,
        "label": label,
    }


# ---------------------------------------------------------------- output --
def previous_flagged(asof: str) -> set[str]:
    """Tickers flagged on the most recent earlier scan, for the NEW badge."""
    if not HISTORY.exists():
        return set()
    earlier = sorted(p for p in HISTORY.glob("*.json") if p.stem < asof)
    if not earlier:
        return set()
    data = json.loads(earlier[-1].read_text())
    return {r["ticker"] for r in data.get("rows", [])}


def run(universe: pd.DataFrame, prices: dict[str, pd.Series]) -> dict:
    rows = []
    for _, u in universe.iterrows():
        series = prices.get(u["ticker"])
        if series is None:
            continue
        sig = compute(series)
        if sig is None:
            continue
        rows.append({
            "ticker": u["ticker"],
            "name": str(u["name"]),
            "sector": str(u["sector"]),
            "market": u["market"],
            **sig,
        })

    if not rows:
        raise RuntimeError("no price data came back; nothing to write")

    asof = max(r["asof"] for r in rows)
    before = previous_flagged(asof)
    for r in rows:
        r["new"] = r["score"] >= MIN_SCORE_FOR_HISTORY and r["ticker"] not in before

    rows.sort(key=lambda r: (-r["score"], r["dd52"]))
    data = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof": asof,
        "rules": RULES,
        "universe": {
            "total": int(len(universe)),
            "scanned": len(rows),
            "us": sum(r["market"] == "US" for r in rows),
            "ca": sum(r["market"] == "CA" for r in rows),
        },
        "rows": rows,
    }

    DOCS.mkdir(exist_ok=True)
    HISTORY.mkdir(exist_ok=True)
    (DOCS / "data.json").write_text(json.dumps(data, separators=(",", ":")))
    flagged = [r for r in rows if r["score"] >= MIN_SCORE_FOR_HISTORY]
    (HISTORY / f"{asof}.json").write_text(
        json.dumps({"asof": asof, "rows": flagged}, separators=(",", ":"))
    )
    return data


def main() -> int:
    universe = load_universe()
    prices = fetch_prices(universe["ticker"].tolist())
    print(f"prices: {len(prices)} of {len(universe)} tickers")
    if len(prices) < 0.5 * len(universe):
        print("too few prices returned; data source may be down", file=sys.stderr)
        return 1

    data = run(universe, prices)
    counts: dict[int, int] = {}
    for r in data["rows"]:
        counts[r["score"]] = counts.get(r["score"], 0) + 1
    print(f"as of {data['asof']}: " + ", ".join(
        f"score {s}: {counts.get(s, 0)}" for s in (4, 3, 2, 1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
