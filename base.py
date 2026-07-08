# -*- coding: utf-8 -*-
"""
data_providers/base.py
========================
واجهة موحدة (Abstract Base Class) لكل مزودي البيانات في المشروع.

الهدف: أي مكوّن في المؤشر (Stablecoin Exchange Inflows, BTC Exchange
Netflow, ...) يمكن أن يُغذّى من أكثر من مصدر بيانات (مجاني تقريبي، مجاني
حقيقي محدود، أو مدفوع دقيق). كل مزود يلتزم بنفس الواجهة، بحيث يستطيع
data_sources.py استبدال المزود دون أي تعديل على fomo_index.py أو app.py.

كل مزود يعلن عن نفسه:
    name            : اسم تعريفي يظهر في الواجهة
    requires_key    : هل يحتاج مفتاح API؟
    is_estimate     : هل الناتج تقدير/بروكسي أم بيانات حقيقية مباشرة؟
    available()     : هل المزود جاهز للاستخدام الآن (مثلاً هل المفتاح مضبوط)؟
    fetch(days)     : يرجع DataFrame بالعمود/الأعمدة المتفق عليها + عمود date
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import pandas as pd


class DataProvider(ABC):
    name: str = "base_provider"
    requires_key: bool = False
    is_estimate: bool = True  # True إذا كانت البيانات تقديرية/بروكسي وليست ground-truth

    def available(self) -> bool:
        """هل يمكن استخدام هذا المزود الآن؟ (مثلاً: هل المفتاح مضبوط في config.py)."""
        return True

    @abstractmethod
    def fetch(self, days: int) -> pd.DataFrame:
        """يرجع DataFrame يحتوي عمود date بالإضافة لأعمدة البيانات الخاصة بالمزود."""
        raise NotImplementedError
