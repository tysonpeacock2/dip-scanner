import json, shutil, sys, tempfile
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scan

def series(vals):
    idx = pd.bdate_range(end="2026-11-24", periods=len(vals))
    return pd.Series(vals, index=idx, dtype=float)

rng = np.random.default_rng(7)
n = 300
up   = 100 * np.cumprod(1 + 0.002 + rng.normal(0, 0.004, n))
gentle = 100 * np.cumprod(1 + 0.001 + rng.normal(0, 0.004, n))
broke = gentle.copy(); broke[-5:] = broke[-6] * np.cumprod([0.97]*5)  # drop through the 200-day
pull = up.copy(); pull[-5:] = pull[-6] * np.cumprod([0.97]*5)          # -14% in 5 days
down = 100 * np.cumprod(np.full(n, 0.998))                              # steady slide
flat = np.full(n, 50.0)
short = 100 * np.cumprod(1 + rng.normal(0, 0.01, 100))

cases = {"UP": up, "PULL": pull, "BROKE": broke, "DOWN": down, "FLAT": flat, "SHORT": short}
res = {k: scan.compute(series(v)) for k, v in cases.items()}
for k, r in res.items():
    print(f"{k:6} score={r['score']} label={r['label']:9} dd52={r['dd52']:+.3f} "
          f"ret5={r['ret5']:+.3f} rsi={r['rsi']} vs200={r['vs200']} hits={r['hits']}")

assert res["UP"]["score"] == 0
assert res["PULL"]["label"] == "Pullback" and "ret5" in res["PULL"]["hits"] and "below200" not in res["PULL"]["hits"]
assert res["DOWN"]["label"] == "Downtrend" and set(res["DOWN"]["hits"]) >= {"dd52", "below200", "rsi"}
assert res["BROKE"]["label"] == "Mixed" and "below200" in res["BROKE"]["hits"]
assert res["FLAT"]["score"] == 0 and res["FLAT"]["rsi"] == 50.0
assert res["SHORT"]["vs200"] is None and "below200" not in res["SHORT"]["hits"]

# RSI vs independent Wilder loop
x = 100 * np.cumprod(1 + rng.normal(0, 0.02, 250))
d = np.diff(x); g = np.clip(d, 0, None); l = np.clip(-d, 0, None)
ag, al = g[:14].mean(), l[:14].mean()   # classic seed: simple average
for i in range(14, len(d)):
    ag = (ag * 13 + g[i]) / 14; al = (al * 13 + l[i]) / 14
ref = 100 - 100 / (1 + ag / al)
mine = scan.rsi_wilder(series(x)).iloc[-1]
print(f"RSI check: mine={mine:.2f} reference={ref:.2f} diff={abs(mine-ref):.3f}")
assert abs(mine - ref) < 0.5   # seeds differ slightly; converge over 250 bars

# End-to-end run + NEW badge across two days, isolated temp dir
tmp = Path(tempfile.mkdtemp())
scan.DOCS, scan.HISTORY = tmp / "docs", tmp / "docs" / "history"
uni = pd.DataFrame([
    {"ticker": "PULL", "name": "Pullback Co", "sector": "Health Care", "market": "US"},
    {"ticker": "DOWN.TO", "name": "Downtrend Corp", "sector": "Energy", "market": "CA"},
    {"ticker": "UP", "name": "Uptrend Inc", "sector": "Information Technology", "market": "US"},
])
day1 = {"PULL": series(pull[:-1]), "DOWN.TO": series(down[:-1]), "UP": series(up[:-1])}
day1 = {k: v.set_axis(pd.bdate_range(end="2026-11-23", periods=len(v))) for k, v in day1.items()}
scan.run(uni, day1)
day2 = {"PULL": series(pull), "DOWN.TO": series(down), "UP": series(up)}
d2 = scan.run(uni, day2)
print("day2:", [(r["ticker"], r["score"], r["label"], r["new"]) for r in d2["rows"]])
by = {r["ticker"]: r for r in d2["rows"]}
assert by["DOWN.TO"]["new"] is False          # already flagged on day 1
print("history files:", sorted(p.name for p in scan.HISTORY.glob("*.json")))
shutil.rmtree(tmp)
print("ALL TESTS PASSED")
