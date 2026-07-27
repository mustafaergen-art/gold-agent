# Veri klasörü

Piyasa verisi (Yahoo Finance türevi) ve yeniden üretilebilir çıktılar bu depoya
**dahil değildir** (lisans/telif nedeniyle). Aşağıdaki script'lerle yeniden üretilir:

```bash
python src/fetch_prices.py    # altın günlük+saatlik  → data/raw/gold_*
python src/fetch_macro.py     # DXY, 10Y faiz          → data/raw/dxy.parquet, tnx.parquet
python src/fetch_fomc.py      # FOMC açıklama metinleri → data/raw/fomc/statements/*
python src/fetch_cpi.py       # BLS CPI (gerçek)        → data/raw/cpi_actual.csv
python src/fomc_tone.py       # sözlük tonu            → data/processed/fomc_tone.csv
python src/analyze_fomc_gold.py
python src/analyze_cpi_gold.py
python src/compare_tone.py
python src/clean_prices.py
python src/signal_engine.py   # karar motoru + backtest
python src/walk_forward.py    # validasyon
```

## Depoya dahil edilen istisnalar

Bu iki dosya script'le yeniden üretilemez (LLM/araştırma çıktısı, Yahoo verisi değil),
bu yüzden depoda tutulur:

- `raw/cpi_release_dates.csv` — CPI yayın tarihleri + konsensüs (araştırmayla derlendi)
- `processed/fomc_tone_llm.csv` — FOMC açıklamalarının LLM ile şahin/güvercin skorları
