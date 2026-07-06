# -*- coding: utf-8 -*-
"""
data_sources.py
================
كل دوال جلب البيانات موجودة هنا فقط. الهدف: عزل منطق المؤشر (fomo_index.py)
تماماً عن تفاصيل أي API خارجي، بحيث لو تغيّر مصدر بيانات أو انقطع،
نعدّل هذا الملف فقط دون المساس بمنطق الحساب.

المصادر المستخدمة (كلها مجانية ولا تحتاج مفتاح API):
  1. CoinGecko           -> سعر BTC التاريخي.
  2. DeFiLlama Stablecoins -> إجمالي المعروض العالمي للستيبل كوين (Circulating Supply).

بيانات "Exchange Netflow" و "Exchange Balance" الحقيقية (بيانات على مستوى
محافظ المنصات) هي بيانات مدفوعة عادة (Glassnode / CryptoQuant) ولا يوجد
مصدر مجاني موثوق يقدمها بدون مفتاح API. لذلك تم بناء "Proxy Mode":
تقدير تقريبي لحركة الأموال من/إلى المنصات باستخدام بيانات حجم التداول
والتقلب المتاحة مجاناً من CoinGecko، مع تصميم يسمح باستبدال هذا التقدير
لاحقاً بأي مزود بيانات حقيقي بمجرد إضافة مفتاح API في config.py.
"""

from __future__ import annotations

import time
import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import requests

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fomo_index.data_sources")

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "FOMO-Index-Dashboard/1.0"})

RETRIES = 3
BACKOFF_SECONDS = 1.5


def _get_json(url: str, params: Optional[dict] = None) -> Optional[dict]:
    """طلب GET مع إعادة محاولة وتراجع أسي (exponential backoff)."""
    for attempt in range(1, RETRIES + 1):
        try:
            resp = _SESSION.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("فشل الطلب (%s/%s) إلى %s: %s", attempt, RETRIES, url, exc)
            if attempt < RETRIES:
                time.sleep(BACKOFF_SECONDS * attempt)
    return None


# ----------------------------------------------------------------------------
# 1) سعر BTC التاريخي — CoinGecko (مجاني، بدون مفتاح)
# ----------------------------------------------------------------------------
def fetch_btc_price_history(days: int = config.HISTORY_DAYS_DEFAULT) -> pd.DataFrame:
    """
    يرجع DataFrame بعمودين: date, btc_price
    المصدر: CoinGecko /coins/{id}/market_chart
    """
    url = f"{config.COINGECKO_BASE}/coins/{config.REFERENCE_COIN_ID}/market_chart"
    params = {"vs_currency": "usd", "days": days, "interval": "daily"}
    data = _get_json(url, params)

    if not data or "prices" not in data:
        logger.error("تعذّر جلب سعر BTC من CoinGecko — سيتم استخدام بيانات احتياطية.")
        return _fallback_series(days, "btc_price", base=40000, vol=0.03)

    prices = data["prices"]  # [[timestamp_ms, price], ...]
    df = pd.DataFrame(prices, columns=["ts", "btc_price"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.date
    df = df.drop(columns=["ts"]).drop_duplicates(subset="date", keep="last")
    df["date"] = pd.to_datetime(df["date"])
    return df.reset_index(drop=True)


def fetch_btc_market_data(days: int = config.HISTORY_DAYS_DEFAULT) -> pd.DataFrame:
    """
    يرجع DataFrame بأعمدة: date, btc_price, btc_volume, btc_market_cap
    يُستخدم أيضاً لحساب بروكسي Exchange Netflow / Balance.
    """
    url = f"{config.COINGECKO_BASE}/coins/{config.REFERENCE_COIN_ID}/market_chart"
    params = {"vs_currency": "usd", "days": days, "interval": "daily"}
    data = _get_json(url, params)

    if not data or "prices" not in data:
        logger.error("تعذّر جلب بيانات السوق من CoinGecko — بيانات احتياطية.")
        fallback = _fallback_series(days, "btc_price", base=40000, vol=0.03)
        fallback["btc_volume"] = np.nan
        fallback["btc_market_cap"] = np.nan
        return fallback

    prices = pd.DataFrame(data.get("prices", []), columns=["ts", "btc_price"])
    volumes = pd.DataFrame(data.get("total_volumes", []), columns=["ts", "btc_volume"])
    mcaps = pd.DataFrame(data.get("market_caps", []), columns=["ts", "btc_market_cap"])

    for d in (prices, volumes, mcaps):
        d["date"] = pd.to_datetime(d["ts"], unit="ms").dt.date

    merged = prices.merge(volumes[["date", "btc_volume"]], on="date", how="left")
    merged = merged.merge(mcaps[["date", "btc_market_cap"]], on="date", how="left")
    merged = merged.drop(columns=["ts"]).drop_duplicates(subset="date", keep="last")
    merged["date"] = pd.to_datetime(merged["date"])
    return merged.reset_index(drop=True)


# ----------------------------------------------------------------------------
# 2) معروض الستيبل كوين العالمي — DeFiLlama (مجاني، بدون مفتاح)
# ----------------------------------------------------------------------------
def fetch_stablecoin_supply_history(days: int = config.HISTORY_DAYS_DEFAULT) -> pd.DataFrame:
    """
    يرجع DataFrame بعمودين: date, stablecoin_supply (بالدولار)
    المصدر: DeFiLlama /stablecoincharts/all
    هذا هو المصدر الأساسي لكل من:
      - stablecoin_inflows  (تغيّر قصير المدى / 7 أيام)
      - stablecoin_supply   (اتجاه طويل المدى / 90 يوم)
    """
    url = f"{config.DEFILLAMA_STABLECOINS_BASE}/stablecoincharts/all"
    data = _get_json(url)

    if not data:
        logger.error("تعذّر جلب بيانات الستيبل كوين من DeFiLlama — بيانات احتياطية.")
        return _fallback_series(days, "stablecoin_supply", base=1.5e11, vol=0.005)

    df = pd.DataFrame(data)
    # الحقل المرجعي في DeFiLlama غالباً "totalCirculating": {"peggedUSD": value}
    if "totalCirculating" in df.columns:
        df["stablecoin_supply"] = df["totalCirculating"].apply(
            lambda x: x.get("peggedUSD") if isinstance(x, dict) else np.nan
        )
    elif "totalCirculatingUSD" in df.columns:
        df["stablecoin_supply"] = df["totalCirculatingUSD"].apply(
            lambda x: x.get("peggedUSD") if isinstance(x, dict) else np.nan
        )
    else:
        logger.error("شكل بيانات DeFiLlama غير متوقع — بيانات احتياطية.")
        return _fallback_series(days, "stablecoin_supply", base=1.5e11, vol=0.005)

    df["date"] = pd.to_datetime(df["date"].astype(int), unit="s")
    df = df[["date", "stablecoin_supply"]].dropna()
    df = df.sort_values("date").drop_duplicates(subset="date", keep="last")

    cutoff = df["date"].max() - pd.Timedelta(days=days)
    df = df[df["date"] >= cutoff].reset_index(drop=True)
    return df


# ----------------------------------------------------------------------------
# 3) Exchange Netflow / Exchange Balance لـ BTC
# ----------------------------------------------------------------------------
def fetch_btc_exchange_metrics(days: int = config.HISTORY_DAYS_DEFAULT) -> pd.DataFrame:
    """
    يرجع DataFrame بأعمدة: date, btc_exchange_netflow, btc_exchange_balance, is_proxy

    الوضع الحقيقي (Real Mode):
        إذا تم ضبط CRYPTOQUANT_API_KEY أو GLASSNODE_API_KEY في config.py
        يتم استدعاء المزود الحقيقي هنا (نقطة الاستبدال الوحيدة في الكود).

    الوضع التقريبي (Proxy Mode) — الافتراضي المجاني 100%:
        لا يوجد مصدر مجاني موثوق لرصيد/تدفقات BTC داخل المنصات، لذلك نبني
        تقديراً معقولاً اعتماداً على بيانات مجانية متاحة من CoinGecko:
          - نستخدم "حجم التداول اليومي" و"التقلب اليومي للسعر" كمؤشر نشاط.
          - Netflow Proxy = التغيّر النسبي في (حجم التداول / القيمة السوقية)
            مع وزن سالب عندما يرتفع السعر (منطق: ارتفاع نسبة الحجم للسعر
            بعد صعود قوي غالباً يرافقه جني أرباح/إيداع للبيع = Netflow موجب).
          - Balance Proxy = تكامل تراكمي (cumulative sum) لإشارة الـ Netflow
            المُطبّعة، لتقريب سلوك "الرصيد المتراكم داخل المنصات".
        هذا تقدير وليس بيانات on-chain حقيقية، ويظهر بوضوح في الواجهة
        كـ "Proxy Mode" حتى لا يُفهم كبيانات دقيقة.
    """
    if config.CRYPTOQUANT_API_KEY or config.GLASSNODE_API_KEY:
        try:
            return _fetch_real_exchange_metrics(days)
        except Exception as exc:  # noqa: BLE001
            logger.warning("فشل مزود البيانات الحقيقي (%s) — رجوع لـ Proxy Mode.", exc)

    market = fetch_btc_market_data(days)
    if market.empty:
        return _fallback_series(days, "btc_exchange_netflow", base=0, vol=0.02)

    market = market.sort_values("date").reset_index(drop=True)
    market["price_return"] = market["btc_price"].pct_change()
    market["vol_to_mcap"] = market["btc_volume"] / market["btc_market_cap"]
    market["vol_to_mcap_change"] = market["vol_to_mcap"].pct_change()

    # إشارة تقريبية: نشاط تداول متزايد مصحوب بارتفاع سعر => احتمال إيداع للبيع أعلى
    raw_netflow_proxy = (
        market["vol_to_mcap_change"].fillna(0) * np.sign(market["price_return"].fillna(0))
    )
    # تطبيع أولي لجعل القيم في مدى معقول
    raw_netflow_proxy = raw_netflow_proxy.clip(-1, 1) * 1000  # وحدة اصطناعية "BTC تقريبي"

    market["btc_exchange_netflow"] = raw_netflow_proxy
    market["btc_exchange_balance"] = raw_netflow_proxy.cumsum()
    market["is_proxy"] = True

    return market[["date", "btc_exchange_netflow", "btc_exchange_balance", "is_proxy"]]


def _fetch_real_exchange_metrics(days: int) -> pd.DataFrame:
    """
    نقطة الاستبدال بمزود حقيقي (CryptoQuant / Glassnode).
    اترك هذه الدالة كما هي إذا لم تملك مفتاح API — لن يتم استدعاؤها إطلاقاً.
    عند إضافة مفتاح صالح في config.py، عدّل الجسم هنا لاستدعاء الـ endpoint
    المناسب من مزودك (مثال أدناه توضيحي فقط ويحتاج تكييف حسب خطتك).
    """
    raise NotImplementedError(
        "أضف هنا استدعاء API الحقيقي لمزودك (CryptoQuant/Glassnode) "
        "باستخدام config.CRYPTOQUANT_API_KEY أو config.GLASSNODE_API_KEY."
    )


# ----------------------------------------------------------------------------
# أدوات مساعدة
# ----------------------------------------------------------------------------
def _fallback_series(days: int, col_name: str, base: float, vol: float) -> pd.DataFrame:
    """
    بيانات احتياطية اصطناعية (Random Walk) تُستخدم فقط إذا فشل الاتصال بكل
    مصادر البيانات، حتى لا تتعطل لوحة التحكم بالكامل. يظهر تحذير واضح
    في الواجهة عند استخدامها.
    """
    logger.warning("استخدام بيانات احتياطية اصطناعية لعمود: %s", col_name)
    rng = np.random.default_rng(42)
    dates = pd.date_range(end=datetime.now(timezone.utc).date(), periods=days, freq="D")
    steps = rng.normal(0, vol, size=days)
    series = base * np.exp(np.cumsum(steps))
    df = pd.DataFrame({"date": dates, col_name: series})
    df["is_fallback"] = True
    return df


def get_last_update_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
