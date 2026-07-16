"""Feishu collaboration adapter: cards, idempotent Bitable sync and commands."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .models import OrderSnapshot, SalesAlert


class FeishuError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None):
        super().__init__(message)
        self.code = code


class ProductAnalyzer(Protocol):
    async def analyze(self, query: str, *, operator_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class FeishuCommand:
    name: str
    argument: str
    operator_id: str
    chat_id: str


class FeishuBusinessHub:
    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        verification_token: str = "",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.verification_token = verification_token
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5))
        self._owns_http = http is None
        self._token = ""
        self._token_expiry = 0.0
        self._token_lock = asyncio.Lock()

    async def __aenter__(self) -> "FeishuBusinessHub":
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_http:
            await self.http.aclose()

    async def tenant_token(self) -> str:
        if self._token and time.monotonic() < self._token_expiry - 60:
            return self._token
        async with self._token_lock:
            if self._token and time.monotonic() < self._token_expiry - 60:
                return self._token
            response = await self.http.post(
                f"{self.BASE_URL}/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            response.raise_for_status()
            data = response.json()
            self._ensure_success(data, "tenant token")
            self._token = str(data["tenant_access_token"])
            self._token_expiry = time.monotonic() + int(data.get("expire", 7200))
            return self._token

    async def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {await self.tenant_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    @staticmethod
    def _ensure_success(payload: dict[str, Any], operation: str) -> None:
        if payload.get("code", 0) != 0:
            raise FeishuError(
                f"Feishu {operation} failed: {payload.get('msg', 'unknown error')}",
                code=payload.get("code"),
            )

    @staticmethod
    def sales_alert_card(alert: SalesAlert) -> dict[str, Any]:
        if alert.days_of_cover <= 7:
            template, level = "red", "紧急"
        elif alert.change_ratio <= -0.2:
            template, level = "orange", "关注"
        else:
            template, level = "blue", "提示"
        acos = "—" if alert.acos is None else f"{alert.acos:.1%}"
        return {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {
                "template": template,
                "title": {"tag": "plain_text", "content": f"Amazon DE 运营{level} · {alert.sku}"},
            },
            "elements": [
                {
                    "tag": "div",
                    "fields": [
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**日期**\n{alert.metric_date}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**销售额**\n€{alert.revenue_eur:,.2f}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**环比**\n{alert.change_ratio:+.1%}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**ACOS**\n{acos}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**可售天数**\n{alert.days_of_cover} 天"}},
                    ],
                },
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**触发原因**\n{alert.reason}"}},
                {
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": f"事件键 {alert.source_key} · 建议仅供参考，动作需人工审批"}],
                },
            ],
        }

    async def send_card(self, chat_id: str, card: dict[str, Any]) -> str:
        response = await self.http.post(
            f"{self.BASE_URL}/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers=await self._headers(),
            json={
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            },
        )
        response.raise_for_status()
        data = response.json()
        self._ensure_success(data, "send card")
        return str(data.get("data", {}).get("message_id", ""))

    async def _search_record(
        self, app_token: str, table_id: str, field_name: str, value: str
    ) -> str | None:
        response = await self.http.post(
            f"{self.BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/records/search",
            headers=await self._headers(),
            json={
                "filter": {
                    "conjunction": "and",
                    "conditions": [
                        {"field_name": field_name, "operator": "is", "value": [value]}
                    ],
                },
                "page_size": 1,
            },
        )
        response.raise_for_status()
        data = response.json()
        self._ensure_success(data, "search Bitable record")
        items = data.get("data", {}).get("items", [])
        return str(items[0]["record_id"]) if items else None

    async def upsert_record(
        self,
        app_token: str,
        table_id: str,
        *,
        idempotency_field: str,
        idempotency_value: str,
        fields: dict[str, Any],
    ) -> str:
        record_id = await self._search_record(
            app_token, table_id, idempotency_field, idempotency_value
        )
        base = f"{self.BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        method, url = ("PUT", f"{base}/{record_id}") if record_id else ("POST", base)
        response = await self.http.request(
            method,
            url,
            headers=await self._headers(),
            json={"fields": {**fields, idempotency_field: idempotency_value}},
        )
        response.raise_for_status()
        data = response.json()
        self._ensure_success(data, "upsert Bitable record")
        return str(data.get("data", {}).get("record", {}).get("record_id", record_id or ""))

    async def sync_order(self, app_token: str, table_id: str, order: OrderSnapshot) -> str:
        return await self.upsert_record(
            app_token,
            table_id,
            idempotency_field="AmazonOrderId",
            idempotency_value=order.amazon_order_id,
            fields={
                "订单状态": order.status,
                "下单时间": order.purchase_date,
                "订单金额": order.order_total,
                "币种": order.currency,
                "MarketplaceId": order.marketplace_id,
            },
        )

    async def publish_alert(
        self, chat_id: str, app_token: str, table_id: str, alert: SalesAlert
    ) -> tuple[str, str]:
        record_id = await self.upsert_record(
            app_token,
            table_id,
            idempotency_field="source_key",
            idempotency_value=alert.source_key,
            fields={
                "SKU": alert.sku,
                "指标日期": alert.metric_date.isoformat(),
                "销售额EUR": alert.revenue_eur,
                "环比": alert.change_ratio,
                "ACOS": alert.acos,
                "可售天数": alert.days_of_cover,
                "触发原因": alert.reason,
                "状态": "待人工处理",
            },
        )
        message_id = await self.send_card(chat_id, self.sales_alert_card(alert))
        return record_id, message_id

    def parse_command(self, event: dict[str, Any]) -> FeishuCommand | None:
        if event.get("type") == "url_verification":
            return None
        header = event.get("header", {})
        if self.verification_token and header.get("token") != self.verification_token:
            raise FeishuError("event verification token mismatch")
        body = event.get("event", {})
        message = body.get("message", {})
        if message.get("message_type") != "text":
            return None
        try:
            text = json.loads(message.get("content", "{}"))["text"].strip()
        except (ValueError, KeyError, TypeError) as exc:
            raise FeishuError("invalid text event payload") from exc
        text = text.replace("@_user_1", "").strip()
        if not text.startswith("/"):
            return None
        command, _, argument = text.partition(" ")
        return FeishuCommand(
            name=command.removeprefix("/").casefold(),
            argument=argument.strip(),
            operator_id=str(body.get("sender", {}).get("sender_id", {}).get("open_id", "")),
            chat_id=str(message.get("chat_id", "")),
        )

    async def handle_event(
        self, event: dict[str, Any], analyzer: ProductAnalyzer
    ) -> dict[str, Any]:
        if event.get("type") == "url_verification":
            return {"challenge": event.get("challenge", "")}
        command = self.parse_command(event)
        if command is None:
            return {"ok": True, "ignored": True}
        if command.name not in {"选品", "product"} or not command.argument:
            await self.send_card(command.chat_id, self._help_card())
            return {"ok": True, "command": "help"}
        result = await analyzer.analyze(command.argument, operator_id=command.operator_id)
        await self.send_card(command.chat_id, self._analysis_card(command.argument, result))
        return {"ok": True, "command": "product", "trace_id": result.get("trace_id")}

    @staticmethod
    def _help_card() -> dict[str, Any]:
        return {
            "header": {"template": "blue", "title": {"tag": "plain_text", "content": "AI 运营助手"}},
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "命令：`/选品 关键词或 ASIN`\n所有建议均需人工复核。"}}],
        }

    @staticmethod
    def _analysis_card(query: str, result: dict[str, Any]) -> dict[str, Any]:
        summary = str(result.get("summary", "暂无结论"))[:3000]
        trace_id = str(result.get("trace_id", "unknown"))
        return {
            "header": {"template": "purple", "title": {"tag": "plain_text", "content": f"AI 选品分析 · {query[:40]}"}},
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": summary}},
                {"tag": "note", "elements": [{"tag": "plain_text", "content": f"trace_id={trace_id} · 数据有时效性，决策需人工审批"}]},
            ],
        }
