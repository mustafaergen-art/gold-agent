# Altın Al-Sat Agent

Altın (XAU) fiyat hareketleri + makro haber akışını analiz ederek al/sat kararı öneren agent projesi.

> ⚠️ **Feragatname:** Bu bir araştırma/eğitim prototipidir, **yatırım tavsiyesi değildir**. Geçmiş performans gelecek getiriyi garanti etmez.
>
> 📊 **Veri depoda yok:** Piyasa verisi (Yahoo Finance türevi) telif/lisans nedeniyle depoya dahil edilmez; `src/fetch_*.py` script'leriyle yeniden üretilir. Bkz. [data/README.md](data/README.md).

## Durum

| Aşama | Durum |
|------|-------|
| 1. Fiyat verisi (günlük 5y + saatlik) | ✅ Tamam |
| 1b. Menü çubuğu anlık fiyat göstergesi | ✅ Tamam |
| 2. Veri kalite kontrolü (hatalı tik) | ✅ Tamam — close temiz, 0 spike |
| 3a. FOMC kararları çekme + ayrıştırma | ✅ Tamam (44 karar, 2021–2026) |
| 3b. FOMC ↔ altın olay analizi (günlük) | ✅ Tamam |
| 3c. FOMC açıklama tonu (şahin/güvercin) + korelasyon | ✅ Tamam |
| 3c-LLM. LLM ton (FinBERT alternatifi) + karşılaştırma | ✅ Tamam |
| 3d. Saatlik intraday tepki (14:00 ET) | ✅ Tamam |
| 4. Haber katmanı #2 — CPI (enflasyon) ↔ altın | ✅ Tamam |
| 5. Karar/sinyal motoru + backtest | ✅ Tamam (v1) |

## Veri

Kaynak: **Yahoo Finance**, enstrüman **`GC=F` (COMEX Gold Futures)** — spot XAU/USD ile ~0.999 korelasyon.
> Not: Spot XAU/USD için asıl kaynak Dukascopy'di; bu ortamın çıkış IP'sinden Dukascopy engelli.
> `src/fetch_prices_dukascopy.py` (opsiyonel) farklı bir ağda çalıştırılırsa 5 yıllık saatlik spot çekilebilir.

`data/raw/` içinde:
- `gold_daily.(parquet|csv)` — günlük OHLCV, ~5 yıl (2021-07 → günümüz)
- `gold_hourly.(parquet|csv)` — saatlik OHLCV, ~2.4 yıl (Yahoo intraday limiti ~730 gün), zaman UTC

## Kurulum

```bash
source ../.venv/bin/activate
pip install -r requirements.txt
```

## Kullanım

```bash
python src/fetch_prices.py                 # GC=F günlük 5y + saatlik max
python src/fetch_prices.py --years 5        # yıl sayısını değiştir
```

### Menü çubuğu anlık gösterge (macOS üst bar)

```bash
python src/menubar.py                       # ön planda
nohup python src/menubar.py >/tmp/gold_menubar.log 2>&1 &   # arka planda
```

Menü çubuğunda `🥇 4158.3 ▲+0.79%` şeklinde görünür; her 30 sn'de bir yenilenir.
Simgeye tıkla → değişim / önceki kapanış / gün aralığı / son güncelleme + Çıkış.

**Çoklu varlık:** Menü çubuğu altınla birlikte **🚀 SpaceX (SPCX)** ve **₿ Bitcoin (BTC-USD)** fiyatlarını da gösterir (kompakt: `🥇4,417▼1.4% 🔴SAT 🚀143▼1% ₿78k▼1%`). Her varlığın menüde detay satırı ve Günlük/Aylık grafik alt menüsü vardır.

**Alarm (min/max):** Her varlık için ayrı — menüden "🔔 … alarmı" → iki adımda ÜST (max) ve ALT (min) eşik gir (boş bırak = o taraf kapalı). Fiyat max'ın üstüne çıkınca **veya** min'in altına inince yazı **kırmızı yanıp söner**; grafiklerde min/max çizgileri görünür. `config.json`'a kaydedilir.

**Grafik:** 🥇 → "📈 Grafik" → Günlük / Aylık / Yıllık / 5 Yıllık. Seçilen dönemin grafiği ([chart.py](src/chart.py), canlı Yahoo verisi) Önizleme'de açılır.

**Touch Bar (opsiyonel):** Touch Bar'lı MacBook'ta [MTMR](https://github.com/Toxblh/MTMR) (`brew install --cask mtmr`) ile fiyat şeridi klavye üstü ekranda da gösterilir: app her yenilemede `/tmp/gold_ticker.txt` yazar, MTMR [touchbar_ticker.sh](src/touchbar_ticker.sh) ile okur (script'i `~/Library/Application Support/MTMR/` altına kopyala — Documents TCC engeline takılır). `items.json` örneği: `shellScriptTitledButton` + `refreshInterval: 15`.

**Fed Ton Analizi:** 🥇 → "📊 Fed Ton Analizi" → altın fiyatı üzerinde FOMC açıklama tonu okları (güvercin ↑ yeşil / şahin ↓ kırmızı). Üretim: [chart_fomc.py](src/chart_fomc.py), ton skoru [fomc_tone.py](src/fomc_tone.py).

## Fed ton ↔ altın korelasyonu (bulgu)

Ton skoru (+ şahin / − güvercin) ile açıklama sonrası altın getirisi:

| Pencere | Pearson | Spearman |
|--------|--------:|---------:|
| 1 gün | +0.05 | +0.02 |
| 1 hafta | −0.07 | −0.14 |
| **1 ay** | **−0.26** | **−0.31** |

Negatif korelasyon = güvercin ton → altın ↑ (teoriyle uyumlu), etki **1 aylık** pencerede belirginleşiyor. Ton grubuna göre 1 aylık ortalama getiri: **güvercin +3.13%**, nötr +1.20%, şahin +1.12%.

Saatlik intraday (14:00 ET, 19 karar): anlık tepki ≈ 0 (piyasa önceden fiyatlıyor). LLM tonu (compare_tone.py) sözlüğü tahminde geçmedi (1-ay LLM −0.17 vs sözlük −0.26).

## CPI (enflasyon) ↔ altın (haber katmanı #2)

CPI sürprizi (gerçek − konsensüs) ile altın tepkisi (59 yayın, 52 konsensüslü):

| Pencere | Pearson | Spearman |
|--------|--------:|---------:|
| **Yayın günü** | **−0.21** | **−0.21** |
| +5 gün | −0.09 | −0.08 |

Negatif = **sıcak CPI → altın ↓** (beklenenden yüksek enflasyon → şahin Fed korkusu → güçlü dolar/yüksek faiz → altın ↓). Fed bulgusuyla tutarlı: her ikisi de **para politikası beklentisi** kanalından — gevşeme beklentisi altını yukarı, sıkılaşma beklentisi aşağı taşıyor. CPI etkisi anlık (yayın günü), Fed tonu etkisi ise haftalar içinde birikiyor. Kod: [fetch_cpi.py](src/fetch_cpi.py), [analyze_cpi_gold.py](src/analyze_cpi_gold.py).

## Karar motoru (Aşama 5, v1)

Bileşik sinyal = 0.5·trend + 0.3·Fed_tonu + 0.2·CPI_sürprizi → LONG/FLAT. 5 yıl backtest (GC=F):

| Metrik | Strateji | Al-tut |
|--------|--------:|-------:|
| Toplam getiri | +120% | +132% |
| Yıllık | 17.2% | 18.4% |
| Oynaklık | 15.4% | 18.5% |
| **Sharpe** | **1.12** | 0.99 |
| **Max düşüş** | **−13%** | −25% |

Boğa piyasasında toplam getiriden biraz feragat ediyor ama **riski belirgin azaltıyor** (daha yüksek Sharpe, yarı yarıya düşük max drawdown). Kod: [signal_engine.py](src/signal_engine.py). ⚠️ Araştırma prototipi, yatırım tavsiyesi değildir.

**Sinyaller:** trend (0.35) + DXY dolar endeksi (0.30, [fetch_macro.py](src/fetch_macro.py)) + Fed tonu (0.20) + CPI sürprizi (0.15). DXY eklenince Sharpe 1.12→**1.20**. DXY-altın günlük getiri korelasyonu −0.385 (en güçlü tekil sürücü).

**Walk-forward validasyon** ([walk_forward.py](src/walk_forward.py)): genişleyen-pencere OOS (eşik geçmişten seçilir, 753 gün görülmemiş) → Sharpe **1.51 vs al-tut 1.36**, max düşüş −13% vs −25%. Eşik 0.0–0.25 boyunca Sharpe hep >0.99 (sağlam, overfit değil). Strateji çalkantı/düşüş rejimlerinde kazanıyor, güçlü boğada geride kalıyor.

**Canlı sinyal (menü çubuğu):** 🥇 fiyatın yanında **· 🟢AL / ⚪TUT / 🔴SAT** rozeti; açılır menüde sinyal bileşenleri. 30 dk'da bir güncellenir. Güncel: 🔴 SAT (skor −0.44, trend baskın).

#### Her açılışta otomatik başlat (LaunchAgent)

Kurulu: `~/Library/LaunchAgents/com.goldagent.menubar.plist` (RunAtLoad + KeepAlive).

```bash
launchctl load   ~/Library/LaunchAgents/com.goldagent.menubar.plist   # aç
launchctl unload ~/Library/LaunchAgents/com.goldagent.menubar.plist   # kapat
launchctl list | grep goldagent                                       # durum
```
Kaldırmak için: `unload` + plist dosyasını sil. Loglar: `/tmp/gold_menubar.log`, `/tmp/gold_menubar.err`.

## Yapı

```
gold-agent/
├── data/
│   ├── raw/          # ham çekilen fiyatlar
│   └── processed/    # temizlenmiş / özellik eklenmiş veri
├── src/
│   └── fetch_prices.py
├── notebooks/
├── requirements.txt
└── README.md
```
