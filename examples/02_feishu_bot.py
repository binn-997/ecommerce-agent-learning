"""Send a Feishu sales card and create a Bitable alert. Run: python 02_feishu_bot.py --demo."""
from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import Any

import httpx
from dotenv import load_dotenv


@dataclass(frozen=True)
class SalesAlert:
    sku: str
    revenue_usd: float
    acos: float
    days_of_cover: int


class FeishuBot:
    def __init__(self, app_id: str, app_secret: str, http: httpx.AsyncClient | None = None) -> None:
        self.app_id, self.app_secret = app_id, app_secret
        self.http = http or httpx.AsyncClient(timeout=20)
        self._owns_http, self._token = http is None, ""

    async def __aenter__(self) -> "FeishuBot": return self
    async def __aexit__(self, *_: object) -> None:
        if self._owns_http: await self.http.aclose()

    async def _headers(self) -> dict[str, str]:
        if not self._token:
            response = await self.http.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", json={"app_id": self.app_id, "app_secret": self.app_secret})
            response.raise_for_status()
            body = response.json()
            if body.get("code") != 0: raise RuntimeError(f"Feishu token error: {body}")
            self._token = body["tenant_access_token"]
        return {"Authorization": f"Bearer {self._token}"}

    @staticmethod
    def card(alert: SalesAlert) -> dict[str, Any]:
        severity = "red" if alert.days_of_cover < 7 else "orange"
        return {"config": {"wide_screen_mode": True}, "header": {"title": {"tag": "plain_text", "content": "Amazon 销售 / 库存预警"}, "template": severity}, "elements": [
            {"tag": "div", "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**SKU**\\n{alert.sku}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**销售额**\\n${alert.revenue_usd:,.2f}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**ACOS**\\n{alert.acos:.1%}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**可售天数**\\n{alert.days_of_cover} 天"}},
            ]}, {"tag": "note", "elements": [{"tag": "plain_text", "content": "请人工核对在途库存与广告活动后再执行动作。"}]}
        ]}

    async def send_sales_report_card(self, chat_id: str, alert: SalesAlert) -> None:
        response = await self.http.post("https://open.feishu.cn/open-apis/im/v1/messages", params={"receive_id_type": "chat_id"}, headers=await self._headers(), json={"receive_id": chat_id, "msg_type": "interactive", "content": __import__("json").dumps(self.card(alert), ensure_ascii=False)})
        response.raise_for_status()
        if response.json().get("code") != 0: raise RuntimeError(response.text)

    async def create_bitable_alert(self, app_token: str, table_id: str, source_key: str, alert: SalesAlert) -> None:
        fields = {"source_key": source_key, "sku": alert.sku, "revenue_usd": alert.revenue_usd, "acos": alert.acos, "days_of_cover": alert.days_of_cover, "status": "open"}
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        response = await self.http.post(url, headers=await self._headers(), json={"fields": fields})
        response.raise_for_status()
        if response.json().get("code") != 0: raise RuntimeError(response.text)


async def main() -> None:
    load_dotenv(); parser = argparse.ArgumentParser(); parser.add_argument("--demo", action="store_true"); args = parser.parse_args()
    alert = SalesAlert("DE-CARPET-001", 1250.50, 0.287, 6)
    if args.demo:
        print(__import__("json").dumps(FeishuBot.card(alert), ensure_ascii=False, indent=2)); return
    required = ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_CHAT_ID", "FEISHU_BITABLE_APP_TOKEN", "FEISHU_BITABLE_TABLE_ID"]
    if missing := [key for key in required if not os.getenv(key)]: raise SystemExit(f"Missing {', '.join(missing)}. Use --demo or fill .env.")
    async with FeishuBot(os.environ["FEISHU_APP_ID"], os.environ["FEISHU_APP_SECRET"]) as bot:
        source_key = "low-stock:DE-CARPET-001:2026-07-12"
        await bot.create_bitable_alert(os.environ["FEISHU_BITABLE_APP_TOKEN"], os.environ["FEISHU_BITABLE_TABLE_ID"], source_key, alert)
        await bot.send_sales_report_card(os.environ["FEISHU_CHAT_ID"], alert)
    print("Bitable record and sales card sent")


if __name__ == "__main__": asyncio.run(main())
