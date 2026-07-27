"""
Walk-forward / sağlamlık validasyonu — Altın Al-Sat Agent, Aşama 5 doğrulama.

Karar motorunun aşırı-uyumlu (overfit) olup olmadığını test eder:

  1) ALT-DÖNEM: 5 yılı ardışık dilimlere böl, her dilimde strateji vs al-tut
     Sharpe. Kenar (edge) tüm rejimlerde tutuyor mu?
  2) PARAMETRE SAĞLAMLIĞI: giriş eşiğini tara — kenar tek bir "sihirli"
     değerde mi yoksa geniş aralıkta mı? (bıçak sırtı = overfit)
  3) GENİŞLEYEN-PENCERE OOS: her 6 ayda bir, SADECE geçmiş veriyle en iyi eşiği
     seç, sonraki 6 ayda uygula (görülmemiş veri). Dikilen OOS getirisi al-tut'u
     geçiyor mu?

Ağırlıklar sabit tutulur (yalnızca eşik optimize edilir) → overfit yüzeyi küçük.

Kullanım: python src/walk_forward.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from signal_engine import (W_TREND, W_DXY, W_FED, W_CPI, load, build_signals, metrics)  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def composite(df):
    return (W_TREND * df["trend"] + W_DXY * df["dxy"]
            + W_FED * df["fed"] + W_CPI * df["cpi"])


def strat_returns(df, comp, thr):
    pos = np.where(comp > thr, 1.0, np.where(comp < -thr, 0.0, np.nan))
    pos = pd.Series(pos, index=df.index).ffill().fillna(0.0)
    return pos.shift(1) * df["ret"]


def sharpe(ret):
    ret = ret.dropna()
    v = ret.std() * np.sqrt(252)
    return (ret.mean() * 252) / v if v else 0.0


def main() -> None:
    close, tone, cpi, dxy = load()
    df = build_signals(close, tone, cpi, dxy)
    comp = composite(df)

    # ---- 1) ALT-DÖNEM ----
    print("=== 1) Alt-dönem tutarlılığı (Sharpe) ===")
    print(f"{'dönem':17} {'STRATEJİ':>10} {'AL-TUT':>10}  {'kazanan':>8}")
    edges = pd.date_range("2021-07-01", "2026-07-01", freq="12MS")
    for a, b in zip(edges[:-1], edges[1:]):
        sl = (df.index >= a) & (df.index < b)
        s_ret = strat_returns(df, comp, 0.10)[sl]
        b_ret = df["ret"][sl]
        ss, bs = sharpe(s_ret), sharpe(b_ret)
        win = "strateji" if ss > bs else "al-tut"
        print(f"{a.date()}→{b.date()}  {ss:>10.2f} {bs:>10.2f}  {win:>8}")

    # ---- 2) PARAMETRE SAĞLAMLIĞI ----
    print("\n=== 2) Giriş eşiği taraması (tüm dönem) ===")
    print(f"{'eşik':>6} {'Sharpe':>8} {'max_dd_%':>9} {'long_%':>7}")
    for thr in [0.0, 0.05, 0.10, 0.15, 0.20, 0.25]:
        r = strat_returns(df, comp, thr)
        pos_share = (strat_returns(df, comp, thr).notna() &
                     (pd.Series(np.where(comp > thr, 1, np.where(comp < -thr, 0, np.nan)),
                                index=df.index).ffill().fillna(0) == 1)).mean() * 100
        m = metrics(r)
        print(f"{thr:>6.2f} {m['sharpe']:>8.2f} {m['max_dd_%']:>9.1f} {pos_share:>7.0f}")
    print("(Sharpe geniş eşik aralığında al-tut 0.99'un üstündeyse → sağlam, bıçak sırtı değil)")

    # ---- 3) GENİŞLEYEN-PENCERE OOS ----
    print("\n=== 3) Genişleyen-pencere OOS (eşik geçmişten seçilir) ===")
    grid = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25]
    oos = pd.Series(dtype=float)
    starts = pd.date_range("2023-07-01", "2026-01-01", freq="6MS")
    for cut in starts:
        nxt = cut + pd.DateOffset(months=6)
        train = df.index < cut
        if train.sum() < 200:
            continue
        # geçmişte en iyi eşiği seç
        best_thr = max(grid, key=lambda t: sharpe(strat_returns(df, comp, t)[train]))
        test = (df.index >= cut) & (df.index < nxt)
        oos = pd.concat([oos, strat_returns(df, comp, best_thr)[test]])
    bh = df["ret"].reindex(oos.index)
    ms, mb = metrics(oos), metrics(bh)
    print(f"OOS dönem: {oos.index.min().date()} → {oos.index.max().date()}  (n={len(oos)})")
    print(f"{'metrik':12} {'OOS STRATEJİ':>14} {'AL-TUT':>10}")
    for k in ["toplam_%", "yıllık_%", "sharpe", "max_dd_%"]:
        print(f"{k:12} {ms[k]:>14.2f} {mb[k]:>10.2f}")


if __name__ == "__main__":
    main()
