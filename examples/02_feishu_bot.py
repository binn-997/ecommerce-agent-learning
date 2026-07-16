"""Render the Feishu sales alert card without credentials or network calls."""

import json
from datetime import date

from amazon_ai_platform.feishu import FeishuBusinessHub
from amazon_ai_platform.models import SalesAlert


alert = SalesAlert(
    source_key="low-stock:DE-CARPET-001:2026-07-16",
    sku="DE-CARPET-001",
    metric_date=date(2026, 7, 16),
    revenue_eur=1250.50,
    change_ratio=-0.23,
    acos=0.287,
    days_of_cover=6,
    reason="库存覆盖不足 7 天，且销售额较前一周期下降 23%",
)

print(json.dumps(FeishuBusinessHub.sales_alert_card(alert), ensure_ascii=False, indent=2))
