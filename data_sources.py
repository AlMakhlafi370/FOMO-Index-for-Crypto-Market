# -*- coding: utf-8 -*-
"""
data_sources.py
================
طبقة تنسيق (orchestration) فوق data_providers/. هذا الملف لا يحتوي منطق
مزودين تفصيلي بعد الآن (انتقل إلى data_providers/) — بل فقط يستدعي أفضل
مزود متاح لكل بيانات، مع Graceful Degradation (الانتقال للمزود التالي
تلقائياً عند فشل الأول)، ويعيد DataFrame موحّد الشكل لبقية المشروع.

المصادر المستخدمة:
  1. CoinGecko             -> سعر BTC وحجم تداوله (مجاني، بدون مفتاح).
  2. DeFiLlama Stablecoins -> معروض الستيبل كوين العالمي (سياق فقط، وزن منخفض).
  3. data_providers/       -> Stablecoin Exchange Inflows + BTC Exchange
                              Netflow/Balance، عبر طبقة مزودين قابلة للتوسعة
                              (مجاني تلقائي <-> مدفوع عند توفر مفتاح).
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

import config
from data_providers.http_utils import get_json, fallback_series
from data_providers.stablecoin_inflows import get_stablecoin_inflow_providers
from data_providers.btc_exchange_flows import get_btc_exchange_flow_providers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fomo_index.data_sources")


# ----------------------------------------------------------------------------
# 1) سعر BTC التاريخي — CoinGecko (مجاني، بدون مفتاح)
# ----------------------------------------------------------------------------
def fetch_btc_price_history(days: int = config.HISTORY_DAYS_DEFAULT) -> pd.DataFrame:
    """يرجع DataFrame بعمودين: date, btc_price"""
    url = f"{config.COINGECKO_BASE}/coins/{config.REFERENCE_COIN_ID}/market_chart"
    params = {"vs_currency": "usd", "days": days, "interval": "daily"}
    data = get_json(url, params)

    if not data or "prices" not in data:
        logger.error("تعذّر جلب سعر BTC من CoinGecko — سيتم استخدام بيانات احتياطية.")
        return fallback_series(days, "btc_price", base=40000, vol=0.03)

    prices = data["prices"]
    df = pd.DataFrame(prices, columns=["ts", "btc_price"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.date
    df = df.drop(columns=["ts"]).drop_duplicates(subset="date", keep="last")
    df["date"] = pd.to_datetime(df["date"])
    return df.reset_index(drop=True)


def fetch_btc_market_data(days: int = config.HISTORY_DAYS_DEFAULT) -> pd.DataFrame:
    """يرجع DataFrame بأعمدة: date, btc_price, btc_volume, btc_market_cap"""
    url = f"{config.COINGECKO_BASE}/coins/{config.REFERENCE_COIN_ID}/market_chart"
    params = {"vs_currency": "usd", "days": days, "interval": "daily"}
    data = get_json(url, params)

    if not data or "prices" not in data:
        logger.error("تعذّر جلب بيانات السوق من CoinGecko — بيانات احتياطية.")
        fallback = fallback_series(days, "btc_price", base=40000, vol=0.03)
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
# 2) معروض الستيبل كوين العالمي — DeFiLlama (سياق فقط، وزن منخفض 10%)
# ----------------------------------------------------------------------------
def fetch_stablecoin_supply_history(days: int = config.HISTORY_DAYS_DEFAULT) -> pd.DataFrame:
    """
    يرجع DataFrame بعمودين: date, stablecoin_supply (بالدولار)

    ⚠️ ملاحظة فلسفية مهمة: هذا المكوّن يقيس *نمو المعروض العالمي* للستيبل
    كوين فقط (سياق كلي)، وليس دخول الأموال الفعلي لمنصات التداول — تلك
    وظيفة data_providers/stablecoin_inflows.py حصرياً. لهذا السبب وزنه
    منخفض عمداً (10%) في config.COMPONENT_WEIGHTS.
    """
    url = f"{config.DEFILLAMA_STABLECOINS_BASE}/stablecoincharts/all"
    data = get_json(url)

    if not data:
        logger.error("تعذّر جلب بيانات الستيبل كوين من DeFiLlama — بيانات احتياطية.")
        return fallback_series(days, "stablecoin_supply", base=1.5e11, vol=0.005)

    df = pd.DataFrame(data)
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
        return fallback_series(days, "stablecoin_supply", base=1.5e11, vol=0.005)

    df["date"] = pd.to_datetime(df["date"].astype(int), unit="s")
    df = df[["date", "stablecoin_supply"]].dropna()
    df = df.sort_values("date").drop_duplicates(subset="date", keep="last")

    cutoff = df["date"].max() - pd.Timedelta(days=days)
    df = df[df["date"] >= cutoff].reset_index(drop=True)
    return df


# ----------------------------------------------------------------------------
# 3) Stablecoin Exchange Inflows — المكوّن الأهم (50%)
# ----------------------------------------------------------------------------
def fetch_stablecoin_exchange_inflows(days: int = config.HISTORY_DAYS_DEFAULT) -> pd.DataFrame:
    """
    يرجع DataFrame: date, stablecoin_exchange_inflow, is_estimate, provider

    يجرّب كل مزود متاح بالترتيب (مدفوع دقيق -> Whale Alert -> CoinGecko
    Proxy) وينتقل تلقائياً للتالي عند أي فشل (Graceful Degradation).
    """
    providers = get_stablecoin_inflow_providers()
    for provider in providers:
        try:
            df = provider.fetch(days)
            df["provider"] = provider.name
            if "is_estimate" not in df.columns:
                df["is_estimate"] = provider.is_estimate
            logger.info("Stablecoin Exchange Inflows: تم الجلب عبر %s (proxy=%s)", provider.name, provider.is_estimate)
            return df
        except Exception as exc:  # noqa: BLE001
            logger.warning("فشل مزود %s لـ Stablecoin Exchange Inflows: %s — تجربة التالي.", provider.name, exc)
            continue

    logger.error("فشلت كل مزودي Stablecoin Exchange Inflows — بيانات احتياطية.")
    fb = fallback_series(days, "stablecoin_exchange_inflow", base=0, vol=0.05)
    fb["is_estimate"] = True
    fb["provider"] = "fallback"
    return fb


# ----------------------------------------------------------------------------
# 4) BTC Exchange Netflow / Balance
# ----------------------------------------------------------------------------
def fetch_btc_exchange_metrics(days: int = config.HISTORY_DAYS_DEFAULT) -> pd.DataFrame:
    """
    يرجع DataFrame: date, btc_exchange_netflow, btc_exchange_balance, is_estimate, provider
    """
    providers = get_btc_exchange_flow_providers()
    market_df = fetch_btc_market_data(days)  # مطلوب فقط لمزود CoinGecko Proxy

    for provider in providers:
        try:
            if provider.name == "coingecko_proxy":
                df = provider.fetch(days, market_df)
            else:
                df = provider.fetch(days)
            df["provider"] = provider.name
            if "is_estimate" not in df.columns:
                df["is_estimate"] = provider.is_estimate
            logger.info("BTC Exchange Metrics: تم الجلب عبر %s (proxy=%s)", provider.name, provider.is_estimate)
            return df
        except Exception as exc:  # noqa: BLE001
            logger.warning("فشل مزود %s لـ BTC Exchange Metrics: %s — تجربة التالي.", provider.name, exc)
            continue

    logger.error("فشلت كل مزودي BTC Exchange Metrics — بيانات احتياطية.")
    fb = fallback_series(days, "btc_exchange_netflow", base=0, vol=0.02)
    fb["btc_exchange_balance"] = fb["btc_exchange_netflow"].cumsum()
    fb["is_estimate"] = True
    fb["provider"] = "fallback"
    return fb
