"""
Karar/sinyal motoru — Altın Al-Sat Agent, Aşama 5.

Üç sinyali birleştirip günlük bir bileşik skor ([-1, +1]) ve al/tut/sat
pozisyonu üretir, sonra 5 yıllık veride backtest eder (al-tut'a karşı).

Sinyaller (hepsi + = altın için yükseliş yönlü):
  1) trend : fiyatın 50 günlük ortalamaya göre konumu  (momentum/trend-takip)
  2) fed   : en son FOMC tonu (güvercin→+, şahin→−); ~30 günde doğrusal söner
  3) cpi   : en son CPI sürprizi (soğuk→+, sıcak→−); ~10 günde söner

Bileşik = w_trend*trend + w_fed*fed + w_cpi*cpi
Pozisyon: bileşik > +eşik → LONG(1); < −eşik → FLAT(0)  (yalnızca uzun/nakit)

NOT: Bu bir araştırma prototipidir, YATIRIM TAVSİYESİ DEĞİLDİR. Ağırlıklar
ve eşikler ayarlanabilir; küçük örnekle aşırı-uyum riski vardır.

Çıktı:
  - data/processed/signal_daily.csv
  - data/charts/signal_backtest.png
  - konsolda performans metrikleri
Kullanım: python src/signal_engine.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np               # noqa: E402
import pandas as pd              # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
OUT = ROOT / "data" / "charts"

# ayarlanabilir parametreler (ağırlık toplamı = 1)
W_TREND, W_DXY, W_FED, W_CPI = 0.35, 0.30, 0.20, 0.15
FED_DECAY_DAYS = 30
CPI_DECAY_DAYS = 10
ENTER_THR = 0.10       # bileşik bu eşiği geçerse LONG
TONE_SCALE = 5.0       # ton skoru ~[-5,5] → [-1,1]
SURPRISE_SCALE = 0.4   # CPI sürprizi ~±0.4 → [-1,1]
DXY_MA = 20            # DXY trend için hareketli ortalama
DXY_SCALE = 0.015      # DXY'nin MA'dan sapması ~1.5% → [-1,1]


def load():
    daily = pd.read_parquet(RAW / "gold_daily.parquet")
    close = daily["close"].copy()
    close.index = (pd.to_datetime(close.index).tz_localize(None)
                   .normalize().astype("datetime64[ns]"))
    close = close[~close.index.duplicated(keep="last")].sort_index()

    tone = pd.read_csv(PROC / "fomc_tone.csv", parse_dates=["date"]).sort_values("date")
    tone["date"] = tone["date"].astype("datetime64[ns]")
    cpi = pd.read_csv(PROC / "cpi_gold_events.csv", parse_dates=["release_date"])
    cpi["release_date"] = cpi["release_date"].astype("datetime64[ns]")
    cpi = cpi.dropna(subset=["surprise"]).sort_values("release_date")

    dxy = pd.read_parquet(RAW / "dxy.parquet")["close"]
    dxy.index = pd.to_datetime(dxy.index).tz_localize(None).normalize().astype("datetime64[ns]")
    dxy = dxy[~dxy.index.duplicated(keep="last")].sort_index()
    return close, tone, cpi, dxy


def build_signals(close, tone, cpi, dxy) -> pd.DataFrame:
    df = pd.DataFrame({"close": close})
    df["ret"] = df["close"].pct_change()

    # 1) trend: fiyat / MA50 − 1, [-1,1] aralığına sıkıştır
    ma50 = df["close"].rolling(50).mean()
    df["trend"] = ((df["close"] / ma50 - 1) / 0.05).clip(-1, 1)

    # 4) dxy: dolar endeksi MA20'nin altındaysa (dolar zayıf) → altın için + sinyal
    dxy_al = dxy.reindex(df.index).ffill()
    dxy_ma = dxy_al.rolling(DXY_MA).mean()
    df["dxy"] = (-(dxy_al / dxy_ma - 1) / DXY_SCALE).clip(-1, 1)

    # 2) fed: en son FOMC tonu, söndürülmüş; güvercin(−skor)→+ sinyal
    t = tone.rename(columns={"date": "event"})[["event", "tone_score"]]
    df = pd.merge_asof(df.rename_axis("d").reset_index(),
                       t, left_on="d", right_on="event", direction="backward")
    age = (df["d"] - df["event"]).dt.days
    decay = (1 - age / FED_DECAY_DAYS).clip(lower=0)
    df["fed"] = (-df["tone_score"] / TONE_SCALE).clip(-1, 1) * decay

    # 3) cpi: en son sürpriz, söndürülmüş; soğuk(−sürpriz)→+ sinyal
    c = cpi.rename(columns={"release_date": "cevent"})[["cevent", "surprise"]]
    df = pd.merge_asof(df, c, left_on="d", right_on="cevent", direction="backward")
    cage = (df["d"] - df["cevent"]).dt.days
    cdecay = (1 - cage / CPI_DECAY_DAYS).clip(lower=0)
    df["cpi"] = (-df["surprise"] / SURPRISE_SCALE).clip(-1, 1) * cdecay

    df = df.set_index("d")
    for col in ["trend", "dxy", "fed", "cpi"]:
        df[col] = df[col].fillna(0)
    df["composite"] = (W_TREND * df["trend"] + W_DXY * df["dxy"]
                       + W_FED * df["fed"] + W_CPI * df["cpi"])
    df["position"] = np.where(df["composite"] > ENTER_THR, 1.0,
                              np.where(df["composite"] < -ENTER_THR, 0.0, np.nan))
    # eşik bandında önceki pozisyonu koru (histerezis), başta flat
    df["position"] = df["position"].ffill().fillna(0.0)
    return df


def latest_signal() -> dict:
    """Menü çubuğu için: en güncel günün bileşik sinyalini AL/TUT/SAT olarak döndürür."""
    close, tone, cpi, dxy = load()
    df = build_signals(close, tone, cpi, dxy)
    last = df.iloc[-1]
    comp = float(last["composite"])
    if comp > ENTER_THR:
        label, emoji = "AL", "🟢"
    elif comp < -ENTER_THR:
        label, emoji = "SAT", "🔴"
    else:
        label, emoji = "TUT", "⚪"
    return {
        "date": df.index[-1].date().isoformat(),
        "composite": round(comp, 2), "label": label, "emoji": emoji,
        "trend": round(float(last["trend"]), 2), "dxy": round(float(last["dxy"]), 2),
        "fed": round(float(last["fed"]), 2), "cpi": round(float(last["cpi"]), 2),
    }


def metrics(ret: pd.Series) -> dict:
    ret = ret.dropna()
    n = len(ret)
    equity = (1 + ret).cumprod()
    ann_ret = equity.iloc[-1] ** (252 / n) - 1 if n else 0
    ann_vol = ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol else 0
    dd = (equity / equity.cummax() - 1).min()
    return {"toplam_%": (equity.iloc[-1] - 1) * 100, "yıllık_%": ann_ret * 100,
            "yıllık_oynaklık_%": ann_vol * 100, "sharpe": sharpe, "max_dd_%": dd * 100}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    close, tone, cpi, dxy = load()
    df = build_signals(close, tone, cpi, dxy)

    strat_ret = df["position"].shift(1) * df["ret"]
    df["strat_equity"] = (1 + strat_ret.fillna(0)).cumprod()
    df["bh_equity"] = (1 + df["ret"].fillna(0)).cumprod()
    df.to_csv(PROC / "signal_daily.csv")

    m_s, m_b = metrics(strat_ret), metrics(df["ret"])
    days_long = (df["position"] == 1).mean() * 100

    print("=== Backtest: sinyal stratejisi vs al-tut (5 yıl, GC=F) ===")
    print(f"{'metrik':22} {'STRATEJİ':>12} {'AL-TUT':>12}")
    for k in ["toplam_%", "yıllık_%", "yıllık_oynaklık_%", "sharpe", "max_dd_%"]:
        print(f"{k:22} {m_s[k]:>12.2f} {m_b[k]:>12.2f}")
    print(f"\nPozisyonda (long) geçen zaman: %{days_long:.0f}")
    print(f"Güncel pozisyon: {'LONG (al)' if df['position'].iloc[-1] else 'FLAT (nakit)'}"
          f" | bileşik skor: {df['composite'].iloc[-1]:+.2f}")

    # grafik: equity eğrileri + fiyat üstünde pozisyon
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), dpi=130,
                                   gridspec_kw={"height_ratios": [2, 1]}, sharex=True)
    ax1.plot(df.index, df["bh_equity"], color="#8a8a8a", lw=1.4, label="Al-tut")
    ax1.plot(df.index, df["strat_equity"], color="#1a9850", lw=1.6, label="Sinyal stratejisi")
    ax1.set_title("Altın karar motoru — backtest (1$ başlangıç)", fontsize=13, fontweight="bold")
    ax1.set_ylabel("Portföy değeri ($)")
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.2)

    ax2.plot(df.index, df["composite"], color="#333", lw=0.9, label="Bileşik skor")
    ax2.axhline(ENTER_THR, color="#1a9850", ls="--", lw=0.7)
    ax2.axhline(-ENTER_THR, color="#d73027", ls="--", lw=0.7)
    ax2.fill_between(df.index, -1, 1, where=(df["position"] == 1),
                     color="#1a9850", alpha=0.08, label="LONG dönemleri")
    ax2.set_ylabel("Sinyal")
    ax2.set_ylim(-1, 1)
    ax2.legend(loc="upper left", fontsize=8)
    ax2.grid(True, alpha=0.2)

    path = OUT / "signal_backtest.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"\nGrafik: {path.relative_to(ROOT)}")
    print("\n⚠️ Araştırma prototipi — yatırım tavsiyesi değildir.")


if __name__ == "__main__":
    main()
