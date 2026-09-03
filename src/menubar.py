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

SYMBOL = "GC=F"           # altın: vadeli (spot anahtar yoksa yedek)
SPACEX_SYMBOL = "SPCX"    # SpaceX (Nasdaq)
BTC_SYMBOL = "BTC-USD"    # Bitcoin (Yahoo)
REFRESH_SECONDS = 30      # fiyat yenileme aralığı
BLINK_SECONDS = 0.6       # alarm anında yanıp-sönme hızı
DEFAULT_ALARM = 4300.0    # ilk kurulumdaki varsayılan alarm eşiği

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.json"
TICKER_FILE = Path("/tmp/gold_ticker.txt")  # Touch Bar (MTMR) bu dosyayı okur
CMD_FILE = Path("/tmp/gold_cmd.txt")        # Touch Bar dokunuşu buraya komut yazar

QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d"
METALS_DEV_URL = "https://api.metals.dev/v1/latest?api_key={key}&currency=USD&unit=toz"
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


def fetch_spot_gold(api_key: str) -> float | None:
    """Metals.Dev'den gerçek spot XAU/USD (TradingView ile eşleşir). Hata → None."""
    try:
        r = requests.get(METALS_DEV_URL.format(key=api_key), timeout=10)
        r.raise_for_status()
        j = r.json()
        price = (j.get("metals") or {}).get("gold")
        return float(price) if price else None
    except Exception:
        return None


def _config() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except Exception:
        return {}


def _save_config(**updates) -> None:
    cfg = _config()
    cfg.update(updates)
    CONFIG.write_text(json.dumps(cfg, indent=2))


def metals_dev_key() -> str:
    return str(_config().get("metals_dev_key", "")).strip()


def load_bounds(key: str) -> dict:
    """Alarm sınırları: {'min': float|None, 'max': float|None}.
    Eski tek-eşik formatlarından otomatik geçirir (alarm_above / value+dir)."""
    cfg = _config()
    a = cfg.get(key)
    out = {"min": None, "max": None}
    try:
        if isinstance(a, dict) and ("min" in a or "max" in a):
            out["min"] = float(a["min"]) if a.get("min") is not None else None
            out["max"] = float(a["max"]) if a.get("max") is not None else None
        elif isinstance(a, dict) and "value" in a:  # eski {'value','dir'} formatı
            if a.get("dir") == "below":
                out["min"] = float(a["value"])
            else:
                out["max"] = float(a["value"])
        elif key == "gold_alarm" and "alarm_above" in cfg:  # en eski altın formatı
            out["max"] = float(cfg["alarm_above"])
    except Exception:
        pass
    return out


def bounds_hit(price: float | None, b: dict | None) -> bool:
    """Fiyat max'ın üstünde ya da min'in altındaysa True."""
    if price is None or not b:
        return False
    if b.get("max") is not None and price >= b["max"]:
        return True
    if b.get("min") is not None and price <= b["min"]:
        return True
    return False


def prompt_text(title: str, message: str, default_text: str = "") -> str | None:
    """Öne gelen, odaklı bir giriş kutusu açar (osascript). İptalde None döner."""
    script = (
        f'display dialog "{message}" '
        f'with title "{title}" '
        f'default answer "{default_text}" '
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
        self.gold_alarm = load_bounds("gold_alarm")     # {'min','max'}
        self.spacex_alarm = load_bounds("spacex_alarm")
        self.btc_alarm = load_bounds("btc_alarm")
        self.last_price: float | None = None
        self.last_spacex_price: float | None = None
        self.last_btc_price: float | None = None
        self.last_text = "🥇 …"
        self._blink_on = False  # yanıp-sönmede o anki faz
        self.signal_badge = ""  # başlıkta gösterilecek AL/TUT/SAT rozeti

        self.item_signal = rumps.MenuItem("📍 Sinyal: —", callback=self.on_recompute_signal)
        self.item_signal_detail = rumps.MenuItem("   (hesaplanıyor…)")
        self.item_change = rumps.MenuItem("Değişim: —")
        self.item_prev = rumps.MenuItem("Önceki kapanış: —")
        self.item_range = rumps.MenuItem("Gün aralığı: —")
        self.item_source = rumps.MenuItem("Kaynak: —")
        self.item_spacex = rumps.MenuItem("🚀 SpaceX (SPCX): —")
        self.item_alarm = rumps.MenuItem(
            self._bounds_title("Altın", self.gold_alarm), callback=self.on_set_alarm)
        self.item_spacex_alarm = rumps.MenuItem(
            self._bounds_title("SpaceX", self.spacex_alarm),
            callback=self.on_set_spacex_alarm)
        self.item_btc = rumps.MenuItem("₿ Bitcoin (BTC/USD): —")
        self.item_btc_alarm = rumps.MenuItem(
            self._bounds_title("Bitcoin", self.btc_alarm),
            callback=self.on_set_btc_alarm)
        self.item_updated = rumps.MenuItem("Güncelleme: —")

        # 📈 Grafik alt menüsü — dönem seç
        chart_menu = rumps.MenuItem("📈 Grafik")
        for label, period in [("Günlük", "günlük"), ("Aylık", "aylık"),
                              ("Yıllık", "yıllık"), ("5 Yıllık", "5 yıllık")]:
            chart_menu.add(rumps.MenuItem(
                label, callback=functools.partial(self.on_chart, period=period)))

        # 🚀 SpaceX grafik alt menüsü — günlük / aylık
        spacex_menu = rumps.MenuItem("🚀 SpaceX Grafik")
        for label, period in [("Günlük", "günlük"), ("Aylık", "aylık")]:
            spacex_menu.add(rumps.MenuItem(
                label, callback=functools.partial(self.on_spacex_chart, period=period)))

        # ₿ Bitcoin grafik alt menüsü — günlük / aylık
        btc_menu = rumps.MenuItem("₿ Bitcoin Grafik")
        for label, period in [("Günlük", "günlük"), ("Aylık", "aylık")]:
            btc_menu.add(rumps.MenuItem(
                label, callback=functools.partial(self.on_btc_chart, period=period)))

        self.menu = [
            self.item_signal,
            self.item_signal_detail,
            None,
            self.item_change,
            self.item_prev,
            self.item_range,
            self.item_source,
            None,
            self.item_spacex,
            spacex_menu,
            self.item_spacex_alarm,
            None,
            self.item_btc,
            btc_menu,
            self.item_btc_alarm,
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
        # Touch Bar dokunuş komutlarını dinle (1 sn)
        self.cmd_timer = rumps.Timer(self.check_command, 1.0)
        self.cmd_timer.start()

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

    def on_spacex_chart(self, _, period: str):
        """SpaceX (SPCX) grafiğini üretip Önizleme'de açar."""
        try:
            path = chart.make_chart(period, symbol=SPACEX_SYMBOL,
                                    label="SpaceX (SPCX)", slug="spcx",
                                    unit="USD", alarm=self.spacex_alarm)
            subprocess.run(["open", path], check=False)
        except Exception as e:
            rumps.alert(title="SpaceX grafik hatası", message=str(e)[:150])

    @staticmethod
    def _bounds_title(name: str, b: dict) -> str:
        mn = f"{b['min']:,.0f}" if b.get("min") else "—"
        mx = f"{b['max']:,.0f}" if b.get("max") else "—"
        return f"🔔 {name} alarmı… (min {mn} / max {mx} $)"

    def _alarm_flow(self, name: str, bounds: dict) -> dict | None:
        """İki adımlı min/max alarm girişi. İptal edilirse None (değişiklik yok)."""
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        mx_txt = prompt_text(
            f"{name} Alarmı — 1/2: ÜST (max)",
            "ÜST alarm (USD): fiyat bu değerin ÜSTÜNE çıkınca alarm çalar.\n"
            "Boş bırak = üst alarm yok.",
            f"{bounds['max']:.0f}" if bounds.get("max") else "")
        if mx_txt is None:
            return None
        mn_txt = prompt_text(
            f"{name} Alarmı — 2/2: ALT (min)",
            "ALT alarm (USD): fiyat bu değerin ALTINA inince alarm çalar.\n"
            "Boş bırak = alt alarm yok.",
            f"{bounds['min']:.0f}" if bounds.get("min") else "")
        if mn_txt is None:
            return None

        def parse(t: str) -> float | None:
            t = t.strip().replace("$", "").replace(",", ".")
            if not t or t in ("-", "yok", "0"):
                return None
            v = float(t)
            if v <= 0:
                raise ValueError
            return v

        try:
            new = {"max": parse(mx_txt), "min": parse(mn_txt)}
        except ValueError:
            rumps.alert(title="Geçersiz değer",
                        message="Sayı girilmedi; alarm değişmedi.")
            return None
        if new["min"] is not None and new["max"] is not None and new["min"] >= new["max"]:
            rumps.alert(title="Geçersiz aralık",
                        message="Min, max'tan küçük olmalı; alarm değişmedi.")
            return None
        return new

    def on_set_spacex_alarm(self, _):
        new = self._alarm_flow("SpaceX (SPCX)", self.spacex_alarm)
        if new is None:
            return
        self.spacex_alarm = new
        _save_config(spacex_alarm=new)
        self.item_spacex_alarm.title = self._bounds_title("SpaceX", new)
        self._render()

    def on_btc_chart(self, _, period: str):
        """Bitcoin (BTC/USD) grafiğini üretip Önizleme'de açar."""
        try:
            path = chart.make_chart(period, symbol=BTC_SYMBOL,
                                    label="Bitcoin (BTC/USD)", slug="btc",
                                    unit="USD", alarm=self.btc_alarm)
            subprocess.run(["open", path], check=False)
        except Exception as e:
            rumps.alert(title="Bitcoin grafik hatası", message=str(e)[:150])

    def on_set_btc_alarm(self, _):
        new = self._alarm_flow("Bitcoin (BTC/USD)", self.btc_alarm)
        if new is None:
            return
        self.btc_alarm = new
        _save_config(btc_alarm=new)
        self.item_btc_alarm.title = self._bounds_title("Bitcoin", new)
        self._render()

    # ---- Touch Bar dokunuş menüsü ----
    def check_command(self, _):
        """Touch Bar tap'inin yazdığı komut dosyasını işler (1 sn'de bir)."""
        try:
            if not CMD_FILE.exists():
                return
            cmd = CMD_FILE.read_text().strip()
            CMD_FILE.unlink(missing_ok=True)
            if cmd == "menu":
                self.touchbar_menu()
        except Exception:
            pass

    def touchbar_menu(self):
        """Touch Bar'dan açılan seçim menüsü → grafik veya alarm formu."""
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        script = (
            'choose from list {'
            '"🥇 Altın Grafik (Aylık)","🚀 SpaceX Grafik (Aylık)","₿ Bitcoin Grafik (Aylık)",'
            '"🔔 Altın Alarmı","🔔 SpaceX Alarmı","🔔 Bitcoin Alarmı"} '
            'with title "Altın Agent" with prompt "Ne açılsın?" '
            'OK button name "Aç" cancel button name "Vazgeç"'
        )
        try:
            out = subprocess.run(["osascript", "-e", script],
                                 capture_output=True, text=True, timeout=120)
            choice = out.stdout.strip()
        except Exception:
            return
        if not choice or choice == "false":
            return
        if "Altın Grafik" in choice:
            self.on_chart(None, period="aylık")
        elif "SpaceX Grafik" in choice:
            self.on_spacex_chart(None, period="aylık")
        elif "Bitcoin Grafik" in choice:
            self.on_btc_chart(None, period="aylık")
        elif "Altın Alarmı" in choice:
            self.on_set_alarm(None)
        elif "SpaceX Alarmı" in choice:
            self.on_set_spacex_alarm(None)
        elif "Bitcoin Alarmı" in choice:
            self.on_set_btc_alarm(None)

    def on_recompute_signal(self, _):
        self.update_signal(None)

    def update_signal(self, _):
        """Karar motorundan güncel AL/TUT/SAT sinyalini alıp menü + rozeti günceller."""
        try:
            s = signal_engine.latest_signal()
            self.signal_badge = f" {s['emoji']}{s['label']}"
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
        new = self._alarm_flow("Altın", self.gold_alarm)
        if new is None:
            return
        self.gold_alarm = new
        _save_config(gold_alarm=new)
        self.item_alarm.title = self._bounds_title("Altın", new)
        self._render()

    # ---- görsel güncelleme ----
    def _gold_in_alarm(self) -> bool:
        return bounds_hit(self.last_price, self.gold_alarm)

    def _spacex_in_alarm(self) -> bool:
        return bounds_hit(self.last_spacex_price, self.spacex_alarm)

    def _btc_in_alarm(self) -> bool:
        return bounds_hit(self.last_btc_price, self.btc_alarm)

    def _in_alarm(self) -> bool:
        return self._gold_in_alarm() or self._spacex_in_alarm() or self._btc_in_alarm()

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

            # Metals.Dev anahtarı varsa gerçek spot XAU/USD göster (TradingView ile eşleşir)
            key = metals_dev_key()
            spot = fetch_spot_gold(key) if key else None
            if spot:
                shown, src = spot, "Spot XAU/USD (Metals.Dev)"
            else:
                shown, src = price, "COMEX vadeli GC=F (Yahoo)" + (" — spot alınamadı" if key else "")
            self.last_price = shown  # alarm gösterilen fiyata göre
            self.item_source.title = f"Kaynak: {src}"

            # menü çubuğu alanı dar (çentik!) → başlık kompakt tutulur
            if prev and not spot:
                diff = price - prev
                pct = diff / prev * 100
                arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "▬")
                self.last_text = f"🥇{shown:,.0f}{arrow}{abs(pct):.1f}%"
                self.item_change.title = f"Değişim: {arrow} {diff:+.1f} $ ({pct:+.2f}%)"
                self.item_prev.title = f"Önceki kapanış: {prev:,.1f} $"
            else:
                self.last_text = f"🥇{shown:,.0f}"
                self.item_change.title = (f"Vadeli GC=F: {price:,.1f} $" if spot
                                          else "Değişim: —")
                self.item_prev.title = (f"Önceki kapanış (GC=F): {prev:,.1f} $"
                                        if prev else "Önceki kapanış: —")

            self.last_text += self.signal_badge  # · 🔴SAT gibi rozet

            if q["high"] and q["low"]:
                self.item_range.title = f"Gün aralığı: {q['low']:,.1f} – {q['high']:,.1f} $"

            # 🚀 SpaceX (SPCX)
            try:
                s = fetch_quote(SPACEX_SYMBOL)
                sp, spv = s["price"], s["prev"]
                self.last_spacex_price = sp  # SpaceX alarmı bu fiyata bakar
                if sp and spv:
                    spct = (sp / spv - 1) * 100
                    sarr = "▲" if spct > 0 else ("▼" if spct < 0 else "▬")
                    self.last_text += f" 🚀{sp:,.0f}{sarr}{abs(spct):.0f}%"
                    self.item_spacex.title = f"🚀 SpaceX (SPCX): {sp:,.2f} $  {sarr} {spct:+.2f}%"
                elif sp:
                    self.last_text += f" 🚀{sp:,.0f}"
                    self.item_spacex.title = f"🚀 SpaceX (SPCX): {sp:,.2f} $"
            except Exception:
                self.item_spacex.title = "🚀 SpaceX (SPCX): veri alınamadı"

            # ₿ Bitcoin (BTC/USD) — başlıkta bin$ cinsinden kompakt (₿77k▼1%)
            try:
                b = fetch_quote(BTC_SYMBOL)
                bp, bpv = b["price"], b["prev"]
                self.last_btc_price = bp  # BTC alarmı bu fiyata bakar
                if bp and bpv:
                    bpct = (bp / bpv - 1) * 100
                    barr = "▲" if bpct > 0 else ("▼" if bpct < 0 else "▬")
                    self.last_text += f" ₿{bp/1000:,.0f}k{barr}{abs(bpct):.0f}%"
                    self.item_btc.title = f"₿ Bitcoin (BTC/USD): {bp:,.0f} $  {barr} {bpct:+.2f}%"
                elif bp:
                    self.last_text += f" ₿{bp/1000:,.0f}k"
                    self.item_btc.title = f"₿ Bitcoin (BTC/USD): {bp:,.0f} $"
            except Exception:
                self.item_btc.title = "₿ Bitcoin (BTC/USD): veri alınamadı"

            now = dt.datetime.now().strftime("%H:%M:%S")
            alarms = []
            if self._gold_in_alarm():
                alarms.append("🥇 ALTIN")
            if self._spacex_in_alarm():
                alarms.append("🚀 SPCX")
            if self._btc_in_alarm():
                alarms.append("₿ BTC")
            state = "🔴 ALARM: " + "+".join(alarms) if alarms else "izliyor"
            self.item_updated.title = f"Güncelleme: {now} · {state}"
        except Exception as e:  # ağ/parse hatası → çökme, sadece uyarı
            self.last_text = "🥇 ⚠️"
            self.item_updated.title = f"Hata: {str(e)[:40]}"
        self._render()
        # Touch Bar (MTMR) için aynı metni dosyaya yaz; alarmda 🔴 öne gelir
        try:
            txt = ("🔴 " if self._in_alarm() else "") + self.last_text
            TICKER_FILE.write_text(txt)
        except Exception:
            pass


if __name__ == "__main__":
    GoldBarApp().run()
