# -*- coding: utf-8 -*-
"""
app.py
======
لوحة تحكم FOMO Index — واجهة احترافية بأسلوب Bloomberg/TradingView
باستخدام Python + Streamlit فقط (بدون React/JSX/Next.js).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
import data_sources as ds
import fomo_index as fi

# ------------------------------------------------------------------------
# إعداد الصفحة
# ------------------------------------------------------------------------
st.set_page_config(
    page_title="FOMO Index",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------------
# الشريط الجانبي: إعدادات + وضع العرض
# ------------------------------------------------------------------------
with st.sidebar:
    st.title("⚙️ الإعدادات")
    dark_mode = st.toggle("الوضع الليلي", value=config.DEFAULT_DARK_MODE)
    days_range = st.slider("مدى البيانات (أيام)", min_value=90, max_value=365, value=180, step=15)
    st.divider()
    refresh_clicked = st.button("🔄 تحديث البيانات الآن", use_container_width=True)
    st.divider()
    st.caption(
        "المؤشر يعتمد فقط على حركة الأموال الفعلية (Stablecoin Flows + BTC "
        "Exchange Flows) — لا يستخدم السعر أو المشاعر أو الأخبار في حسابه."
    )
    st.caption(f"آخر تحديث: {ds.get_last_update_str()}")

# ------------------------------------------------------------------------
# CSS مخصص — أسلوب Bloomberg/TradingView
# ------------------------------------------------------------------------
if dark_mode:
    bg_color, card_bg, text_color, grid_color = "#0E1117", "#161B22", "#E6EDF3", "#30363D"
else:
    bg_color, card_bg, text_color, grid_color = "#F5F6FA", "#FFFFFF", "#1A1A1A", "#E0E0E0"

st.markdown(
    f"""
    <style>
    .stApp {{ background-color: {bg_color}; color: {text_color}; }}
    div[data-testid="stMetric"] {{
        background-color: {card_bg};
        border: 1px solid {grid_color};
        border-radius: 12px;
        padding: 14px 16px;
    }}
    .fomo-card {{
        background-color: {card_bg};
        border: 1px solid {grid_color};
        border-radius: 14px;
        padding: 18px 20px;
        margin-bottom: 14px;
    }}
    .fomo-badge {{
        display: inline-block;
        padding: 4px 14px;
        border-radius: 999px;
        font-weight: 700;
        font-size: 0.95rem;
    }}
    h1, h2, h3 {{ color: {text_color}; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🔥 FOMO Index")
st.caption("مؤشر يقيس درجة الفومو الحقيقية من خلال حركة الأموال الفعلية — وليس المشاعر أو السعر أو الأخبار.")


# ------------------------------------------------------------------------
# جلب وحساب البيانات (مع Cache)
# ------------------------------------------------------------------------
@st.cache_data(ttl=config.CACHE_TTL_SECONDS, show_spinner="جاري جلب البيانات وحساب المؤشر...")
def load_and_compute(days: int) -> pd.DataFrame:
    btc_market = ds.fetch_btc_market_data(days)
    stable = ds.fetch_stablecoin_supply_history(days)
    exch = ds.fetch_btc_exchange_metrics(days)
    components = fi.build_components_dataframe(stable, exch, btc_market)
    return fi.compute_fomo_index(components)


if refresh_clicked:
    load_and_compute.clear()

data = load_and_compute(days_range)

if data.empty or data["fomo_index"].dropna().empty:
    st.error("تعذّر حساب المؤشر — تحقق من الاتصال بالإنترنت أو حاول التحديث لاحقاً.")
    st.stop()

is_proxy = bool(data.get("is_proxy", pd.Series([False])).fillna(False).any())
is_fallback = bool(data.get("is_fallback", pd.Series([False])).fillna(False).any())

latest = data.dropna(subset=["fomo_index"]).iloc[-1]
current_value = float(latest["fomo_index"])
current_price = float(latest["btc_price"]) if not np.isnan(latest["btc_price"]) else None
zone = fi.classify_value(current_value)

if is_proxy:
    st.info(
        "🧪 **Proxy Mode**: بيانات Exchange Netflow / Exchange Balance الحالية "
        "تقديرية (مشتقة من حجم التداول العام) لعدم توفر مصدر مجاني حقيقي على "
        "مستوى المنصات. يمكن استبدالها بسهولة ببيانات حقيقية (CryptoQuant/"
        "Glassnode) بإضافة مفتاح API في config.py.",
        icon="🧪",
    )
if is_fallback:
    st.warning("⚠️ تعذّر الاتصال بأحد مصادر البيانات — يتم عرض بيانات احتياطية اصطناعية مؤقتاً.")


# ------------------------------------------------------------------------
# الصف الأول: Gauge + مقاييس رئيسية
# ------------------------------------------------------------------------
col_gauge, col_metrics = st.columns([1.1, 1.4])

with col_gauge:
    fig_gauge = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=current_value,
            number={"suffix": "", "font": {"size": 46, "color": zone["color"]}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": text_color},
                "bar": {"color": zone["color"], "thickness": 0.28},
                "bgcolor": card_bg,
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
        height=320,
        margin=dict(l=20, r=20, t=30, b=10),
        paper_bgcolor=bg_color,
        font={"color": text_color},
    )
    st.plotly_chart(fig_gauge, use_container_width=True)
    st.markdown(
        f"<div style='text-align:center'><span class='fomo-badge' "
        f"style='background-color:{zone['color']}22; color:{zone['color']}; "
        f"border:1px solid {zone['color']}'>{zone['label']}</span></div>",
        unsafe_allow_html=True,
    )

with col_metrics:
    m1, m2, m3 = st.columns(3)
    m1.metric("قيمة المؤشر", f"{current_value:.1f} / 100")
    m2.metric("سعر BTC", f"${current_price:,.0f}" if current_price else "—")
    prev = data.dropna(subset=["fomo_index"]).iloc[-2] if len(data.dropna(subset=["fomo_index"])) > 1 else None
    delta = current_value - float(prev["fomo_index"]) if prev is not None else None
    m3.metric("تغيّر يومي", f"{delta:+.1f}" if delta is not None else "—")

    st.markdown("<div class='fomo-card'>", unsafe_allow_html=True)
    st.subheader("مكونات المؤشر ومساهمتها")
    contrib_cols = [c for c in data.columns if c.startswith("contribution_")]
    contrib_row = latest[contrib_cols].fillna(0)
    labels_ar = {
        "contribution_stablecoin_inflows": "تدفقات Stablecoin (قصيرة المدى)",
        "contribution_btc_exchange_netflow": "Exchange Netflow (BTC)",
        "contribution_btc_exchange_balance": "Exchange Balance (BTC)",
        "contribution_stablecoin_supply": "نمو معروض Stablecoin (طويل المدى)",
    }
    fig_bar = go.Figure(
        go.Bar(
            x=[contrib_row[c] for c in contrib_cols],
            y=[labels_ar[c] for c in contrib_cols],
            orientation="h",
            marker_color=["#42A5F5", "#AB47BC", "#FFA726", "#66BB6A"],
        )
    )
    fig_bar.update_layout(
        height=220,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor=card_bg,
        plot_bgcolor=card_bg,
        font={"color": text_color},
        xaxis_title="نقاط المساهمة",
    )
    st.plotly_chart(fig_bar, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


# ------------------------------------------------------------------------
# الصف الثاني: رسوم بيانية زمنية
# ------------------------------------------------------------------------
tab1, tab2, tab3 = st.tabs(["📈 المؤشر عبر الزمن", "💰 سعر BTC", "🔀 مقارنة المؤشر مع السعر"])

hist = data.dropna(subset=["fomo_index"])

with tab1:
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(x=hist["date"], y=hist["fomo_index"], line=dict(color="#D32F2F", width=2), name="FOMO Index"))
    for z in config.INDEX_ZONES:
        fig1.add_hrect(y0=z.low, y1=min(z.high, 100), fillcolor=z.color, opacity=0.06, line_width=0)
    fig1.update_layout(height=380, paper_bgcolor=bg_color, plot_bgcolor=bg_color, font={"color": text_color}, yaxis_range=[0, 100])
    st.plotly_chart(fig1, use_container_width=True)

with tab2:
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=hist["date"], y=hist["btc_price"], line=dict(color="#1976D2", width=2), name="BTC Price"))
    fig2.update_layout(height=380, paper_bgcolor=bg_color, plot_bgcolor=bg_color, font={"color": text_color})
    st.plotly_chart(fig2, use_container_width=True)

with tab3:
    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(x=hist["date"], y=hist["fomo_index"], name="FOMO Index", line=dict(color="#D32F2F"), yaxis="y1"))
    fig3.add_trace(go.Scatter(x=hist["date"], y=hist["btc_price"], name="BTC Price", line=dict(color="#1976D2"), yaxis="y2"))
    fig3.update_layout(
        height=420,
        paper_bgcolor=bg_color,
        plot_bgcolor=bg_color,
        font={"color": text_color},
        yaxis=dict(title="FOMO Index", range=[0, 100], side="left"),
        yaxis2=dict(title="BTC Price (USD)", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig3, use_container_width=True)


# ------------------------------------------------------------------------
# الصف الثالث: جدول تاريخي + سجل آخر القراءات
# ------------------------------------------------------------------------
st.subheader("📋 السجل التاريخي")
display_cols = {
    "date": "التاريخ",
    "fomo_index": "FOMO Index",
    "btc_price": "سعر BTC",
    "score_stablecoin_inflows": "Stablecoin Inflows",
    "score_btc_exchange_netflow": "Exchange Netflow",
    "score_btc_exchange_balance": "Exchange Balance",
    "score_stablecoin_supply": "Stablecoin Supply",
}
table = hist[list(display_cols.keys())].rename(columns=display_cols).sort_values("التاريخ", ascending=False)
table["FOMO Index"] = table["FOMO Index"].round(1)
table["سعر BTC"] = table["سعر BTC"].round(0)

last_readings, full_history = st.tabs(["آخر 15 قراءة", "السجل الكامل"])
with last_readings:
    st.dataframe(table.head(15), use_container_width=True, hide_index=True)
with full_history:
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ تحميل السجل الكامل (CSV)",
        data=table.to_csv(index=False).encode("utf-8-sig"),
        file_name="fomo_index_history.csv",
        mime="text/csv",
    )

st.divider()
st.caption(
    "⚠️ هذا المؤشر لأغراض تعليمية/تحليلية فقط وليس نصيحة استثمارية. "
    "البيانات مصدرها CoinGecko و DeFiLlama (مجانية بالكامل)."
)
