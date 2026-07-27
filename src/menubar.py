"""
macOS menü çubuğu (üst bar) altın fiyatı göstergesi — Altın Al-Sat Agent.

Menü çubuğunda anlık GC=F (altın) fiyatını ve önceki kapanışa göre yüzde
değişimi gösterir; her `REFRESH_SECONDS` saniyede bir günceller.

ALARM: Simgeye tıkla → "Alarm fiyatı belirle" ile bir eşik gir. Fiyat bu
eşiğe ulaşınca (>=) menü çubuğu yazısı KIRMIZI yanıp söner. Eşik config.json'a
kaydedilir, uygulama yeniden başlasa da korunur.

Çalıştırma:
    source ../.venv/bin/activate
    python src/menubar.py

Çıkış: menü çubuğundaki 🥇 simgesine tıkla → Çıkış.
"""
from __future__ import annotations

import datetime as dt
import functools
import json
import os
import subprocess
import sys
from pathlib import Path

import requests
import rumps
from AppKit import NSApplication, NSColor, NSForegroundColorAttributeName
from Foundation import NSAttributedString

# script olarak da (LaunchAgent) paket olarak da import edilebilsin diye
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chart          # noqa: E402
import chart_fomc     # noqa: E402
import signal_engine  # noqa: E402

SYMBOL = "GC=F"
REFRESH_SECONDS = 30      # fiyat yenileme aralığı
BLINK_SECONDS = 0.6       # alarm anında yanıp-sönme hızı
DEFAULT_ALARM = 4300.0    # ilk kurulumdaki varsayılan alarm eşiği

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.json"

QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_quote(symbol: str = SYMBOL) -> dict:
    """Yahoo chart endpoint'inden anlık fiyat özetini döndürür."""
    url = QUOTE_URL.format(sym=symbol)
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    m = r.json()["chart"]["result"][0]["meta"]
    return {
        "price": m.get("regularMarketPrice"),
        "prev": m.get("chartPreviousClose") or m.get("previousClose"),
        "high": m.get("regularMarketDayHigh"),
        "low": m.get("regularMarketDayLow"),
        "currency": m.get("currency", "USD"),
    }


def load_alarm() -> float:
    try:
        return float(json.loads(CONFIG.read_text())["alarm_above"])
    except Exception:
        return DEFAULT_ALARM


def save_alarm(value: float) -> None:
    CONFIG.write_text(json.dumps({"alarm_above": value}, indent=2))


def prompt_number(default: float) -> str | None:
    """Öne gelen, odaklı bir giriş kutusu açar (osascript). İptalde None döner."""
    script = (
        'display dialog "Alarm fiyatını girin (USD).\n'
        'Fiyat bu değere ulaşınca menü çubuğu kırmızı yanıp söner." '
        'with title "Altın Alarmı" '
        f'default answer "{default:.0f}" '
        'buttons {"İptal", "Kaydet"} default button "Kaydet"\n'
        "return text returned of result"
    )
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120,
        )
        if out.returncode != 0:  # kullanıcı İptal'e bastı
            return None
        return out.stdout.strip()
    except Exception:
        return None


class GoldBarApp(rumps.App):
    def __init__(self):
        super().__init__("🥇 …", quit_button=None)
        self.alarm = load_alarm()
        self.last_price: float | None = None
        self.last_text = "🥇 …"
        self._blink_on = False  # yanıp-sönmede o anki faz
        self.signal_badge = ""  # başlıkta gösterilecek AL/TUT/SAT rozeti

        self.item_signal = rumps.MenuItem("📍 Sinyal: —", callback=self.on_recompute_signal)
        self.item_signal_detail = rumps.MenuItem("   (hesaplanıyor…)")
        self.item_change = rumps.MenuItem("Değişim: —")
        self.item_prev = rumps.MenuItem("Önceki kapanış: —")
        self.item_range = rumps.MenuItem("Gün aralığı: —")
        self.item_alarm = rumps.MenuItem(
            f"🔔 Alarm fiyatı belirle… (şu an: {self.alarm:,.0f} $)",
            callback=self.on_set_alarm,
        )
        self.item_updated = rumps.MenuItem("Güncelleme: —")

        # 📈 Grafik alt menüsü — dönem seç
        chart_menu = rumps.MenuItem("📈 Grafik")
        for label, period in [("Günlük", "günlük"), ("Aylık", "aylık"),
                              ("Yıllık", "yıllık"), ("5 Yıllık", "5 yıllık")]:
            chart_menu.add(rumps.MenuItem(
                label, callback=functools.partial(self.on_chart, period=period)))

        self.menu = [
            self.item_signal,
            self.item_signal_detail,
            None,
            self.item_change,
            self.item_prev,
            self.item_range,
            None,
            chart_menu,
            rumps.MenuItem("📊 Fed Ton Analizi", callback=self.on_fomc_chart),
            self.item_alarm,
            None,
            self.item_updated,
            rumps.MenuItem("Şimdi yenile", callback=self.on_refresh),
            None,
            rumps.MenuItem("Çıkış", callback=rumps.quit_application),
        ]

        self.update_signal(None)  # karar sinyalini hesapla
        self.refresh(None)  # ilk fiyat çekimi
        self.timer = rumps.Timer(self.refresh, REFRESH_SECONDS)
        self.timer.start()
        self.blink_timer = rumps.Timer(self.blink, BLINK_SECONDS)
        self.blink_timer.start()
        # karar sinyali yavaş değişir (günlük veri) → 30 dakikada bir yenile
        self.signal_timer = rumps.Timer(self.update_signal, 1800)
        self.signal_timer.start()

    # ---- kullanıcı eylemleri ----
    def on_refresh(self, _):
        self.refresh(None)

    def on_chart(self, _, period: str):
        """Seçilen dönemin grafiğini üretip Önizleme'de açar."""
        try:
            path = chart.make_chart(period)
            subprocess.run(["open", path], check=False)
        except Exception as e:
            rumps.alert(title="Grafik hatası", message=str(e)[:150])

    def on_recompute_signal(self, _):
        self.update_signal(None)

    def update_signal(self, _):
        """Karar motorundan güncel AL/TUT/SAT sinyalini alıp menü + rozeti günceller."""
        try:
            s = signal_engine.latest_signal()
            self.signal_badge = f" · {s['emoji']}{s['label']}"
            self.item_signal.title = f"📍 Sinyal: {s['emoji']} {s['label']}  (skor {s['composite']:+.2f})"
            self.item_signal_detail.title = (
                f"   trend {s['trend']:+.1f} · dxy {s['dxy']:+.1f} · "
                f"fed {s['fed']:+.1f} · cpi {s['cpi']:+.1f}  [{s['date']}]")
            self._render()  # rozet başlığa yansısın
        except Exception as e:
            self.signal_badge = ""
            self.item_signal.title = "📍 Sinyal: hata"
            self.item_signal_detail.title = f"   {str(e)[:50]}"

    def on_fomc_chart(self, _):
        """Altın fiyatı üzerinde FOMC ton oklarını gösteren analiz grafiğini açar."""
        try:
            path = chart_fomc.build_and_get_path()
            subprocess.run(["open", path], check=False)
        except Exception as e:
            rumps.alert(title="Fed ton grafiği hatası", message=str(e)[:150])

    def on_set_alarm(self, _):
        # menü çubuğu uygulaması arka planda; giriş kutusunu öne getirmek için aktive et
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        text = prompt_number(self.alarm)
        if text is None:  # iptal
            return
        raw = text.strip().replace(",", ".").replace("$", "")
        try:
            val = float(raw)
            if val <= 0:
                raise ValueError
        except ValueError:
            rumps.alert(title="Geçersiz değer", message=f"'{text}' geçerli bir sayı değil.")
            return
        self.alarm = val
        save_alarm(val)
        self.item_alarm.title = f"🔔 Alarm fiyatı belirle… (şu an: {val:,.0f} $)"
        self._render()

    # ---- görsel güncelleme ----
    def _in_alarm(self) -> bool:
        return self.last_price is not None and self.last_price >= self.alarm

    def _render(self):
        """Başlığı, alarm/yanıp-sönme durumuna göre renklendirerek çizer."""
        red = self._in_alarm() and self._blink_on
        try:
            button = self._nsapp.nsstatusitem.button()
        except Exception:
            button = None
        if button is None:
            self.title = self.last_text
            return
        color = NSColor.systemRedColor() if red else NSColor.labelColor()
        attr = NSAttributedString.alloc().initWithString_attributes_(
            self.last_text, {NSForegroundColorAttributeName: color}
        )
        button.setAttributedTitle_(attr)

    def blink(self, _):
        """Alarm halindeyken kırmızı/normal arasında geçiş yaparak yanıp söndürür."""
        if self._in_alarm():
            self._blink_on = not self._blink_on
        else:
            self._blink_on = False
        self._render()

    def refresh(self, _):
        try:
            q = fetch_quote()
            price, prev = q["price"], q["prev"]
            if price is None:
                raise ValueError("fiyat yok")
            self.last_price = price

            if prev:
                diff = price - prev
                pct = diff / prev * 100
                arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "▬")
                self.last_text = f"🥇 {price:,.1f} {arrow}{pct:+.2f}%"
                self.item_change.title = f"Değişim: {arrow} {diff:+.1f} $ ({pct:+.2f}%)"
                self.item_prev.title = f"Önceki kapanış: {prev:,.1f} $"
            else:
                self.last_text = f"🥇 {price:,.1f}"
                self.item_change.title = "Değişim: —"
                self.item_prev.title = "Önceki kapanış: —"

            self.last_text += self.signal_badge  # · 🔴SAT gibi rozet

            if q["high"] and q["low"]:
                self.item_range.title = f"Gün aralığı: {q['low']:,.1f} – {q['high']:,.1f} $"

            now = dt.datetime.now().strftime("%H:%M:%S")
            state = "🔴 ALARM" if self._in_alarm() else "izliyor"
            self.item_updated.title = f"Güncelleme: {now} · {state}"
        except Exception as e:  # ağ/parse hatası → çökme, sadece uyarı
            self.last_text = "🥇 ⚠️"
            self.item_updated.title = f"Hata: {str(e)[:40]}"
        self._render()


if __name__ == "__main__":
    GoldBarApp().run()
