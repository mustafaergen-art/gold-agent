"""
FOMC açıklama tonu skorlama — Altın Al-Sat Agent, Aşama 3c.

Kaydedilmiş FOMC açıklama metinlerini (data/raw/fomc/statements/*.txt) okur,
sözlük tabanlı bir "şahin (hawkish) − güvercin (dovish)" net ton skoru üretir.

Yöntem: FOMC dili çok kalıplaşmıştır; bu yüzden genel kelimeler ("inflation",
"employment") yerine, toplantıdan toplantıya DEĞİŞEN ayırt edici ifadeler
kullanılır. Oybirliği/muhalefet ("Voting...") paragrafı skordan çıkarılır.

Ton → altın beklentisi:
  güvercin (dovish)  → altın için pozitif  → grafikte YUKARI ok (yeşil)
  şahin   (hawkish)  → altın için negatif  → grafikte AŞAĞI ok (kırmızı)

Çıktı: data/processed/fomc_tone.csv  (date, haw, dov, tone_score, tone)

Kullanım:  python src/fomc_tone.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TXT_DIR = ROOT / "data" / "raw" / "fomc" / "statements"
PROC = ROOT / "data" / "processed"

# ağırlıklı ifadeler (küçük harfe indirgenmiş metinde aranır)
HAWKISH: dict[str, float] = {
    "raise the target range": 2.0,
    "raising the target range": 2.0,
    "ongoing increases": 2.0,
    "additional policy firming": 2.0,
    "policy firming": 1.5,
    "additional increases": 1.5,
    "further increases": 1.5,
    "upside risks to inflation": 1.5,
    "inflation remains elevated": 1.5,
    "overheating": 1.5,
    "elevated inflation": 1.0,
    "upward pressure on inflation": 1.0,
    "highly attentive to inflation": 1.0,
    "attentive to inflation risks": 1.0,
    "more restrictive": 1.0,
    "restrictive stance": 1.0,
    "tightening": 1.0,
    "remains elevated": 1.0,
    "robust": 0.5,
}

DOVISH: dict[str, float] = {
    "lower the target range": 2.0,
    "lowering the target range": 2.0,
    "reduce the target range": 2.0,
    "reducing the target range for the federal funds": 2.0,
    "gained greater confidence": 1.5,
    "gained further confidence": 1.5,
    "recalibrate": 1.5,
    "greater confidence": 1.0,
    "further progress": 1.0,
    "progress on inflation": 1.0,
    "have slowed": 1.0,
    "has slowed": 1.0,
    "softened": 1.0,
    "moderated": 1.0,
    "eased": 1.0,
    "easing": 1.0,
    "downside risks": 1.0,
    "cooling": 1.0,
    "cooled": 1.0,
    "roughly in balance": 0.5,
    "supporting maximum employment": 0.5,
}


def score_text(text: str) -> tuple[float, float]:
    """Metnin şahin ve güvercin toplam ağırlıklarını döndürür."""
    t = text.lower()
    # muhalefet paragrafını at (yanlış 'raise/lower' sayımını önler)
    cut = t.find("voting for the monetary policy action")
    if cut != -1:
        t = t[:cut]
    haw = sum(w * t.count(k) for k, w in HAWKISH.items())
    dov = sum(w * t.count(k) for k, w in DOVISH.items())
    return round(haw, 2), round(dov, 2)


def classify(score: float, thr: float = 1.0) -> str:
    if score >= thr:
        return "hawkish"
    if score <= -thr:
        return "dovish"
    return "neutral"


def build() -> pd.DataFrame:
    rows = []
    for f in sorted(TXT_DIR.glob("*.txt")):
        date = pd.to_datetime(f.stem, format="%Y%m%d")
        haw, dov = score_text(f.read_text())
        net = round(haw - dov, 2)
        rows.append({
            "date": date,
            "haw": haw,
            "dov": dov,
            "tone_score": net,          # + şahin, − güvercin
            "tone": classify(net),
        })
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def main() -> None:
    PROC.mkdir(parents=True, exist_ok=True)
    df = build()
    out = PROC / "fomc_tone.csv"
    df.to_csv(out, index=False)
    print(f"{len(df)} açıklama skorlandı.")
    print("Ton dağılımı:", df["tone"].value_counts().to_dict())
    print("\nSon 8 açıklama:")
    print(df.tail(8).to_string(index=False))
    print(f"\nKayıt: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
