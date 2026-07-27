"""
Sözlük tonu vs LLM tonu karşılaştırma + altın korelasyonu. Aşama 3c (derinleştirme).

İki ton yöntemini karşılaştırır:
  - sözlük tabanlı  (fomc_tone.csv     : tone_score, + şahin / − güvercin)
  - LLM tabanlı     (fomc_tone_llm.csv : llm_score,  + şahin / − güvercin)

Uyum oranını, birbirleriyle korelasyonu ve HER İKİSİNİN altın getirisiyle
korelasyonunu raporlar → hangi yöntem daha güçlü sinyal veriyor?

Kullanım: python src/compare_tone.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"


def load():
    daily = pd.read_parquet(RAW / "gold_daily.parquet")
    close = daily["close"].copy()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close[~close.index.duplicated(keep="last")].sort_index()

    d = pd.read_csv(PROC / "fomc_tone.csv", parse_dates=["date"])
    d["date"] = d["date"].dt.normalize()
    l = pd.read_csv(PROC / "fomc_tone_llm.csv", parse_dates=["date"])
    l["date"] = l["date"].dt.normalize()

    m = d[["date", "tone_score", "tone"]].merge(
        l[["date", "llm_score", "llm_label"]], on="date", how="inner")
    return close, m


def fwd_returns(close, dates) -> pd.DataFrame:
    idx, vals = close.index, close.values
    out = {}
    for d in dates:
        p = int(idx.searchsorted(d))
        if p >= len(vals):
            out[d] = (None, None, None)
            continue
        def r(h):
            return (vals[p + h] / vals[p] - 1) * 100 if p + h < len(vals) else None
        out[d] = (r(1), r(5), r(20))
    return pd.DataFrame(
        [(d, *out[d]) for d in dates], columns=["date", "ret_1d", "ret_5d", "ret_20d"])


def spearman(a, b):
    return a.rank().corr(b.rank(), method="pearson")


def main() -> None:
    close, m = load()
    ret = fwd_returns(close, list(m["date"]))
    m = m.merge(ret, on="date")

    print("=== Sözlük vs LLM tonu — uyum ===")
    agree = (m["tone"] == m["llm_label"]).mean()
    print(f"  Etiket uyumu           : {agree:.0%}  ({int((m['tone']==m['llm_label']).sum())}/{len(m)})")
    print(f"  Skor korelasyonu       : Pearson {m['tone_score'].corr(m['llm_score']):+.2f} | "
          f"Spearman {spearman(m['tone_score'], m['llm_score']):+.2f}")

    print("\n=== Ton skoru ↔ altın getirisi korelasyonu (negatif = güvercin→altın↑) ===")
    print(f"  {'pencere':8} | {'SÖZLÜK (P / S)':>18} | {'LLM (P / S)':>18}")
    for col, lbl in [("ret_1d", "1 gün"), ("ret_5d", "1 hafta"), ("ret_20d", "1 ay")]:
        s = m[["tone_score", "llm_score", col]].dropna()
        dp, ds = s["tone_score"].corr(s[col]), spearman(s["tone_score"], s[col])
        lp, ls = s["llm_score"].corr(s[col]), spearman(s["llm_score"], s[col])
        print(f"  {lbl:8} | {dp:+.2f} / {ds:+.2f}      | {lp:+.2f} / {ls:+.2f}")

    print("\n=== LLM ton grubuna göre ortalama altın getirisi (%) ===")
    g = m.groupby("llm_label")[["ret_1d", "ret_5d", "ret_20d"]].mean().round(2)
    g["olay"] = m.groupby("llm_label").size()
    for t in ["dovish", "neutral", "hawkish"]:
        if t in g.index:
            row = g.loc[t]
            print(f"  {t:8} (n={int(row['olay']):2}): 1g {row['ret_1d']:+.2f} | "
                  f"1hf {row['ret_5d']:+.2f} | 1ay {row['ret_20d']:+.2f}")


if __name__ == "__main__":
    main()
