#!/bin/bash
# Touch Bar (MTMR) fiyat şeridi — menü çubuğu app'inin yazdığı dosyayı okur.
# Dosya yoksa (app kapalıysa) bekleme mesajı gösterir.
cat /tmp/gold_ticker.txt 2>/dev/null || echo "🥇 bekleniyor…"
