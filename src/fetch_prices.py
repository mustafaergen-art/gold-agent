"""
Altın fiyat verisi çekme modülü — Altın Al-Sat Agent projesi.

Kaynak: Yahoo Finance (yfinance)
Enstrüman: GC=F  (COMEX Gold Futures — spot XAU/USD ile ~0.999 korelasyon)

Çekilen veriler:
  1) Günlük (1d)  — son 5 yıl
  2) Saatlik (1h) — Yahoo'nun izin verdiği maksimum (~730 gün / ~2.4 yıl)

Çıktılar:  gold-agent/data/raw/ altında hem .parquet hem .csv
  - gold_daily.(parquet|csv)
  - gold_hourly.(parquet|csv)

Kullanım:
    python src/fetch_prices.py
    python src/fetch_prices.py --symbol GC=F --years 5
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yfinance as yf

# Proje kökü: bu dosya src/ içinde → bir üst klasör
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

SYMBOL = "GC=F"  # COMEX Gold Futures


def _flatten(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """yfinance'in ürettiği MultiIndex kolonları düzleştirir ve standart isimlere getirir."""
    if isinstance(df.columns, pd.MultiIndex):
        # (Field, Ticker) -> Field
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns=str.lower)
    # index adını 'datetime' yap
    df.index.name = "datetime"
    # sadece OHLCV
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep].copy()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["close"])
    return df


def fetch_daily(symbol: str = SYMBOL, years: int = 5) -> pd.DataFrame:
    print(f"[günlük] {symbol} — son {years} yıl çekiliyor...")
    df = yf.download(
        symbol, period=f"{years}y", interval="1d",
        auto_adjust=True, progress=False,
    )
    df = _flatten(df, symbol)
    print(f"[günlük] {len(df)} satır | {df.index.min().date()} → {df.index.max().date()}")
    return df


def fetch_hourly(symbol: str = SYMBOL) -> pd.DataFrame:
    # Yahoo intraday 1h için maksimum ~730 gün geriye izin verir
    print(f"[saatlik] {symbol} — maksimum geçmiş (~730 gün) çekiliyor...")
    df = yf.download(
        symbol, period="730d", interval="1h",
        auto_adjust=True, progress=False,
    )
    df = _flatten(df, symbol)
    # saat dilimini UTC'ye normalize et (tutarlı birleştirme için)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC")
    print(f"[saatlik] {len(df)} satır | {df.index.min()} → {df.index.max()} (UTC)")
    return df


def save(df: pd.DataFrame, name: str) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    pq = RAW / f"{name}.parquet"
    csv = RAW / f"{name}.csv"
    df.to_parquet(pq)
    df.to_csv(csv)
    print(f"[kayıt] {pq.relative_to(ROOT)}  &  {csv.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Altın fiyat verisi çekme")
    ap.add_argument("--symbol", default=SYMBOL)
    ap.add_argument("--years", type=int, default=5)
    args = ap.parse_args()

    daily = fetch_daily(args.symbol, args.years)
    save(daily, "gold_daily")

    hourly = fetch_hourly(args.symbol)
    save(hourly, "gold_hourly")

    print("\n=== ÖZET ===")
    print(f"Günlük : {len(daily):>6} satır  ({daily.index.min().date()} → {daily.index.max().date()})")
    print(f"Saatlik: {len(hourly):>6} satır  ({hourly.index.min().date()} → {hourly.index.max().date()})")


if __name__ == "__main__":
    main()
