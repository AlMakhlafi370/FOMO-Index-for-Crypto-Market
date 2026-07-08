# -*- coding: utf-8 -*-
"""
data_providers/stablecoin_inflows.py
======================================
مزودو بيانات "Stablecoin Exchange Inflows" — أي كمية العملات المستقرة
(USDT, USDC, ...) التي تدخل فعلياً منصات التداول (Binance, Bybit, OKX,
Coinbase, Kraken, ...). هذا هو المكوّن الأهم في FOMO Index لأنه يمثل
"أموال جاهزة للشراء" مباشرة.

لماذا ليس Stablecoin Total Supply؟
  زيادة معروض USDT العالمي (إصدار جديد من Tether) لا تعني أن هذه الأموال
  دخلت منصات التداول فعلاً — قد تبقى في محافظ خاصة أو عقود DeFi لأسابيع.
  لذلك تم فصل هذا المكوّن تماماً عن Stablecoin Supply (الذي بقي كمكوّن
  سياقي منفصل بوزن منخفض جداً في config.py).

ترتيب المزودين حسب الدقة (الأفضل أولاً):
  1. PaidStablecoinInflowProvider   — CryptoQuant / Glassnode / Nansen / Arkham
                                       (بيانات on-chain حقيقية على مستوى
                                       محافظ المنصات المعروفة). يتطلب مفتاح مدفوع.
  2. WhaleAlertProvider             — بيانات معاملات حقيقية (ليست تقديرية)
                                       من Whale Alert، لكنها محدودة بعتبة
                                       الحد الأدنى للمعاملة الكبيرة، وتحتاج
                                       مفتاح API مجاني (تسجيل بسيط بدون دفع).
  3. CoinGeckoExchangeActivityProxy — الخيار الافتراضي بدون أي تسجيل: تقدير
                                       مبني على تغيّر حجم تداول USDT+USDC
                                       الحقيقي (من CoinGecko) كبديل مجاني
                                       100% دون أي مفتاح.

يتم اختيار أفضل مزود متاح تلقائياً عبر get_stablecoin_inflow_provider().
"""

from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np
import pandas as pd

import config
from .base import DataProvider
from .http_utils import get_json, fallback_series

logger = logging.getLogger("fomo_index.data_providers.stablecoin_inflows")

STABLECOIN_IDS = {
    "tether": "USDT",
    "usd-coin": "USDC",
}

KNOWN_EXCHANGES = ["binance", "bybit", "okx", "coinbase", "kraken"]


# ----------------------------------------------------------------------------
# 1) المزود المدفوع (نقطة الاستبدال بمزود دقيق لاحقاً)
# ----------------------------------------------------------------------------
class PaidStablecoinInflowProvider(DataProvider):
    """
    نقطة الاستبدال الوحيدة عند توفر اشتراك حقيقي.
    مثال على المزودين المتوافقين مع هذه الواجهة: CryptoQuant, Glassnode,
    Nansen, Arkham. عدّل الجسم هنا لاستدعاء الـ endpoint المناسب لمزودك،
    ويجب أن يرجع DataFrame بعمودين: date, stablecoin_exchange_inflow
    (بوحدة الدولار، صافي التدفق اليومي = دخول - خروج من المنصات).
    """

    name = "paid_provider"
    requires_key = True
    is_estimate = False

    def available(self) -> bool:
        return bool(
            config.CRYPTOQUANT_API_KEY
            or config.GLASSNODE_API_KEY
            or config.NANSEN_API_KEY
            or config.ARKHAM_API_KEY
        )

    def fetch(self, days: int) -> pd.DataFrame:
        raise NotImplementedError(
            "أضف هنا استدعاء API الحقيقي لمزودك (CryptoQuant/Glassnode/Nansen/"
            "Arkham) باستخدام المفتاح المضبوط في config.py. يجب أن يرجع "
            "DataFrame بعمودي date, stablecoin_exchange_inflow."
        )


# ----------------------------------------------------------------------------
# 2) Whale Alert — بيانات معاملات حقيقية (تحتاج مفتاح مجاني)
# ----------------------------------------------------------------------------
class WhaleAlertProvider(DataProvider):
    """
    Whale Alert (https://whale-alert.io) يوفر واجهة REST مجانية (بعد تسجيل
    بسيط بدون دفع للحصول على مفتاح) لمعاملات العملات الرقمية الكبيرة،
    وتتضمن حقل "owner_type" الذي يحدد إن كانت الجهة المُرسِلة/المُستقبِلة
    "exchange". هذا يسمح بحساب:
        Net Stablecoin Exchange Inflow = (تحويلات إلى منصات) - (تحويلات من منصات)
    وهي بيانات معاملات حقيقية (ليست تقديراً)، لكن القيود:
      - الخطة المجانية تراقب فقط المعاملات الكبيرة (فوق عتبة معينة).
      - نافذة الاستعلام التاريخي للخطة المجانية محدودة (عادة ساعات قليلة
        إلى بضعة أيام للخلف، وليست سنة كاملة)، لذلك هذا المزود مناسب أكثر
        للتشغيل المستمر (يجمع بيانات يومياً ويخزنها) أكثر من الرجوع
        لتاريخ طويل دفعة واحدة.
    """

    name = "whale_alert"
    requires_key = True
    is_estimate = False

    BASE_URL = "https://api.whale-alert.io/v1/transactions"

    def available(self) -> bool:
        return bool(config.WHALE_ALERT_API_KEY)

    def fetch(self, days: int) -> pd.DataFrame:
        import time as _time

        end = int(_time.time())
        start = end - min(days, 30) * 86400  # القيد الزمني للخطة المجانية عادة قصير
        params = {
            "api_key": config.WHALE_ALERT_API_KEY,
            "start": start,
            "end": end,
            "min_value": config.WHALE_ALERT_MIN_USD,
            "currency": "usdt",  # يُستدعى مرة أخرى لكل عملة مستقرة عند الحاجة
        }
        data = get_json(self.BASE_URL, params=params)
        if not data or "transactions" not in data:
            raise RuntimeError("Whale Alert: لا توجد استجابة صالحة.")

        rows = []
        for tx in data["transactions"]:
            date = pd.to_datetime(tx["timestamp"], unit="s").normalize()
            amount_usd = tx.get("amount_usd", 0)
            to_type = tx.get("to", {}).get("owner_type")
            from_type = tx.get("from", {}).get("owner_type")
            flow = 0.0
            if to_type == "exchange":
                flow += amount_usd
            if from_type == "exchange":
                flow -= amount_usd
            rows.append({"date": date, "flow": flow})

        if not rows:
            raise RuntimeError("Whale Alert: لم يتم رصد معاملات ضمن النطاق الزمني.")

        df = pd.DataFrame(rows).groupby("date", as_index=False)["flow"].sum()
        df = df.rename(columns={"flow": "stablecoin_exchange_inflow"})
        df["is_estimate"] = False
        return df


# ----------------------------------------------------------------------------
# 3) CoinGecko Proxy — الخيار الافتراضي (مجاني 100%، بدون أي تسجيل)
# ----------------------------------------------------------------------------
class CoinGeckoExchangeActivityProxyProvider(DataProvider):
    """
    البديل المجاني الافتراضي بدون أي مفتاح API.

    الفكرة: بدل قياس "المعروض العالمي" (الذي لا يعكس الدخول الفعلي
    للمنصات)، نقيس **حجم التداول اليومي الفعلي** لأكبر عملتين مستقرتين
    (USDT, USDC) كما تُبلّغه المنصات لـ CoinGecko. حجم التداول هو نشاط
    يحدث *داخل* المنصات حصراً (على عكس المعروض الذي قد يكون خارجها)،
    لذلك هو أقرب مفهومياً لـ "أموال تدخل/تتحرك داخل المنصات" من معروض
    الستيبل كوين الكلي، رغم أنه لا يزال بروكسي (ليس بيانات محافظ حقيقية).

    Net Inflow Proxy (يومي) = التغيّر المطلق في (حجم تداول USDT + USDC)
    مقارنة بمتوسطها المتحرك، بحيث ترتفع القيمة عندما يتضاعف النشاط
    التداولي على الستيبل كوين بشكل غير اعتيادي (إشارة على ضخ سيولة
    جديدة للشراء داخل المنصات).
    """

    name = "coingecko_proxy"
    requires_key = False
    is_estimate = True

    def available(self) -> bool:
        return True  # لا يحتاج أي إعداد — يعمل دائماً كخط أخير

    def fetch(self, days: int) -> pd.DataFrame:
        volumes = []
        for coin_id in STABLECOIN_IDS:
            url = f"{config.COINGECKO_BASE}/coins/{coin_id}/market_chart"
            data = get_json(url, params={"vs_currency": "usd", "days": days, "interval": "daily"})
            if not data or "total_volumes" not in data:
                logger.warning("تعذّر جلب حجم تداول %s من CoinGecko.", coin_id)
                continue
            vdf = pd.DataFrame(data["total_volumes"], columns=["ts", f"vol_{coin_id}"])
            vdf["date"] = pd.to_datetime(vdf["ts"], unit="ms").dt.date
            vdf["date"] = pd.to_datetime(vdf["date"])
            vdf = vdf.drop(columns=["ts"]).drop_duplicates(subset="date", keep="last")
            volumes.append(vdf.set_index("date")[f"vol_{coin_id}"])

        if not volumes:
            logger.error("تعذّر جلب أي حجم تداول للستيبل كوين — بيانات احتياطية.")
            fb = fallback_series(days, "stablecoin_exchange_inflow", base=0, vol=0.05)
            fb["is_estimate"] = True
            return fb

        combined = pd.concat(volumes, axis=1).sum(axis=1).rename("total_volume")
        combined = combined.sort_index()

        # التدفق التقديري = الانحراف عن المتوسط المتحرك (نشاط غير اعتيادي = ضخ سيولة)
        rolling_mean = combined.rolling(window=14, min_periods=3).mean()
        proxy_flow = (combined - rolling_mean).fillna(0)

        df = proxy_flow.reset_index()
        df.columns = ["date", "stablecoin_exchange_inflow"]
        df["is_estimate"] = True
        return df


# ----------------------------------------------------------------------------
# اختيار أفضل مزود متاح تلقائياً (Provider Factory)
# ----------------------------------------------------------------------------
def get_stablecoin_inflow_providers() -> List[DataProvider]:
    """
    يرجع كل المزودين *المتاحين حالياً* مرتبين من الأدق للأقل دقة:
    مدفوع (إن وُجد مفتاح) -> Whale Alert (إن وُجد مفتاح مجاني) ->
    CoinGecko Proxy (افتراضي متاح دائماً بدون أي إعداد).

    الاستدعاء (في data_sources.py) يجرّب كل مزود بالترتيب، وينتقل للتالي
    تلقائياً إذا فشل الاتصال أو رمى استثناء (Graceful Degradation)،
    فتبقى اللوحة تعمل دوماً حتى بدون أي مفتاح API.
    """
    candidates: List[DataProvider] = [
        PaidStablecoinInflowProvider(),
        WhaleAlertProvider(),
        CoinGeckoExchangeActivityProxyProvider(),
    ]
    return [p for p in candidates if p.available()]
