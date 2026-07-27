"""
Altın grafiği üretici — menü çubuğu uygulaması için.

Seçilen döneme göre canlı GC=F verisini Yahoo'dan çeker, PNG grafik üretir
ve dosya yolunu döndürür. menubar.py bu PNG'yi `open` ile açar.

Dönemler: günlük / aylık / yıllık / 5 yıllık
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # GUI'siz backend — rumps event loop'u ile çakışmaz
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt     # noqa: E402
import requests                     # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "charts"
HEADERS = {"User-Agent": "Mozilla/5.0"}
GOLD = "#C8A100"

# dönem -> (Yahoo range, interval, başlık, tarih biçimi)
PERIODS: dict[str, tuple[str, str, str, str]] = {
    "günlük":   ("1d",  "5m",  "Bugün (5 dakikalık)",      "%H:%M"),
    "aylık":    ("1mo", "1d",  "Son 1 Ay (günlük)",         "%d %b"),
    "yıllık":   ("1y",  "1d",  "Son 1 Yıl (günlük)",        "%b %y"),
    "5 yıllık": ("5y",  "1wk", "Son 5 Yıl (haftalık)",      "%Y"),
}


def fetch_series(rng: str, interval: str) -> tuple[list[dt.datetime], list[float]]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval={interval}&range={rng}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    xs = [dt.datetime.fromtimestamp(t) for t, c in zip(ts, closes) if c is not None]
    ys = [float(c) for c in closes if c is not None]
    return xs, ys


def make_chart(period: str) -> str:
    if period not in PERIODS:
        raise ValueError(f"bilinmeyen dönem: {period}")
    rng, interval, subtitle, datefmt = PERIODS[period]
    xs, ys = fetch_series(rng, interval)
    if not ys:
        raise RuntimeError("veri boş döndü")

    first, last = ys[0], ys[-1]
    chg = (last / first - 1) * 100
    up = last >= first
    line_color = "#1a9850" if up else "#d73027"  # yükseliş yeşil / düşüş kırmızı

    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=130)
    ax.plot(xs, ys, color=line_color, lw=1.7)
    ax.fill_between(xs, ys, min(ys), color=line_color, alpha=0.08)

    ax.set_title(
        f"Altın (GC=F) — {subtitle}\n"
        f"Son: {last:,.1f} $   Dönem değişimi: {chg:+.2f} %",
        fontsize=12, fontweight="bold",
    )
    ax.set_ylabel("USD / ons")
    ax.grid(True, alpha=0.25)
    ax.xaxis.set_major_formatter(mdates.DateFormatter(datefmt))
    fig.autofmt_xdate(rotation=30)
    # son fiyatı işaretle
    ax.scatter([xs[-1]], [last], color=line_color, zorder=5, s=25)
    ax.annotate(f"{last:,.1f}", (xs[-1], last),
                textcoords="offset points", xytext=(-10, 8),
                fontsize=10, fontweight="bold", color=line_color, ha="right")

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"gold_{period.replace(' ', '_')}.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return str(path)


if __name__ == "__main__":
    for p in PERIODS:
        print(p, "->", make_chart(p))
