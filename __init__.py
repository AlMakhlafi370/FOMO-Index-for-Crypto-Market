# -*- coding: utf-8 -*-
"""
data_providers
==============
طبقة مزودي البيانات القابلة للتوسعة لمشروع FOMO Index.
كل مصدر بيانات "قابل للاستبدال" (Stablecoin Exchange Inflows، BTC Exchange
Netflow/Balance) له وحدته الخاصة هنا، مبنية على واجهة موحدة (base.DataProvider)
حتى يسهل إضافة مزود جديد (مجاني أو مدفوع) دون تعديل بقية المشروع.
"""

from .base import DataProvider
from .stablecoin_inflows import get_stablecoin_inflow_providers
from .btc_exchange_flows import get_btc_exchange_flow_providers

__all__ = [
    "DataProvider",
    "get_stablecoin_inflow_providers",
    "get_btc_exchange_flow_providers",
]
