"""
FOMC açıklamalarını çekme modülü — Altın Al-Sat Agent, Aşama 3 (Fed katmanı).

Kaynak: federalreserve.gov (FRED bu ortamdan engelli olduğu için tek kaynak buradan).

Yaptığı:
  1) FOMC takvim sayfasından tüm açıklama tarihlerini bulur (monetaryYYYYMMDDa.htm)
  2) Her açıklamanın metnini indirir
  3) Metinden politika faizi hedef aralığını (alt/üst %) ayrıştırır
  4) Ardışık toplantıları karşılaştırıp karar yönünü çıkarır (artış/sabit/indirim)

Çıktılar:
  - data/raw/fomc/statements/<YYYYMMDD>.txt   (ham metin)
  - data/raw/fomc_events.(parquet|csv)         (tarih, url, hedef alt/üst, değişim, yön)

Kullanım:
    python src/fetch_fomc.py
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
TXT_DIR = RAW / "fomc" / "statements"

CAL_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
STMT_URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary{date}a.htm"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# "4-1/4", "1/2", "0" gibi ifadeleri ondalığa çevir
_FRAC = {"1/4": 0.25, "1/2": 0.5, "3/4": 0.75}


def _to_float(tok: str) -> float | None:
    tok = tok.strip()
    if not tok:
        return None
    # "4-1/4"  ->  4 + 0.25
    m = re.match(r"^(\d+)-(\d/\d)$", tok)
    if m:
        return int(m.group(1)) + _FRAC.get(m.group(2), 0.0)
    if tok in _FRAC:  # "1/4"
        return _FRAC[tok]
    if re.match(r"^\d+$", tok):  # "0", "5"
        return float(tok)
    return None


def parse_target_range(text: str) -> tuple[float | None, float | None]:
    """
    'target range for the federal funds rate ... 4-1/4 to 4-1/2 percent' → (4.25, 4.5)
    Faiz kararı içermeyen (ör. sadece bilanço) açıklamalarda (None, None) döner.
    """
    text = normalize(text)
    # esnek desen: "range for the federal funds rate at/to X to Y percent"
    pat = re.compile(
        r"target range for the federal funds rate[^.]*?"
        r"(?:at|to)\s+([\d/\- ]+?)\s+to\s+([\d/\- ]+?)\s+percent",
        re.IGNORECASE,
    )
    m = pat.search(text)
    if not m:
        return None, None
    lo = _to_float(m.group(1))
    hi = _to_float(m.group(2))
    return lo, hi


# Fed metinlerinde geçen özel tire/çizgi karakterleri → ASCII "-"
#   U+2011 kırılmaz tire, U+2012-2015 çizgiler, U+2212 eksi
_DASHES = dict.fromkeys([0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212], "-")


def normalize(text: str) -> str:
    return text.translate(_DASHES)


def _get(url: str, tries: int = 4) -> requests.Response:
    """UTF-8 zorlayan, geçici SSL/ağ hatalarında yeniden deneyen GET."""
    last = None
    for attempt in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            r.encoding = "utf-8"  # sunucu charset vermiyor → Latin-1 mojibake'i engelle
            return r
        except Exception as e:  # SSLError dahil geçici hatalar
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def get_statement_dates() -> list[str]:
    r = _get(CAL_URL)
    dates = sorted(set(re.findall(r"/newsevents/pressreleases/monetary(\d{8})a\.htm", r.text)))
    return dates


def fetch_statement_text(date: str) -> str:
    r = _get(STMT_URL.format(date=date))
    soup = BeautifulSoup(r.text, "lxml")
    # ana içerik paragrafları
    paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    # kısa/boş ve navigasyon paragraflarını at
    paras = [p for p in paras if len(p) > 40]
    return normalize("\n\n".join(paras))


def main() -> None:
    TXT_DIR.mkdir(parents=True, exist_ok=True)
    dates = get_statement_dates()
    print(f"[FOMC] {len(dates)} açıklama tarihi bulundu ({dates[0]} → {dates[-1]})")

    rows = []
    for i, d in enumerate(dates, 1):
        txt_path = TXT_DIR / f"{d}.txt"
        if txt_path.exists():
            text = txt_path.read_text()
        else:
            try:
                text = fetch_statement_text(d)
                txt_path.write_text(text)
                time.sleep(0.5)  # sunucuya nazik ol
            except Exception as e:
                print(f"  ! {d} indirilemedi: {type(e).__name__}")
                continue
        lo, hi = parse_target_range(text)
        rows.append({
            "date": pd.to_datetime(d, format="%Y%m%d"),
            "url": STMT_URL.format(date=d),
            "target_lower": lo,
            "target_upper": hi,
            "has_rate_decision": lo is not None,
            "text_len": len(text),
        })
        flag = f"{lo}-{hi}%" if lo is not None else "(karar yok)"
        print(f"  [{i:>2}/{len(dates)}] {d}  {flag}")

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    # karar yönü: bir önceki KARAR içeren toplantının üst hedefiyle karşılaştır
    dec = df[df["has_rate_decision"]].copy()
    dec["prev_upper"] = dec["target_upper"].shift(1)
    dec["change_bps"] = ((dec["target_upper"] - dec["prev_upper"]) * 100).round(0)
    dec["direction"] = dec["change_bps"].apply(
        lambda x: "hike" if x > 0 else ("cut" if x < 0 else "hold")
    )
    df = df.merge(dec[["date", "change_bps", "direction"]], on="date", how="left")

    out_pq = RAW / "fomc_events.parquet"
    out_csv = RAW / "fomc_events.csv"
    df.to_parquet(out_pq)
    df.to_csv(out_csv, index=False)

    print("\n=== ÖZET ===")
    print(f"Toplam olay      : {len(df)}")
    print(f"Faiz kararı olan : {int(df['has_rate_decision'].sum())}")
    vc = df["direction"].value_counts(dropna=True)
    print("Yön dağılımı     :", vc.to_dict())
    print(f"Kayıt: {out_pq.relative_to(ROOT)} & {out_csv.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
