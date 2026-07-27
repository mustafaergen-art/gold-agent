"""
FOMC ton okları + altın korelasyon grafiği — Altın Al-Sat Agent, Aşama 3c.

Altın günlük fiyat grafiğinin üzerine her FOMC açıklamasının tonuna göre ok koyar:
  güvercin (dovish)  → YUKARI yeşil ok  (altın için pozitif beklenti)
  şahin   (hawkish)  → AŞAĞI kırmızı ok (altın için negatif beklenti)
  nötr               → gri nokta

Ayrıca ton skoru ile açıklama SONRASI altın getirileri arasındaki korelasyonu
(Pearson + Spearman) hesaplar ve yön bazında ortalama getiriyi raporlar.

Çıktı:
  - data/charts/fomc_tone_gold.png
  - konsolda korelasyon özeti

Kullanım:  python src/chart_fomc.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt     # noqa: E402
import pandas as pd                 # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
OUT = ROOT / "data" / "charts"

TONE_COLOR = {"dovish": "#1a9850", "hawkish": "#d73027", "neutral": "#999999"}


def load():
    daily = pd.read_parquet(RAW / "gold_daily.parquet")
    close = daily["close"].copy()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close[~close.index.duplicated(keep="last")].sort_index()

    tone = pd.read_csv(PROC / "fomc_tone.csv", parse_dates=["date"])
    tone["date"] = tone["date"].dt.normalize()
    return close, tone


def forward_returns(close: pd.Series, tone: pd.DataFrame) -> pd.DataFrame:
    """Her FOMC tarihine, açıklama sonrası 1/5/20 işlem günü getirilerini ekler."""
    idx = close.index
    vals = close.values
    rows = []
    for _, r in tone.iterrows():
        p = int(idx.searchsorted(r["date"]))
        if p >= len(vals):
            continue

        def ret(h):
            return round((vals[p + h] / vals[p] - 1) * 100, 2) if p + h < len(vals) else None

        rows.append({
            "date": r["date"],
            "tone": r["tone"],
            "tone_score": r["tone_score"],
            "gold_close": round(float(vals[p]), 1),
            "ret_1d": ret(1),
            "ret_5d": ret(5),
            "ret_20d": ret(20),
        })
    return pd.DataFrame(rows)


def correlation_report(df: pd.DataFrame) -> str:
    lines = ["=== Ton skoru ↔ açıklama sonrası altın getirisi korelasyonu ===",
             "(ton skoru: + şahin / − güvercin.  Teori: güvercin → altın ↑, yani NEGATİF korelasyon beklenir)\n"]
    for col, label in [("ret_1d", "1 gün"), ("ret_5d", "1 hafta"), ("ret_20d", "1 ay")]:
        sub = df[["tone_score", col]].dropna()
        pear = sub["tone_score"].corr(sub[col], method="pearson")
        # Spearman = sıralamaların Pearson korelasyonu (scipy'siz)
        spear = sub["tone_score"].rank().corr(sub[col].rank(), method="pearson")
        lines.append(f"  {label:7} sonrası: Pearson {pear:+.2f} | Spearman {spear:+.2f}  (n={len(sub)})")

    lines.append("\n=== Ton grubuna göre ortalama getiri (%) ===")
    g = df.groupby("tone")[["ret_1d", "ret_5d", "ret_20d"]].mean().round(2)
    g["olay"] = df.groupby("tone").size()
    for t in ["dovish", "neutral", "hawkish"]:
        if t in g.index:
            row = g.loc[t]
            lines.append(f"  {t:8} (n={int(row['olay']):2}): 1g {row['ret_1d']:+.2f} | "
                         f"1hf {row['ret_5d']:+.2f} | 1ay {row['ret_20d']:+.2f}")
    return "\n".join(lines)


def make_chart(close: pd.Series, tone: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(14, 6.2), dpi=130)
    ax.plot(close.index, close.values, color="#8a8a8a", lw=1.0, alpha=0.8, zorder=1)
    ax.fill_between(close.index, close.values, close.values.min(),
                    color="#C8A100", alpha=0.05, zorder=0)

    span = close.values.max() - close.values.min()
    off = span * 0.02
    for _, r in tone.iterrows():
        if r["date"] not in close.index:
            pos = close.index.searchsorted(r["date"])
            if pos >= len(close):
                continue
            price = close.values[pos]
            date = close.index[pos]
        else:
            price = close.loc[r["date"]]
            date = r["date"]
        t = r["tone"]
        if t == "dovish":       # yukarı yeşil ok, fiyatın altına
            ax.scatter(date, price - off, marker="^", s=90,
                       color=TONE_COLOR[t], edgecolor="white", lw=0.5, zorder=3)
        elif t == "hawkish":    # aşağı kırmızı ok, fiyatın üstüne
            ax.scatter(date, price + off, marker="v", s=90,
                       color=TONE_COLOR[t], edgecolor="white", lw=0.5, zorder=3)
        else:                    # nötr gri nokta
            ax.scatter(date, price, marker="o", s=28,
                       color=TONE_COLOR[t], edgecolor="white", lw=0.5, zorder=3)

    # legend
    from matplotlib.lines import Line2D
    handles = [
        Line2D([0], [0], marker="^", color="w", markerfacecolor=TONE_COLOR["dovish"],
               markersize=11, label="Güvercin (dovish) — altın ↑ beklenir"),
        Line2D([0], [0], marker="v", color="w", markerfacecolor=TONE_COLOR["hawkish"],
               markersize=11, label="Şahin (hawkish) — altın ↓ beklenir"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=TONE_COLOR["neutral"],
               markersize=9, label="Nötr"),
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=9, framealpha=0.9)

    ax.set_title("Altın (GC=F) fiyatı üzerinde FOMC açıklama tonu\n"
                 "Ok yönü = açıklamanın tonu (güvercin ↑ / şahin ↓)",
                 fontsize=13, fontweight="bold")
    ax.set_ylabel("USD / ons")
    ax.grid(True, alpha=0.2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    fig.autofmt_xdate(rotation=30)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "fomc_tone_gold.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def build_and_get_path() -> str:
    """Menü çubuğu için: grafiği üretip PNG yolunu döndürür (konsol çıktısı yok)."""
    close, tone = load()
    return make_chart(close, tone)


def main() -> None:
    close, tone = load()
    df = forward_returns(close, tone)
    df.to_csv(PROC / "fomc_tone_returns.csv", index=False)
    print(correlation_report(df))
    path = make_chart(close, tone)
    print(f"\nGrafik: {Path(path).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
