"""
Altın grafiği üretici — menü çubuğu uygulaması için.

Seçilen döneme göre canlı GC=F verisini Yahoo'dan çeker, PNG grafik üretir
ve dosya yolunu döndürür. menubar.py bu PNG'yi `open` ile açar.

Dönemler: günlük / aylık / yıllık / 5 yıllık
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # GUI'siz backend — rumps event loop'u ile çakışmaz
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt     # noqa: E402
import requests                     # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "charts"
CONFIG = ROOT / "config.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}
GOLD = "#C8A100"
ALARM_COLOR = "#e08a00"


def read_alarm() -> dict:
    """config.json'daki altın alarm sınırlarını {'min','max'} olarak döndürür.
    Yeni format 'gold_alarm'; yoksa eski 'alarm_above' max'a geçirilir."""
    try:
        cfg = json.loads(CONFIG.read_text())
    except Exception:
        return {"min": None, "max": None}
    a = cfg.get("gold_alarm")
    if isinstance(a, dict):
        return {"min": a.get("min"), "max": a.get("max")}
    if "alarm_above" in cfg:
        return {"min": None, "max": cfg["alarm_above"]}
    return {"min": None, "max": None}


def draw_alarm_line(ax, x_left, value: float | dict | None = None) -> None:
    """Grafiğe yatay min/max alarm çizgileri + etiket ekler.
    value: None → altın alarmı config'ten; float → tek max çizgisi; dict → {'min','max'}."""
    if value is None:
        bounds = read_alarm()
    elif isinstance(value, dict):
        bounds = value
    else:
        bounds = {"min": None, "max": float(value)}
    for key, lbl, va in (("max", "Max", "bottom"), ("min", "Min", "top")):
        v = bounds.get(key)
        if not v:
            continue
        ax.axhline(v, color=ALARM_COLOR, ls="--", lw=1.3, alpha=0.9, zorder=4)
        ax.text(x_left, v, f" {lbl} alarm {v:,.0f}$", color=ALARM_COLOR,
                fontsize=9, fontweight="bold", va=va, ha="left", zorder=5)

# dönem -> (Yahoo range, interval, başlık, tarih biçimi)
PERIODS: dict[str, tuple[str, str, str, str]] = {
    "günlük":   ("1d",  "5m",  "Bugün (5 dakikalık)",      "%H:%M"),
    "aylık":    ("1mo", "1d",  "Son 1 Ay (günlük)",         "%d %b"),
    "yıllık":   ("1y",  "1d",  "Son 1 Yıl (günlük)",        "%b %y"),
    "5 yıllık": ("5y",  "1wk", "Son 5 Yıl (haftalık)",      "%Y"),
}


def fetch_series(rng: str, interval: str,
                 symbol: str = "GC=F") -> tuple[list[dt.datetime], list[float]]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={rng}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    xs = [dt.datetime.fromtimestamp(t) for t, c in zip(ts, closes) if c is not None]
    ys = [float(c) for c in closes if c is not None]
    return xs, ys


def make_chart(period: str, symbol: str = "GC=F", label: str = "Altın (GC=F)",
               slug: str = "gold", unit: str = "USD / ons",
               alarm: float | dict | None = None) -> str:
    """Verilen sembol için dönem grafiği üretir; alarm verilirse (float ya da
    {'min','max'}) o çizilir, verilmezse (altın için) config'teki alarm çizilir."""
    if period not in PERIODS:
        raise ValueError(f"bilinmeyen dönem: {period}")
    rng, interval, subtitle, datefmt = PERIODS[period]
    xs, ys = fetch_series(rng, interval, symbol)
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
        f"{label} — {subtitle}\n"
        f"Son: {last:,.1f} $   Dönem değişimi: {chg:+.2f} %",
        fontsize=12, fontweight="bold",
    )
    ax.set_ylabel(unit)
    ax.grid(True, alpha=0.25)
    ax.xaxis.set_major_formatter(mdates.DateFormatter(datefmt))
    fig.autofmt_xdate(rotation=30)
    # son fiyatı işaretle
    ax.scatter([xs[-1]], [last], color=line_color, zorder=5, s=25)
    ax.annotate(f"{last:,.1f}", (xs[-1], last),
                textcoords="offset points", xytext=(-10, 8),
                fontsize=10, fontweight="bold", color=line_color, ha="right")

    # yatay alarm çizgisi (altında varsayılan altın alarmı; başka sembolde verilen değer)
    if symbol == "GC=F" and alarm is None:
        draw_alarm_line(ax, xs[0])
    elif alarm is not None:
        draw_alarm_line(ax, xs[0], alarm)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{slug}_{period.replace(' ', '_')}.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return str(path)


if __name__ == "__main__":
    for p in PERIODS:
        print(p, "->", make_chart(p))
