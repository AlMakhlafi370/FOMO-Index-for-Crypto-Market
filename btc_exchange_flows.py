# -*- coding: utf-8 -*-
"""
data_providers/btc_exchange_flows.py
======================================
مزودو بيانات BTC Exchange Netflow / Exchange Balance.
نفس منطق الإصدار السابق لكن مُعاد تنظيمه ضمن طبقة Data Provider الموحّدة
(الملف base.py) بحيث يتبع نفس نمط stablecoin_inflows.py، ويسهل استبداله
لاحقاً بمزود مدفوع دون تعديل أي كود آخر في المشروع.
"""

from __future__ import annotations

import logging
from typing import List

import numpy as np
import pandas as pd

import config
from .base import DataProvider
from .http_utils import fallback_series

logger = logging.getLogger("fomo_index.data_providers.btc_exchange_flows")


# ----------------------------------------------------------------------------
# 1) المزود المدفوع (نقطة الاستبدال بمزود دقيق لاحقاً)
# ----------------------------------------------------------------------------
class PaidBTCExchangeFlowProvider(DataProvider):
    """
    نقطة الاستبدال بمزود on-chain حقيقي (CryptoQuant/Glassnode/Nansen/Arkham)
    لبيانات BTC Exchange Netflow / Exchange Balance الفعلية.
    يجب أن يرجع fetch() عمود date + btc_exchange_netflow + btc_exchange_balance.
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
            "Arkham) باستخدام المفتاح المضبوط في config.py."
        )


# ----------------------------------------------------------------------------
# 2) CoinGecko Proxy — الخيار الافتراضي (مجاني 100%، بدون أي تسجيل)
# ----------------------------------------------------------------------------
class CoinGeckoBTCFlowProxyProvider(DataProvider):
    """
    لا يوجد مصدر مجاني موثوق لرصيد/تدفقات BTC داخل المنصات بدون مفتاح،
    لذلك نبني تقديراً من بيانات حجم التداول والسعر المتاحة مجاناً من
    CoinGecko (نفس منهجية الإصدار السابق من المشروع، بدون تغيير).
    """

    name = "coingecko_proxy"
    requires_key = False
    is_estimate = True

    def available(self) -> bool:
        return True

    def fetch(self, days: int, market_df: pd.DataFrame) -> pd.DataFrame:
        if market_df.empty:
            fb = fallback_series(days, "btc_exchange_netflow", base=0, vol=0.02)
            fb["btc_exchange_balance"] = fb["btc_exchange_netflow"].cumsum()
            fb["is_estimate"] = True
            return fb

        market = market_df.sort_values("date").reset_index(drop=True).copy()
        market["price_return"] = market["btc_price"].pct_change()
        market["vol_to_mcap"] = market["btc_volume"] / market["btc_market_cap"]
        market["vol_to_mcap_change"] = market["vol_to_mcap"].pct_change()

        raw_netflow_proxy = (
            market["vol_to_mcap_change"].fillna(0) * np.sign(market["price_return"].fillna(0))
        )
        raw_netflow_proxy = raw_netflow_proxy.clip(-1, 1) * 1000

        out = pd.DataFrame({
            "date": market["date"],
            "btc_exchange_netflow": raw_netflow_proxy,
        })
        out["btc_exchange_balance"] = out["btc_exchange_netflow"].cumsum()
        out["is_estimate"] = True
        return out


def get_btc_exchange_flow_providers() -> List[DataProvider]:
    """أفضل المزودين المتاحين حالياً، من الأدق للأقل دقة."""
    candidates: List[DataProvider] = [
        PaidBTCExchangeFlowProvider(),
        CoinGeckoBTCFlowProxyProvider(),
    ]
    return [p for p in candidates if p.available()]
