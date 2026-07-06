# -*- coding: utf-8 -*-
"""
fomo_index.py
=============
المنطق الرياضي الكامل لحساب مؤشر FOMO Index.
هذا الملف لا يعرف شيئاً عن Streamlit ولا عن مصدر البيانات — فقط دوال نقية
(pure functions) تأخذ DataFrame وترجع DataFrame، مما يجعلها قابلة للاختبار
وإعادة الاستخدام في backtest.py بسهولة.

خطوات الحساب لكل مكوّن:
  1. تنعيم القيمة الخام بـ EMA لإزالة الضوضاء اليومية (denoising).
  2. حساب Rolling Percentile Rank ضمن نافذة متحركة (تطبيع 0-100 مقاوم
     للقيم الشاذة، بعكس Z-Score الذي يتأثر بالـ outliers).
  3. عكس الاتجاه إذا كان "أعلى = فومو أقل" حسب COMPONENT_INVERT.

الحساب النهائي:
  - مجموع مرجّح (Weighted Sum) للمكونات الأربعة حسب COMPONENT_WEIGHTS.
  - تنعيم إضافي للمخرج النهائي (EMA) + تحديد سقف للتغيّر اليومي
    (Rate Limiting) لمنع القفزات الحادة/الإشارات الكاذبة.
  - إعادة توزيع الأوزان تلقائياً إذا كان أحد المكونات غير متاح في يوم معيّن
    (Graceful Degradation) بدل كسر الحساب بالكامل.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

import config


# ----------------------------------------------------------------------------
# أدوات التطبيع
# ----------------------------------------------------------------------------
def smooth_ema(series: pd.Series, span: int) -> pd.Series:
    """تنعيم أسي لإزالة الضوضاء اليومية قبل أي حساب آخر."""
    return series.ewm(span=span, adjust=False, min_periods=1).mean()


def rolling_percentile_rank(series: pd.Series, window: int) -> pd.Series:
    """
    يحوّل القيمة الحالية إلى مرتبة مئوية (0-100) بالنسبة لتاريخها الخاص
    ضمن نافذة متحركة. هذا التطبيع مقاوم للـ outliers بعكس Z-Score التقليدي،
    وهو ما يمنع أرقاماً متطرفة نادرة (مثل يوم انهيار سيولة استثنائي) من
    التسبب بقفزة غير منطقية في المؤشر.
    """
    def _rank(window_vals: np.ndarray) -> float:
        current = window_vals[-1]
        if np.isnan(current):
            return np.nan
        valid = window_vals[~np.isnan(window_vals)]
        if len(valid) < 2:
            return 50.0
        rank = (valid < current).sum() + 0.5 * (valid == current).sum()
        return 100.0 * rank / len(valid)

    return series.rolling(window=window, min_periods=2).apply(_rank, raw=True)


def compute_component_score(raw: pd.Series, window: int, invert: bool, ema_span: int = config.EMA_SPAN_RAW) -> pd.Series:
    """يطبّق: تنعيم -> تطبيع percentile -> عكس إذا لزم -> يرجع سلسلة 0-100."""
    smoothed = smooth_ema(raw, ema_span)
    pct = rolling_percentile_rank(smoothed, window)
    if invert:
        pct = 100.0 - pct
    return pct


# ----------------------------------------------------------------------------
# بناء جدول المكونات الموحّد
# ----------------------------------------------------------------------------
def build_components_dataframe(
    stablecoin_df: pd.DataFrame,
    btc_exchange_df: pd.DataFrame,
    btc_price_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    يدمج كل مصادر البيانات على عمود date ويحسب القيم الخام لكل مكوّن
    (قبل التطبيع)، تمهيداً لحساب compute_fomo_index.
    """
    df = stablecoin_df.merge(btc_exchange_df, on="date", how="outer")
    df = df.merge(btc_price_df, on="date", how="outer")
    df = df.sort_values("date").reset_index(drop=True)

    # تعبئة أمامية بسيطة للفجوات القصيرة (لا تتجاوز 3 أيام) فقط
    df = df.ffill(limit=3)

    # المكوّن 1: Stablecoin Inflows -> تغيّر نسبي قصير المدى (7 أيام) في المعروض
    df["raw_stablecoin_inflows"] = df["stablecoin_supply"].pct_change(
        periods=config.SHORT_TERM_WINDOW
    ) * 100

    # المكوّن 4: Stablecoin Supply -> اتجاه طويل المدى (90 يوم)
    df["raw_stablecoin_supply"] = df["stablecoin_supply"].pct_change(
        periods=config.LONG_TERM_WINDOW
    ) * 100

    # المكوّن 2 و 3 يأتيان جاهزين من data_sources (netflow / balance)
    df["raw_btc_exchange_netflow"] = df.get("btc_exchange_netflow")
    df["raw_btc_exchange_balance"] = df.get("btc_exchange_balance")

    return df


# ----------------------------------------------------------------------------
# الحساب النهائي للمؤشر
# ----------------------------------------------------------------------------
def compute_fomo_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    يأخذ الناتج من build_components_dataframe ويضيف:
      - عمود لكل مكوّن بعد التطبيع (score_<component>)
      - fomo_index_raw   : المجموع المرجّح قبل الـ rate limiting
      - fomo_index       : المؤشر النهائي بعد التنعيم وتحديد سقف التغيّر اليومي
      - contribution_<c> : نسبة مساهمة كل مكوّن في القيمة النهائية (لعرضها في الواجهة)
    """
    df = df.copy()

    raw_map = {
        "stablecoin_inflows": "raw_stablecoin_inflows",
        "btc_exchange_netflow": "raw_btc_exchange_netflow",
        "btc_exchange_balance": "raw_btc_exchange_balance",
        "stablecoin_supply": "raw_stablecoin_supply",
    }

    scores = {}
    for comp, raw_col in raw_map.items():
        invert = config.COMPONENT_INVERT[comp]
        scores[comp] = compute_component_score(df[raw_col], config.ROLLING_WINDOW, invert)
        df[f"score_{comp}"] = scores[comp]

    # ---- مجموع مرجّح مع إعادة توزيع الأوزان عند غياب بيانات مكوّن معيّن ----
    score_matrix = pd.DataFrame(scores)
    weights = pd.Series(config.COMPONENT_WEIGHTS)

    def _weighted_row(row: pd.Series) -> float:
        available = row.dropna()
        if available.empty:
            return np.nan
        w = weights[available.index]
        w = w / w.sum()  # إعادة توزيع الأوزان لتبقى نسبتها 100% رغم غياب بعض المكونات
        return float((available * w).sum())

    df["fomo_index_raw"] = score_matrix.apply(_weighted_row, axis=1)

    # ---- مساهمة كل مكوّن (لأغراض العرض في الواجهة) ----
    for comp in raw_map:
        w = config.COMPONENT_WEIGHTS[comp]
        df[f"contribution_{comp}"] = df[f"score_{comp}"] * w

    # ---- تنعيم نهائي + سقف تغيّر يومي لمنع الإشارات الكاذبة ----
    df["fomo_index_smoothed"] = smooth_ema(df["fomo_index_raw"], config.EMA_SPAN_FINAL)
    df["fomo_index"] = _apply_rate_limit(df["fomo_index_smoothed"], config.MAX_DAILY_DELTA)
    df["fomo_index"] = df["fomo_index"].clip(0, 100)

    return df


def _apply_rate_limit(series: pd.Series, max_delta: float) -> pd.Series:
    """
    يمنع المؤشر من القفز أكثر من max_delta نقطة بين يوم وآخر.
    هذا يقلل الإشارات الكاذبة الناتجة عن بيانات شاذة ليوم واحد،
    ويجعل تفسير المؤشر أكثر استقراراً وموثوقية بصرياً.
    """
    values = series.to_numpy(dtype=float)
    limited = values.copy()
    for i in range(1, len(values)):
        if np.isnan(limited[i]) or np.isnan(limited[i - 1]):
            continue
        delta = limited[i] - limited[i - 1]
        if delta > max_delta:
            limited[i] = limited[i - 1] + max_delta
        elif delta < -max_delta:
            limited[i] = limited[i - 1] - max_delta
    return pd.Series(limited, index=series.index)


def classify_value(value: float) -> Dict[str, str]:
    """يرجع تصنيف نصي ولون للقيمة الحالية للمؤشر."""
    if value is None or np.isnan(value):
        return {"label": "بيانات غير كافية", "color": "#9E9E9E"}
    zone = config.get_zone(value)
    return {"label": zone.label_ar, "color": zone.color}
