# -*- coding: utf-8 -*-
"""
backtest.py
===========
اختبار تاريخي احترافي لمؤشر FOMO Index على أحداث سوقية معروفة:
قيعان، قمم، أسواق صاعدة، أسواق هابطة.

يمكن تشغيله مباشرة من سطر الأوامر:
    python backtest.py

سيقوم بـ:
  1. جلب أطول تاريخ متاح من البيانات المجانية.
  2. حساب المؤشر عبر كامل الفترة.
  3. مقارنة قيمة المؤشر عند تواريخ معروفة (قمم/قيعان دورة البيتكوين).
  4. طباعة تقرير نصي + حفظ رسم بياني ثابت في assets/backtest_report.png
     (إن كانت matplotlib متاحة) وملف CSV بالنتائج الكاملة.

ملاحظة مهمة حول القيود:
  بيانات CoinGecko المجانية للـ market_chart محدودة عادة بحد أقصى ~365 يوماً
  (interval=daily) للحسابات المجانية بدون مفتاح API. لذلك هذا الـ Backtest
  يعمل ضمن أطول مدى بيانات مجاني متاح فعلياً، ويوضح ذلك في التقرير.
  لتوسيع المدى لسنوات كاملة (لتغطية قمة 2021 وقاع 2022 بدقة)، يُنصح
  باستخدام مفتاح CoinGecko Pro أو تصدير بيانات تاريخية يدوياً — الكود هنا
  مصمم للعمل فوراً بأي مدى بيانات متاح دون تعديل.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

import config
import data_sources as ds
import fomo_index as fi

# أحداث سوقية معروفة لمقارنة سلوك المؤشر حولها (تُستخدم فقط إذا وقعت
# ضمن مدى البيانات المتاح فعلياً وقت التشغيل)
KNOWN_EVENTS = [
    {"date": "2021-11-10", "label": "قمة الدورة السابقة (ATH ~$69k)", "type": "top"},
    {"date": "2022-06-18", "label": "قاع سوق هابط 2022", "type": "bottom"},
    {"date": "2022-11-21", "label": "قاع انهيار FTX", "type": "bottom"},
    {"date": "2024-03-14", "label": "قمة محلية قبل الهالفينغ 2024", "type": "top"},
    {"date": "2025-01-20", "label": "قمة محلية أوائل 2025", "type": "top"},
]


def run_backtest(days: int = 1500) -> pd.DataFrame:
    print("== FOMO Index Backtest ==")
    print("جاري جلب البيانات التاريخية (أطول مدى متاح مجاناً)...")

    btc_price = ds.fetch_btc_price_history(days)
    btc_market = ds.fetch_btc_market_data(days)
    stable = ds.fetch_stablecoin_supply_history(days)
    exch = ds.fetch_btc_exchange_metrics(days)

    actual_start = btc_price["date"].min()
    actual_end = btc_price["date"].max()
    print(f"المدى الفعلي للبيانات المتاحة: {actual_start.date()} -> {actual_end.date()}")

    components = fi.build_components_dataframe(stable, exch, btc_market)
    result = fi.compute_fomo_index(components)

    # تقييم عند الأحداث المعروفة (إن وقعت ضمن المدى المتاح)
    print("\n--- مقارنة المؤشر عند الأحداث المعروفة ---")
    hits = []
    for ev in KNOWN_EVENTS:
        ev_date = pd.to_datetime(ev["date"])
        if ev_date < actual_start or ev_date > actual_end:
            print(f"[تخطي] {ev['label']} ({ev['date']}) خارج مدى البيانات المتاح.")
            continue
        nearest_idx = (result["date"] - ev_date).abs().idxmin()
        row = result.loc[nearest_idx]
        hits.append({
            "event": ev["label"],
            "type": ev["type"],
            "date": row["date"].date(),
            "fomo_index": round(row["fomo_index"], 1) if not np.isnan(row["fomo_index"]) else None,
            "btc_price": round(row["btc_price"], 2) if not np.isnan(row["btc_price"]) else None,
        })
        idx_val = row["fomo_index"]
        verdict = "غير متاح"
        if not np.isnan(idx_val):
            if ev["type"] == "top" and idx_val >= 60:
                verdict = "✅ متوافق (فومو مرتفع عند القمة)"
            elif ev["type"] == "bottom" and idx_val <= 40:
                verdict = "✅ متوافق (فومو منخفض/يأس عند القاع)"
            else:
                verdict = "⚠️ غير متوافق تماماً — راجع البيانات/الأوزان"
        print(f"{ev['label']} ({row['date'].date()}): FOMO={idx_val:.1f} | السعر=${row['btc_price']:,.0f} -> {verdict}")

    events_df = pd.DataFrame(hits)

    # إحصائيات عامة: الارتباط بين المؤشر والسعر (متوقع أن يكون منخفضاً/متوسطاً
    # لأن الفلسفة أن المؤشر لا يتبع السعر مباشرة بل يسبقه أو يوضح سياقه)
    valid = result.dropna(subset=["fomo_index", "btc_price"])
    if len(valid) > 5:
        corr = valid["fomo_index"].corr(valid["btc_price"])
        print(f"\nالارتباط (Correlation) بين المؤشر والسعر: {corr:.3f}")
        print("(ارتباط متوسط منطقي: المؤشر يقيس تدفقات الأموال لا السعر نفسه)")

    # حفظ النتائج
    result.to_csv("backtest_full_history.csv", index=False)
    if not events_df.empty:
        events_df.to_csv("backtest_known_events.csv", index=False)
    print("\nتم حفظ: backtest_full_history.csv" + (" و backtest_known_events.csv" if not events_df.empty else ""))

    _try_plot(result)

    return result


def _try_plot(result: pd.DataFrame) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import os

        os.makedirs("assets", exist_ok=True)
        fig, ax1 = plt.subplots(figsize=(12, 6))
        ax1.plot(result["date"], result["fomo_index"], color="#D32F2F", label="FOMO Index")
        ax1.set_ylabel("FOMO Index (0-100)")
        ax1.set_ylim(0, 100)

        ax2 = ax1.twinx()
        ax2.plot(result["date"], result["btc_price"], color="#1976D2", alpha=0.5, label="BTC Price")
        ax2.set_ylabel("BTC Price (USD)")

        fig.legend(loc="upper left")
        plt.title("FOMO Index vs BTC Price — Backtest")
        plt.tight_layout()
        plt.savefig("assets/backtest_report.png", dpi=150)
        print("تم حفظ الرسم البياني: assets/backtest_report.png")
    except ImportError:
        print("matplotlib غير متاحة — تم تخطي حفظ الرسم البياني (النتائج الرقمية محفوظة في CSV).")


if __name__ == "__main__":
    run_backtest()
