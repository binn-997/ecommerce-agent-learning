from __future__ import annotations

import asyncio
from datetime import date

import httpx

from amazon_ai_platform.feishu import FeishuBusinessHub
from amazon_ai_platform.models import OrderSnapshot, SalesAlert


def run(coro):
    return asyncio.run(coro)


def test_alert_card_exposes_business_context_and_manual_boundary() -> None:
    alert = SalesAlert(
        source_key="stock:SKU-1:2026-07-16", sku="SKU-1", metric_date=date(2026, 7, 16),
        revenue_eur=1234.5, change_ratio=-0.25, acos=0.18, days_of_cover=5,
        reason="7 日均销量上升且库存覆盖不足",
    )
    card = FeishuBusinessHub.sales_alert_card(alert)
    assert card["header"]["template"] == "red"
    assert "人工审批" in str(card)
    assert "€1,234.50" in str(card)


def test_order_sync_updates_existing_bitable_record() -> None:
    methods: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token", "expire": 7200})
        methods.append(request.method)
        if request.url.path.endswith("/records/search"):
            return httpx.Response(200, json={"code": 0, "data": {"items": [{"record_id": "rec-1"}]}})
        if request.url.path.endswith("/records/rec-1"):
            return httpx.Response(200, json={"code": 0, "data": {"record": {"record_id": "rec-1"}}})
        raise AssertionError(str(request.url))

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            hub = FeishuBusinessHub(app_id="id", app_secret="secret", http=http)
            return await hub.sync_order("app", "table", OrderSnapshot(
                amazon_order_id="ORDER-1", status="Shipped", purchase_date="2026-07-16T01:00:00Z",
                order_total=59.9, currency="EUR", marketplace_id="A1PA6795UKMFR9",
            ))

    assert run(scenario()) == "rec-1"
    assert methods == ["POST", "PUT"]
