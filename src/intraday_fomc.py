"""
FOMC açıklama anı — saatlik intraday altın tepkisi. Aşama 3d.

FOMC açıklamaları 14:00 ET'de yayınlanır. Saatlik altın verisi (GC=F, UTC)
2024-02'den başladığı için bu pencereye düşen FOMC toplantıları için
açıklama saati etrafındaki tepki ölçülür:

  pre_1h   : açıklama saatinden önceki saatin getirisi (t-1 → t0)
  react_1h : açıklama saati → +1 saat
  react_3h : açıklama saati → +3 saat

t0 = 14:00 ET'yi içeren saatlik bar (DST zoneinfo ile UTC'ye çevrilir).

Çıktı: data/processed/fomc_intraday.csv + konsol özeti
Kullanım: python src/intraday_fomc.py
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def load():
    h = pd.read_parquet(RAW / "gold_hourly.parquet")
    close = h["close"].sort_index()

    ev = pd.read_parquet(RAW / "fomc_events.parquet")
    ev = ev[ev["has_rate_decision"]].copy()
    ev["date"] = pd.to_datetime(ev["date"]).dt.normalize()

    tone = pd.read_csv(PROC / "fomc_tone.csv", parse_dates=["date"])
    tone["date"] = tone["date"].dt.normalize()

    ev = ev.merge(tone[["date", "tone", "tone_score"]], on="date", how="left")
    return close, ev


def announce_utc(day: pd.Timestamp) -> pd.Timestamp:
    """O günün 14:00 ET anını UTC saatlik bar zamanına çevirir."""
    local = datetime(day.year, day.month, day.day, 14, 0, tzinfo=ET)
    return pd.Timestamp(local.astimezone(UTC)).floor("h")


def build(close: pd.Series, ev: pd.DataFrame) -> pd.DataFrame:
    idx = close.index
    vals = close.values
    lo, hi = idx.min(), idx.max()
    rows = []
    for _, r in ev.iterrows():
        t0 = announce_utc(r["date"])
        if t0 < lo or t0 > hi:
            continue  # saatlik pencere dışında
        pos = int(idx.searchsorted(t0))
        if pos == 0 or pos >= len(vals):
            continue
        bar_time = idx[pos]
        # bar açıklama saatinden >2 saat uzaksa güvenme (veri boşluğu)
        if abs((bar_time - t0).total_seconds()) > 2 * 3600:
            continue

        def ret(h):
            j = pos + h
            return round((vals[j] / vals[pos] - 1) * 100, 3) if 0 <= j < len(vals) else None

        rows.append({
            "date": r["date"].date(),
            "direction": r["direction"],
            "tone": r["tone"],
            "announce_utc": bar_time.strftime("%Y-%m-%d %H:%M"),
            "price_t0": round(float(vals[pos]), 1),
            "pre_1h": ret(-1),
            "react_1h": ret(1),
            "react_3h": ret(3),
        })
    return pd.DataFrame(rows)


def main() -> None:
    PROC.mkdir(parents=True, exist_ok=True)
    close, ev = load()
    df = build(close, ev)
    df.to_csv(PROC / "fomc_intraday.csv", index=False)

    print(f"Saatlik pencerede {len(df)} FOMC kararı bulundu "
          f"({close.index.min().date()} → {close.index.max().date()})\n")
    print("=== Açıklama anı intraday tepki (%) — olay bazında ===")
    print(df.to_string(index=False))

    print("\n=== Karar yönüne göre ortalama (%) ===")
    g = df.groupby("direction")[["pre_1h", "react_1h", "react_3h"]].mean().round(3)
    g["olay"] = df.groupby("direction").size()
    print(g.to_string())
    print(f"\nKayıt: {(PROC / 'fomc_intraday.csv').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
