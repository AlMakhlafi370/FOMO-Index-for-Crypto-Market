# -*- coding: utf-8 -*-
"""
app.py
======
نقطة التشغيل الوحيدة لمشروع FOMO Index.

تشغيل محلي:
    streamlit run app.py

تصميم الصفحة (بأسلوب Fear & Greed Index — بسيط واحترافي):
    🔥 FOMO Index
    [عداد Gauge كبير بالقيمة الحالية]
    [الحالة: Very Low / Low / Neutral / High / Extreme FOMO]
    [تفسير قصير سطر إلى سطرين]
    [سعر BTC الحالي  |  تاريخ آخر تحديث]
    [رسم بياني صغير لآخر 30 يوماً]

لا يوجد أي عنصر تحكم يتطلب تدخل المستخدم (بدون أزرار، بدون قوائم اختيار،
بدون صفحات إضافية). البيانات تُجلب وتُحسب تلقائياً عند فتح الصفحة،
وتُخزَّن مؤقتاً (st.cache_data) لمدة ساعة، ويُعاد تحميل الصفحة تلقائياً
كل ساعة عبر وسم HTML لإعادة التحديث (بدون أي مكتبة خارجية إضافية).

مبدأ الموثوقية الأساسي في هذا الملف:
    أي خطأ (شبكة، بيانات ناقصة، استثناء غير متوقع) يجب أن يُعالَج محلياً
    ولا يُسمح له أبداً بإيقاف التطبيق أو إظهار شاشة عطل للمستخدم. في أسوأ
    الحالات نعرض آخر قراءة محفوظة (persistence.py)، وإن لم توجد نعرض
    رسالة "البيانات غير متوفرة حالياً" فقط.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
import data_sources as ds
import fomo_index as fi
import persistence

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fomo_index.app")

# ------------------------------------------------------------------------
# إعداد الصفحة (صفحة واحدة فقط، بدون قائمة جانبية أو صفحات إضافية)
# ------------------------------------------------------------------------
st.set_page_config(
    page_title="FOMO Index",
    page_icon="🔥",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# إعادة تحميل الصفحة تلقائياً كل ساعة (بدون أي مكتبة خارجية إضافية)
st.markdown(
    f'<meta http-equiv="refresh" content="{config.AUTO_REFRESH_SECONDS}">',
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------------
# تصميم ثابت (بدون خيار تبديل — مظهر داكن احترافي دائم)
# ------------------------------------------------------------------------
BG_COLOR, CARD_BG, TEXT_COLOR, GRID_COLOR = "#0E1117", "#161B22", "#E6EDF3", "#30363D"

st.markdown(
    f"""
    <style>
    .stApp {{ background-color: {BG_COLOR}; color: {TEXT_COLOR}; }}
    #MainMenu, footer, header {{ visibility: hidden; }}
    .fomo-title {{
        text-align: center; font-size: 2.4rem; font-weight: 800; margin-bottom: 0;
    }}
    .fomo-status-badge {{
        display: block; text-align: center; margin: 6px auto 14px auto;
        padding: 6px 22px; border-radius: 999px; font-weight: 800;
        font-size: 1.3rem; width: fit-content;
    }}
    .fomo-explain {{
        text-align: center; font-size: 1.02rem; color: {TEXT_COLOR};
        opacity: 0.9; max-width: 560px; margin: 0 auto 18px auto; line-height: 1.6;
    }}
    .fomo-meta-row {{
        display: flex; justify-content: center; gap: 40px; margin-bottom: 10px;
        flex-wrap: wrap;
    }}
    .fomo-meta-item {{ text-align: center; }}
    .fomo-meta-label {{ font-size: 0.85rem; opacity: 0.65; }}
    .fomo-meta-value {{ font-size: 1.15rem; font-weight: 700; }}
    .fomo-stale-banner {{
        text-align: center; background-color: #3A2E12; color: #FFCA28;
        border: 1px solid #FFCA2855; border-radius: 10px; padding: 8px 14px;
        margin: 10px auto; max-width: 560px; font-size: 0.9rem;
    }}
    .fomo-unavailable {{
        text-align: center; font-size: 1.6rem; font-weight: 700; margin-top: 60px;
        color: {TEXT_COLOR};
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="fomo-title">🔥 FOMO Index</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------------
# الحساب الكامل للمؤشر — محاط بالكامل بمعالجة أخطاء شاملة
# ------------------------------------------------------------------------
@st.cache_data(ttl=config.CACHE_TTL_SECONDS, show_spinner=False)
def compute_index_cached():
    """
    يحاول حساب المؤشر الكامل. يُخزَّن الناتج لمدة ساعة (CACHE_TTL_SECONDS)
    حتى لا يُعاد جلب البيانات عند كل Refresh للصفحة.

    نجلب FETCH_DAYS_FOR_CALCULATION يوماً (وليس فقط 30) لأن حساب المؤشر
    يحتاج نافذة تطبيع 180 يوماً + نافذة سياق 90 يوماً لتكون النتيجة دقيقة؛
    الواجهة نفسها تعرض لاحقاً فقط آخر 30 يوماً منها.

    أي استثناء غير متوقع يُلتقط هنا بالكامل ويُرجع None بدل إيقاف التطبيق.
    """
    days = config.FETCH_DAYS_FOR_CALCULATION
    try:
        btc_market = ds.fetch_btc_market_data(days)
        stable_supply = ds.fetch_stablecoin_supply_history(days)
        stable_inflows = ds.fetch_stablecoin_exchange_inflows(days)
        exch = ds.fetch_btc_exchange_metrics(days)

        if btc_market is None or btc_market.empty:
            logger.error("لا توجد بيانات سعر BTC إطلاقاً — لا يمكن حساب المؤشر.")
            return None

        components = fi.build_components_dataframe(stable_supply, stable_inflows, exch, btc_market)
        result = fi.compute_fomo_index(components)

        if result is None or result.empty or result["fomo_index"].dropna().empty:
            logger.error("نتيجة حساب المؤشر فارغة تماماً.")
            return None

        persistence.save_last_reading(result)  # نجاح -> نحفظها كآخر قراءة سليمة
        return result

    except Exception as exc:  # noqa: BLE001 — أي خطأ غير متوقع لا يجب أن يوقف التطبيق
        logger.exception("خطأ غير متوقع أثناء حساب المؤشر: %s", exc)
        return None


# ------------------------------------------------------------------------
# تحديد مصدر البيانات المعروضة: حساب حي، أو آخر قراءة محفوظة، أو رسالة عجز
# ------------------------------------------------------------------------
result = None
is_stale = False
saved_at_ts = None

try:
    result = compute_index_cached()
except Exception as exc:  # noqa: BLE001 — حماية إضافية حول استدعاء الكاش نفسه
    logger.exception("فشل غير متوقع عند استدعاء compute_index_cached: %s", exc)
    result = None

if result is None:
    try:
        saved = persistence.load_last_reading()
    except Exception:  # noqa: BLE001
        saved = None

    if saved is not None:
        result = saved["df"]
        saved_at_ts = saved.get("saved_at")
        is_stale = True
    else:
        st.markdown('<div class="fomo-unavailable">البيانات غير متوفرة حالياً</div>', unsafe_allow_html=True)
        st.stop()

# ------------------------------------------------------------------------
# استخراج آخر قراءة صالحة بأمان تام (بدون أي KeyError / IndexError محتمل)
# ------------------------------------------------------------------------
try:
    valid_rows = result.dropna(subset=["fomo_index"])
    if valid_rows.empty:
        st.markdown('<div class="fomo-unavailable">البيانات غير متوفرة حالياً</div>', unsafe_allow_html=True)
        st.stop()

    latest = valid_rows.iloc[-1]
    current_value = float(latest["fomo_index"])
    current_price = float(latest["btc_price"]) if "btc_price" in latest and pd.notna(latest["btc_price"]) else None
    latest_date = latest["date"] if "date" in latest and pd.notna(latest["date"]) else None
    zone = fi.classify_value(current_value)
except Exception as exc:  # noqa: BLE001
    logger.exception("خطأ أثناء استخراج آخر قراءة: %s", exc)
    st.markdown('<div class="fomo-unavailable">البيانات غير متوفرة حالياً</div>', unsafe_allow_html=True)
    st.stop()

# ------------------------------------------------------------------------
# تنبيه صغير إذا كانت هذه بيانات محفوظة (وليست حية الآن)
# ------------------------------------------------------------------------
if is_stale:
    if saved_at_ts:
        age_minutes = max(0, int((datetime.now(timezone.utc).timestamp() - saved_at_ts) / 60))
        age_txt = f"منذ {age_minutes} دقيقة" if age_minutes < 120 else f"منذ {age_minutes // 60} ساعة"
    else:
        age_txt = ""
    st.markdown(
        f'<div class="fomo-stale-banner">⚠️ تعذّر الاتصال بمصادر البيانات حالياً — '
        f'يتم عرض آخر قراءة سليمة محفوظة {age_txt}.</div>',
        unsafe_allow_html=True,
    )

# ------------------------------------------------------------------------
# العداد الرئيسي (Gauge) — القيمة الحالية
# ------------------------------------------------------------------------
try:
    fig_gauge = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=current_value,
            number={"font": {"size": 54, "color": zone["color"]}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": TEXT_COLOR},
                "bar": {"color": zone["color"], "thickness": 0.28},
                "bgcolor": CARD_BG,
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 20], "color": "#1B3A20"},
                    {"range": [20, 40], "color": "#2E5D33"},
                    {"range": [40, 60], "color": "#5D5424"},
                    {"range": [60, 80], "color": "#5D3A14"},
                    {"range": [80, 100], "color": "#5D1F1F"},
                ],
            },
        )
    )
    fig_gauge.update_layout(
        height=340,
        margin=dict(l=20, r=20, t=20, b=0),
        paper_bgcolor=BG_COLOR,
        font={"color": TEXT_COLOR},
    )
    st.plotly_chart(fig_gauge, use_container_width=True, config={"displayModeBar": False})
except Exception as exc:  # noqa: BLE001
    logger.exception("تعذّر رسم العداد: %s", exc)
    st.markdown(f'<div class="fomo-title">{current_value:.1f}</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------------
# الحالة النصية + التفسير القصير
# ------------------------------------------------------------------------
st.markdown(
    f'<span class="fomo-status-badge" style="background-color:{zone["color"]}22; '
    f'color:{zone["color"]}; border:1px solid {zone["color"]}">{zone["label_en"]}</span>',
    unsafe_allow_html=True,
)
st.markdown(f'<div class="fomo-explain">{zone["explanation_ar"]}</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------------
# سعر BTC الحالي + تاريخ آخر تحديث
# ------------------------------------------------------------------------
price_txt = f"${current_price:,.0f}" if current_price is not None else "—"
date_txt = latest_date.strftime("%Y-%m-%d") if latest_date is not None else "—"

st.markdown(
    f"""
    <div class="fomo-meta-row">
        <div class="fomo-meta-item">
            <div class="fomo-meta-label">سعر BTC الحالي</div>
            <div class="fomo-meta-value">{price_txt}</div>
        </div>
        <div class="fomo-meta-item">
            <div class="fomo-meta-label">تاريخ آخر تحديث</div>
            <div class="fomo-meta-value">{date_txt}</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------------
# رسم بياني صغير — آخر 30 يوماً فقط، بدون أي أزرار أو تحكم
# ------------------------------------------------------------------------
try:
    chart_df = valid_rows.tail(config.CHART_DISPLAY_DAYS)
    if len(chart_df) >= 2:
        fig_mini = go.Figure()
        fig_mini.add_trace(
            go.Scatter(
                x=chart_df["date"],
                y=chart_df["fomo_index"],
                mode="lines",
                line=dict(color=zone["color"], width=2.5),
                fill="tozeroy",
                fillcolor=f'{zone["color"]}22',
            )
        )
        fig_mini.update_layout(
            height=180,
            margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor=BG_COLOR,
            plot_bgcolor=BG_COLOR,
            font={"color": TEXT_COLOR, "size": 11},
            yaxis=dict(range=[0, 100], gridcolor=GRID_COLOR),
            xaxis=dict(gridcolor=GRID_COLOR),
            showlegend=False,
        )
        st.plotly_chart(fig_mini, use_container_width=True, config={"displayModeBar": False})
except Exception as exc:  # noqa: BLE001
    logger.exception("تعذّر رسم الرسم البياني المصغر: %s", exc)
    # لا نعرض شيئاً بدل الرسم — لا داعي لإزعاج المستخدم بخطأ فني هنا

st.markdown(
    '<p style="text-align:center; opacity:0.5; font-size:0.8rem; margin-top:10px;">'
    'لأغراض تعليمية/تحليلية فقط وليس نصيحة استثمارية.</p>',
    unsafe_allow_html=True,
)
