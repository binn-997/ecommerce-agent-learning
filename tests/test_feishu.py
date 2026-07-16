from __future__ import annotations

import asyncio
from datetime import date

import httpx

import json

import pytest

from amazon_ai_platform.feishu import FeishuBusinessHub, FeishuError
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


def test_forged_event_verification_token_is_rejected() -> None:
    hub = FeishuBusinessHub(
        app_id="id", app_secret="secret", verification_token="expected"
    )
    event = {
        "header": {"token": "forged"},
        "event": {"message": {"message_type": "text", "content": '{"text":"/选品 test"}'}},
    }
    with pytest.raises(FeishuError, match="verification token mismatch"):
        hub.parse_command(event)


def test_product_command_sends_ack_before_analysis() -> None:
    events: list[str] = []

    class Hub(FeishuBusinessHub):
        async def send_card(self, chat_id, card):
            events.append(card["header"]["title"]["content"])
            return "message"

    class Analyzer:
        async def analyze(self, query, *, operator_id):
            events.append("analyze")
            return {"summary": "synthetic", "trace_id": "trace-feishu-1"}

    hub = Hub(app_id="id", app_secret="secret", verification_token="expected")
    event = {
        "header": {"token": "expected"},
        "event": {
            "sender": {"sender_id": {"open_id": "operator"}},
            "message": {
                "message_type": "text",
                "content": json.dumps({"text": "/选品 Hundeteppich"}),
                "chat_id": "chat",
            },
        },
    }
    result = run(hub.handle_event(event, Analyzer()))
    assert events == ["已接收选品分析", "analyze", "AI 选品分析 · Hundeteppich"]
    assert result["trace_id"] == "trace-feishu-1"


def test_duplicate_alert_only_updates_record_without_second_notification() -> None:
    class Hub(FeishuBusinessHub):
        async def upsert_record(self, *args, **kwargs):
            return "record-1"

        async def send_card(self, chat_id, card):
            self.sent = getattr(self, "sent", 0) + 1
            return f"message-{self.sent}"

    alert = SalesAlert(
        source_key="synthetic-alert", sku="SYNTHETIC", metric_date=date(2026, 7, 16),
        revenue_eur=100, change_ratio=-0.3, acos=0.2, days_of_cover=5, reason="synthetic",
    )
    hub = Hub(app_id="id", app_secret="secret")

    async def scenario():
        return (
            await hub.publish_alert("chat", "app", "table", alert),
            await hub.publish_alert("chat", "app", "table", alert),
        )

    first, second = run(scenario())
    assert first == ("record-1", "message-1")
    assert second == ("record-1", "")


def test_expired_tenant_token_refreshes_once() -> None:
    token_calls = 0
    message_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, message_calls
        if request.url.path.endswith("/tenant_access_token/internal"):
            token_calls += 1
            return httpx.Response(200, json={
                "code": 0, "tenant_access_token": f"token-{token_calls}", "expire": 7200,
            })
        message_calls += 1
        if message_calls == 1:
            return httpx.Response(200, json={"code": 99991663, "msg": "token expired"})
        assert request.headers["Authorization"] == "Bearer token-2"
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "message-1"}})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await FeishuBusinessHub(
                app_id="id", app_secret="secret", http=http
            ).send_card("chat", {"elements": []})

    assert run(scenario()) == "message-1"
    assert token_calls == 2
    assert message_calls == 2
