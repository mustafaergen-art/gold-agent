"""
CPI (enflasyon) yayınları ↔ altın tepkisi. Aşama 4 (haber katmanı #2).

Gerçek CPI (cpi_actual.csv) + yayın tarihleri/konsensüs (cpi_release_dates.csv)
birleştirilir; her yayın gününde altın tepkisi ölçülür ve CPI SÜRPRİZİ
(gerçek − beklenti) ile korelasyonu hesaplanır.

Hipotez sınaması: "sıcak" CPI sürprizi (gerçek > beklenti) altını nasıl etkiler?
  - Enflasyon koruması görüşü → altın ↑
  - Şahin Fed korkusu görüşü  → altın ↓
Veri hangisini söylüyor?

Getiriler (kapanış-kapanış):
  ret_0d : yayın günü tepkisi (t-1 → t; 08:30 ET reaksiyonunu içerir)
  ret_5d : yayın → +5 işlem günü

Çıktı: data/processed/cpi_gold_events.csv + konsol özeti
Kullanım: python src/analyze_cpi_gold.py
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

    act = pd.read_csv(RAW / "cpi_actual.csv", parse_dates=["ref_month"])
    act["ref_month"] = act["ref_month"].dt.to_period("M")

    rel = pd.read_csv(RAW / "cpi_release_dates.csv")
    rel["ref_month"] = pd.PeriodIndex(rel["ref_month"], freq="M")
    rel["release_date"] = pd.to_datetime(rel["release_date"], errors="coerce")

    m = rel.merge(act[["ref_month", "cpi_yoy", "cpi_mom"]], on="ref_month", how="left")
    m = m.dropna(subset=["release_date", "cpi_yoy"]).sort_values("release_date")
    # sürpriz = gerçek − beklenti (konsensüs varsa)
    m["surprise"] = (m["cpi_yoy"] - m["consensus_yoy"]).round(2)
    return close, m


def build(close, m) -> pd.DataFrame:
    idx, vals = close.index, close.values
    rows = []
    for _, r in m.iterrows():
        p = int(idx.searchsorted(r["release_date"]))
        if p == 0 or p >= len(vals):
            continue

        def ret(a, b):
            return round((vals[b] / vals[a] - 1) * 100, 2) if 0 <= a and b < len(vals) else None

        rows.append({
            "release_date": r["release_date"].date(),
            "ref_month": str(r["ref_month"]),
            "cpi_yoy": r["cpi_yoy"],
            "consensus_yoy": r["consensus_yoy"],
            "surprise": r["surprise"],
            "gold_close": round(float(vals[p]), 1),
            "ret_0d": ret(p - 1, p),
            "ret_5d": ret(p, p + 5) if p + 5 < len(vals) else None,
        })
    return pd.DataFrame(rows)


def spearman(a, b):
    return a.rank().corr(b.rank(), method="pearson")


def main() -> None:
    PROC.mkdir(parents=True, exist_ok=True)
    close, m = load()
    df = build(close, m)
    df.to_csv(PROC / "cpi_gold_events.csv", index=False)
    print(f"{len(df)} CPI yayını altınla hizalandı "
          f"({df['release_date'].min()} → {df['release_date'].max()})")

    sp = df.dropna(subset=["surprise"])
    print(f"\nSürprizi (konsensüs) olan yayın: {len(sp)}")
    print("\n=== CPI SÜRPRİZİ (gerçek−beklenti) ↔ altın tepkisi korelasyonu ===")
    print("(+ sürpriz = enflasyon beklenenden sıcak)")
    for col, lbl in [("ret_0d", "yayın günü"), ("ret_5d", "+5 gün")]:
        s = sp[["surprise", col]].dropna()
        print(f"  {lbl:11}: Pearson {s['surprise'].corr(s[col]):+.2f} | "
              f"Spearman {spearman(s['surprise'], s[col]):+.2f}  (n={len(s)})")

    # sürpriz yönüne göre gruplama
    sp = sp.assign(surp_dir=pd.cut(sp["surprise"], [-99, -0.05, 0.05, 99],
                                   labels=["soğuk (miss)", "beklenti", "sıcak (beat)"]))
    print("\n=== Sürpriz yönüne göre ortalama altın getirisi (%) ===")
    g = sp.groupby("surp_dir", observed=True)[["ret_0d", "ret_5d"]].mean().round(2)
    g["olay"] = sp.groupby("surp_dir", observed=True).size()
    print(g.to_string())

    print("\n=== En büyük 5 sıcak sürpriz gününde altın ===")
    print(sp.nlargest(5, "surprise")[
        ["release_date", "cpi_yoy", "consensus_yoy", "surprise", "ret_0d", "ret_5d"]
    ].to_string(index=False))
    print(f"\nKayıt: {(PROC / 'cpi_gold_events.csv').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
