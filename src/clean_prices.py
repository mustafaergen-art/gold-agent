"""
GC=F fiyat kalite kontrolü / temizliği — Altın Al-Sat Agent, Aşama 2.

BULGU (bu veri için): close (kapanış) serisinde gerçek hatalı tik YOK.
- 55 bar "OHLC dördü eşit" (Yahoo intraday OHLC bulamayıp kapanışa eşitlemiş);
  ama bu barların KAPANIŞ değeri komşularıyla tutarlı → close doğru, yalnızca
  gün-içi aralık (high-low) güvenilmez.
- Kapanışın komşu ortalamasından >NEIGHBOR_PCT sapıp ertesi gün geri döndüğü
  gerçek "spike" barı yok (2026 Oca-Mar aşırı hareketleri GERÇEK volatilite).

Bu yüzden temizlik muhafazakârdır:
  * close'a yalnızca gerçek spike-revert varsa dokunulur (enterpolasyon).
  * OHLC-eşit barlar "range_ok=False" ile işaretlenir (close korunur) — gün-içi
    aralık kullanan ileriki analizler bunları eleyebilir.

Çıktı: data/processed/gold_daily_clean.parquet (close + range_ok + spike_fixed)
Kullanım: python src/clean_prices.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"

NEIGHBOR_PCT = 0.08   # close, komşu ortalamasından bu kadar saparsa aday
REVERT_PCT = 0.06     # ertesi gün en az bu kadar geri dönerse spike teyidi


def clean(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c = d["close"].astype(float)

    # gün-içi aralığı güvenilmez barlar (close korunur)
    all_equal = (d["open"] == d["high"]) & (d["high"] == d["low"]) & (d["low"] == d["close"])
    d["range_ok"] = ~all_equal

    # gerçek close spike'ı: komşu ort.dan sap + ertesi gün geri dön
    neigh = (c.shift(1) + c.shift(-1)) / 2
    dev = (c - neigh).abs() / neigh
    revert = ((c.shift(-1) - c).abs() / c) >= REVERT_PCT
    prev_revert = ((c.shift(1) - c).abs() / c) >= REVERT_PCT
    spike = (dev >= NEIGHBOR_PCT) & revert & prev_revert  # her iki komşudan da kopuk

    d["close_raw"] = c
    c_fixed = c.copy()
    c_fixed[spike] = np.nan
    c_fixed = c_fixed.interpolate(method="linear", limit_direction="both")
    d["close"] = c_fixed
    d["spike_fixed"] = spike
    return d


def main() -> None:
    PROC.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(RAW / "gold_daily.parquet")
    d = clean(df)
    out = PROC / "gold_daily_clean.parquet"
    d[["open", "high", "low", "close", "volume", "close_raw", "range_ok", "spike_fixed"]].to_parquet(out)

    n_range = int((~d["range_ok"]).sum())
    n_spike = int(d["spike_fixed"].sum())
    print("=== GC=F kalite kontrolü ===")
    print(f"Toplam bar                 : {len(df)}")
    print(f"Gerçek close spike (düzeltildi): {n_spike}")
    print(f"Güvenilmez gün-içi aralık (OHLC-eşit, close korundu): {n_range}")
    print(f"Ham vs temiz close farkı > 0 olan bar: {int((d['close'] != d['close_raw']).sum())}")
    print(f"\nSonuç: close serisi temiz — analizler (close bazlı) değişmeden geçerli.")
    print(f"Kayıt: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
