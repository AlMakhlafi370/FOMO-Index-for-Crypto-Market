# -*- coding: utf-8 -*-
"""
persistence.py
===============
طبقة بسيطة لحفظ واسترجاع "آخر قراءة سليمة" للمؤشر على القرص.

لماذا هذا الملف؟
  إذا تعطلت كل مصادر البيانات في نفس اللحظة (CoinGecko + DeFiLlama + كل
  مزودي data_providers)، يجب ألا تظهر صفحة فارغة أو رسالة خطأ فنية.
  بدلاً من ذلك: نعرض آخر قيمة مؤشر تم حسابها بنجاح، مع تنبيه صغير أنها
  ليست محدّثة الآن.

كيف يعمل؟
  عند كل حساب ناجح للمؤشر (app.py) يتم استدعاء save_last_reading() فتُكتب
  آخر 30 يوماً (date, fomo_index, btc_price) في ملف JSON محلي بسيط.
  عند فشل كل مصادر البيانات، تستدعي app.py دالة load_last_reading()
  لاسترجاع هذه النسخة الاحتياطية.

ملاحظات موثوقية:
  - كل عملية قراءة/كتابة محاطة بـ try/except: فشل الحفظ أو القراءة لا يوقف
    التطبيق إطلاقاً — فقط يُسجَّل تحذير ويُتجاهل.
  - المسار قابل للتخصيص عبر متغير بيئة FOMO_CACHE_DIR (مفيد على Render إذا
    رغبت بتوجيهه لمسار قرص دائم/Persistent Disk اختياري).
  - في حال عدم توفر تصريح كتابة على القرص (بيئة للقراءة فقط)، يفشل الحفظ
    بصمت والتطبيق يستمر بالعمل بشكل طبيعي (فقط بدون هذه الطبقة الاحتياطية).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any

import pandas as pd

logger = logging.getLogger("fomo_index.persistence")

CACHE_DIR = Path(os.environ.get("FOMO_CACHE_DIR", ".fomo_cache"))
CACHE_FILE = CACHE_DIR / "last_reading.json"


def save_last_reading(df: pd.DataFrame) -> None:
    """
    يحفظ آخر 30 يوماً من قراءات المؤشر الصالحة (fomo_index غير فارغ).
    لا يرمي أي استثناء إطلاقاً — أي فشل في الحفظ يُسجَّل ويُتجاهل بصمت.
    """
    try:
        valid = df.dropna(subset=["fomo_index"])
        if valid.empty:
            return

        tail = valid.tail(30)[["date", "fomo_index", "btc_price"]].copy()
        tail["date"] = tail["date"].astype(str)
        tail["fomo_index"] = tail["fomo_index"].astype(float)
        tail["btc_price"] = tail["btc_price"].astype(float)

        payload = {
            "saved_at": time.time(),
            "rows": tail.to_dict(orient="records"),
        }

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("تعذّر حفظ آخر قراءة سليمة على القرص: %s", exc)


def load_last_reading() -> Optional[Dict[str, Any]]:
    """
    يرجع dict فيه:
        df        : DataFrame بعمودي date/fomo_index/btc_price لآخر 30 يوماً
        saved_at  : الطابع الزمني (epoch) لوقت الحفظ
    أو None إذا لم توجد نسخة محفوظة صالحة أو حدث أي خطأ أثناء القراءة.
    """
    try:
        if not CACHE_FILE.exists():
            return None
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        rows = payload.get("rows", [])
        if not rows:
            return None

        df = pd.DataFrame(rows)
        if df.empty or "fomo_index" not in df.columns:
            return None
        df["date"] = pd.to_datetime(df["date"])
        return {"df": df, "saved_at": payload.get("saved_at")}
    except Exception as exc:  # noqa: BLE001
        logger.warning("تعذّر قراءة آخر قراءة محفوظة من القرص: %s", exc)
        return None
