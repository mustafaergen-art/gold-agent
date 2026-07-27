"""
FOMC kararları ↔ altın fiyatı olay analizi — Altın Al-Sat Agent, Aşama 3.

Her FOMC faiz kararını altın (GC=F) fiyatına hizalar ve karar öncesi/sonrası
getirileri karar yönüne (artış/sabit/indirim) göre gruplar.

Mantık — "olay penceresi" (event study):
  Her karar günü t için:
    ret_pre_1d   : t-1 → t   kapanış getirisi (karar gününün tepkisi)
    ret_post_1d  : t   → t+1 kapanış getirisi (ertesi gün)
    ret_post_5d  : t   → t+5 kapanış getirisi (1 hafta)
  (Karar günü ABD tatili/hafta sonuna denk gelirse en yakın işlem gününe hizalanır.)

Çıktı:
  - data/processed/fomc_gold_events.csv   (olay bazında getiriler)
  - konsolda yön bazında ortalama getiri + "yukarı kapanma oranı" özeti

Kullanım:
    python src/analyze_fomc_gold.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"


def load() -> tuple[pd.DataFrame, pd.Series]:
    ev = pd.read_parquet(RAW / "fomc_events.parquet")
    ev = ev[ev["has_rate_decision"]].copy()
    ev["date"] = pd.to_datetime(ev["date"])

    daily = pd.read_parquet(RAW / "gold_daily.parquet")
    close = daily["close"].copy()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close[~close.index.duplicated(keep="last")].sort_index()
    return ev, close


def _pos(idx: pd.DatetimeIndex, date: pd.Timestamp) -> int | None:
    """Karar gününe eşit veya ondan sonraki ilk işlem gününün konumu."""
    loc = idx.searchsorted(date)
    return int(loc) if loc < len(idx) else None


def build_events(ev: pd.DataFrame, close: pd.Series) -> pd.DataFrame:
    idx = close.index
    vals = close.values
    rows = []
    for _, r in ev.iterrows():
        p = _pos(idx, r["date"].normalize())
        if p is None or p == 0:
            continue

        def ret(a: int, b: int):
            if a < 0 or b >= len(vals):
                return None
            return round((vals[b] / vals[a] - 1) * 100, 2)

        rows.append({
            "date": r["date"].date(),
            "direction": r["direction"],
            "change_bps": r["change_bps"],
            "target_upper": r["target_upper"],
            "gold_close": round(float(vals[p]), 1),
            "ret_pre_1d": ret(p - 1, p),
            "ret_post_1d": ret(p, p + 1) if p + 1 < len(vals) else None,
            "ret_post_5d": ret(p, p + 5) if p + 5 < len(vals) else None,
        })
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    def agg(g):
        return pd.Series({
            "olay_sayısı": len(g),
            "ort_karar_günü_%": round(g["ret_pre_1d"].mean(), 2),
            "yukarı_oranı_karar_günü": round((g["ret_pre_1d"] > 0).mean(), 2),
            "ort_ertesi_gün_%": round(g["ret_post_1d"].mean(), 2),
            "ort_1_hafta_%": round(g["ret_post_5d"].mean(), 2),
            "yukarı_oranı_1_hafta": round((g["ret_post_5d"] > 0).mean(), 2),
        })
    order = ["cut", "hold", "hike"]
    out = df.groupby("direction").apply(agg, include_groups=False)
    return out.reindex([o for o in order if o in out.index])


def main() -> None:
    PROC.mkdir(parents=True, exist_ok=True)
    ev, close = load()
    df = build_events(ev, close)
    df.to_csv(PROC / "fomc_gold_events.csv", index=False)

    print(f"Altın günlük veri: {close.index.min().date()} → {close.index.max().date()}")
    print(f"Analiz edilen FOMC kararı: {len(df)}\n")

    print("=== Karar yönüne göre altın tepkisi (%) ===")
    print(summarize(df).to_string())

    print("\n=== Son 6 karar (detay) ===")
    print(df.tail(6).to_string(index=False))
    print(f"\nKayıt: {(PROC / 'fomc_gold_events.csv').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
