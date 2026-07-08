# -*- coding: utf-8 -*-
"""
data_providers/http_utils.py
=============================
أدوات HTTP مشتركة (طلب مع إعادة محاولة، وبيانات احتياطية عند فشل الكل)
يستخدمها data_sources.py وكل مزودي البيانات داخل data_providers/ حتى لا
يتكرر منطق الشبكة في كل مكان.
"""

from __future__ import annotations

import time
import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fomo_index.http_utils")

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "FOMO-Index-Dashboard/1.0"})

RETRIES = 3  # محاولة أولى + محاولتان إعادة، ثم الانتقال للمصدر الاحتياطي
BACKOFF_SECONDS = 1.5
REQUEST_TIMEOUT = 20  # ثانية — يمنع تعليق التطبيق إذا تأخر أحد المزودين


def get_json(url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> Optional[dict]:
    """طلب GET مع مهلة 20 ثانية، وإعادة محاولة بتراجع أسي (exponential backoff)."""
    for attempt in range(1, RETRIES + 1):
        try:
            resp = _SESSION.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 — أي خطأ شبكة يُسجَّل فقط ولا يوقف التطبيق أبداً
            logger.warning("فشل الطلب (%s/%s) إلى %s: %s", attempt, RETRIES, url, exc)
            if attempt < RETRIES:
                time.sleep(BACKOFF_SECONDS * attempt)
    return None


def fallback_series(days: int, col_name: str, base: float, vol: float) -> pd.DataFrame:
    """
    بيانات احتياطية اصطناعية (Random Walk) تُستخدم فقط إذا فشل الاتصال بكل
    مصادر البيانات الحقيقية، حتى لا تتعطل لوحة التحكم بالكامل.
    """
    logger.warning("استخدام بيانات احتياطية اصطناعية لعمود: %s", col_name)
    rng = np.random.default_rng(42)
    dates = pd.date_range(end=datetime.now(timezone.utc).date(), periods=days, freq="D")
    steps = rng.normal(0, vol, size=days)
    series = base * np.exp(np.cumsum(steps)) if base != 0 else rng.normal(0, vol, size=days)
    df = pd.DataFrame({"date": dates, col_name: series})
    df["is_fallback"] = True
    return df
