"""
ABD CPI (enflasyon) gerçek verisi — Altın Al-Sat Agent, Aşama 4 (haber katmanı #2).

Kaynak: BLS public API v2 (anahtarsız; FRED bu ortamdan engelli).
Seri: CUUR0000SA0 = CPI-U, All items, US city average, NSA.

Referans ayı bazında endeks değerini çeker; YoY ve MoM % enflasyonu hesaplar.
(Yayın tarihleri ayrı bir adımda eklenir — BLS API yayın gününü vermez.)

Çıktı: data/raw/cpi_actual.csv  (ref_month, index, cpi_yoy, cpi_mom)
Kullanım: python src/fetch_cpi.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
SERIES = "CUUR0000SA0"


def fetch(start_year: int = 2020, end_year: int = 2026) -> pd.DataFrame:
    rows = []
    # BLS anahtarsız çağrıda 10 yıllık aralık sınırı var; parça parça çek
    yr = start_year
    while yr <= end_year:
        y2 = min(yr + 9, end_year)
        r = requests.post(API, json={
            "seriesid": [SERIES], "startyear": str(yr), "endyear": str(y2),
        }, timeout=30)
        r.raise_for_status()
        data = r.json()["Results"]["series"][0]["data"]
        for d in data:
            if d["period"].startswith("M"):  # aylık (M13 = yıllık ort, atla)
                if d["period"] == "M13":
                    continue
                val = d["value"].strip()
                if not val or val == "-":  # eksik değer
                    continue
                month = int(d["period"][1:])
                rows.append({
                    "ref_month": pd.Timestamp(int(d["year"]), month, 1),
                    "index": float(val),
                })
        yr = y2 + 1
    df = pd.DataFrame(rows).drop_duplicates("ref_month").sort_values("ref_month")
    df["cpi_yoy"] = (df["index"] / df["index"].shift(12) - 1) * 100
    df["cpi_mom"] = (df["index"] / df["index"].shift(1) - 1) * 100
    return df.reset_index(drop=True)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    df = fetch()
    df = df[df["ref_month"] >= "2021-01-01"].copy()  # YoY için 2020 yardımcıydı
    df[["cpi_yoy", "cpi_mom"]] = df[["cpi_yoy", "cpi_mom"]].round(2)
    out = RAW / "cpi_actual.csv"
    df.to_csv(out, index=False)
    print(f"{len(df)} aylık CPI kaydı ({df['ref_month'].min().date()} → {df['ref_month'].max().date()})")
    print("\nSon 6 ay:")
    print(df.tail(6).to_string(index=False))
    print(f"\nZirve YoY: {df['cpi_yoy'].max():.1f}% ({df.loc[df['cpi_yoy'].idxmax(),'ref_month'].date()})")
    print(f"Kayıt: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
