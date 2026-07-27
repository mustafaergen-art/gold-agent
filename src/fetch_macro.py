"""
Makro yardımcı seriler — Altın Al-Sat Agent, Aşama 4 (sinyal #3).

DXY (dolar endeksi) ve 10Y ABD tahvil faizi — altınla ters ilişkili makro sürücüler.
Kaynak: Yahoo Finance.
  DX-Y.NYB : ABD Dolar Endeksi (DXY)
  ^TNX     : 10 yıllık ABD Hazine getirisi (%)

Çıktı: data/raw/dxy.parquet, data/raw/tnx.parquet
Kullanım: python src/fetch_macro.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

SERIES = {"dxy": "DX-Y.NYB", "tnx": "^TNX"}


def fetch_one(symbol: str) -> pd.Series:
    df = yf.download(symbol, period="5y", interval="1d", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    s = df["Close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize().astype("datetime64[ns]")
    return s[~s.index.duplicated(keep="last")].sort_index().dropna()


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for name, sym in SERIES.items():
        s = fetch_one(sym)
        s.to_frame("close").to_parquet(RAW / f"{name}.parquet")
        print(f"{name:4} ({sym:9}): {len(s)} gün | {s.index.min().date()} → "
              f"{s.index.max().date()} | son {s.iloc[-1]:.2f}")


if __name__ == "__main__":
    main()
