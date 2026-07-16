"""Amazon Ads Reporting v3 client and evidence-first anomaly explanation."""

from __future__ import annotations

import asyncio
import gzip
import json
import time
from datetime import date
from decimal import Decimal
from typing import Any, Callable

import httpx
from pydantic import BaseModel, Field

from .models import AdvertisingMetrics, StandardAdvertisingRow


class AdsAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AdsReportFailed(AdsAPIError):
    pass


class AmazonAdsClient:
    RETRYABLE = {429, 500, 502, 503, 504}

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        profile_id: str,
        marketplace_id: str,
        endpoint: str = "https://advertising-api-eu.amazon.com",
        http: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
        max_attempts: int = 4,
    ) -> None:
        if profile_id == marketplace_id:
            raise ValueError("Ads profile_id and marketplace_id are different identifiers")
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.profile_id = profile_id
        self.marketplace_id = marketplace_id
        self.endpoint = endpoint.rstrip("/")
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10))
        self._owns_http = http is None
        self.sleep = sleep
        self.max_attempts = max_attempts
        self._token = ""
        self._token_expiry = 0.0
        self._token_lock = asyncio.Lock()

    async def __aenter__(self) -> "AmazonAdsClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_http:
            await self.http.aclose()

    async def access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expiry - 60:
            return self._token
        async with self._token_lock:
            if self._token and time.monotonic() < self._token_expiry - 60:
                return self._token
            response = await self.http.post(
                "https://api.amazon.com/auth/o2/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
            if response.status_code >= 400:
                raise AdsAPIError("Ads LWA token refresh failed", status_code=response.status_code)
            try:
                payload = response.json()
                self._token = str(payload["access_token"])
                self._token_expiry = time.monotonic() + int(payload.get("expires_in", 3600))
            except (ValueError, KeyError, TypeError) as exc:
                raise AdsAPIError("Ads LWA token response was invalid") from exc
            return self._token

    async def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {await self.access_token()}",
            "Amazon-Advertising-API-ClientId": self.client_id,
            "Amazon-Advertising-API-Scope": self.profile_id,
            "Content-Type": "application/json",
        }

    async def request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        for attempt in range(self.max_attempts):
            try:
                response = await self.http.request(
                    method,
                    f"{self.endpoint}{path}",
                    headers=await self._headers(),
                    json=json_body,
                )
            except httpx.TransportError as exc:
                if attempt + 1 == self.max_attempts:
                    raise AdsAPIError(f"Ads network failure: {type(exc).__name__}") from exc
                await self.sleep(min(2**attempt, 10))
                continue
            if response.status_code < 400:
                return response.json()
            if response.status_code not in self.RETRYABLE or attempt + 1 == self.max_attempts:
                raise AdsAPIError(
                    f"Ads API returned HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            await self.sleep(float(response.headers.get("Retry-After", min(2**attempt, 10))))
        raise AssertionError("retry loop must return or raise")

    async def create_campaign_report(self, start: date, end: date) -> str:
        if end < start:
            raise ValueError("end date must not precede start date")
        payload = {
            "name": f"campaign-{start.isoformat()}-{end.isoformat()}",
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "configuration": {
                "adProduct": "SPONSORED_PRODUCTS",
                "groupBy": ["campaign"],
                "columns": [
                    "date",
                    "campaignId",
                    "campaignName",
                    "impressions",
                    "clicks",
                    "cost",
                    "sales14d",
                    "purchases14d",
                ],
                "reportTypeId": "spCampaigns",
                "timeUnit": "DAILY",
                "format": "GZIP_JSON",
            },
        }
        result = await self.request("POST", "/reporting/reports", json_body=payload)
        return str(result["reportId"])

    async def wait_for_report(
        self, report_id: str, *, poll_interval: float = 10, timeout: float = 300
    ) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = await self.request("GET", f"/reporting/reports/{report_id}")
            status = result.get("status")
            if status == "COMPLETED":
                return str(result["url"])
            if status in {"FAILURE", "CANCELLED"}:
                raise AdsReportFailed(f"Ads report {report_id} ended with {status}")
            await self.sleep(poll_interval)
        raise TimeoutError(f"Ads report {report_id} was not ready within {timeout}s")

    async def download_report(self, url: str, *, sku: str) -> list[StandardAdvertisingRow]:
        try:
            response = await self.http.get(url)
            response.raise_for_status()
            raw = gzip.decompress(response.content)
            payload = json.loads(raw)
        except (httpx.HTTPError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
            raise AdsReportFailed(f"Ads report download/parse failed: {type(exc).__name__}") from exc
        return [
            StandardAdvertisingRow(
                metric_date=item["date"],
                campaign_id=str(item["campaignId"]),
                sku=sku,
                currency="EUR",
                impressions=item["impressions"],
                clicks=item["clicks"],
                purchases=item["purchases14d"],
                spend=Decimal(str(item["cost"])),
                attributed_sales=Decimal(str(item["sales14d"])),
            )
            for item in payload
        ]

    async def get_campaign_report(
        self,
        start: date,
        end: date,
        *,
        sku: str,
        poll_interval: float = 10,
        timeout: float = 300,
    ) -> tuple[str, list[StandardAdvertisingRow]]:
        report_id = await self.create_campaign_report(start, end)
        url = await self.wait_for_report(report_id, poll_interval=poll_interval, timeout=timeout)
        return report_id, await self.download_report(url, sku=sku)


class EvidenceScore(BaseModel):
    hypothesis: str
    score: float = Field(ge=0, le=1)
    evidence: list[str]


class AdvertisingRecommendation(BaseModel):
    report_id: str
    campaign_id: str
    window_start: date
    window_end: date
    metrics: AdvertisingMetrics
    conclusion: str
    hypotheses: list[EvidenceScore]
    suggested_action: str
    observation_window_days: int
    rollback_condition: str
    requires_human_review: bool = True
    executable: bool = False


def explain_advertising_anomaly(
    *,
    report_id: str,
    campaign_id: str,
    window_start: date,
    window_end: date,
    impressions: int,
    clicks: int,
    purchases: int,
    spend: Decimal,
    attributed_sales: Decimal,
    total_sales: Decimal,
    inventory_units: int,
    price_changed: bool,
    today: date,
) -> AdvertisingRecommendation:
    metrics = AdvertisingMetrics.calculate(
        impressions=impressions,
        clicks=clicks,
        purchases=purchases,
        spend=spend,
        attributed_sales=attributed_sales,
        total_sales=total_sales,
    )
    evidence = [
        f"window={window_start.isoformat()}/{window_end.isoformat()}",
        f"campaign_id={campaign_id}",
        f"report_id={report_id}",
    ]
    if impressions < 1000:
        conclusion = "曝光样本不足，不形成确定性异常结论。"
    elif (today - window_end).days < 14:
        conclusion = "14 天广告归因窗口尚未闭合，当前 ACOS 可能高估。"
    elif attributed_sales == 0:
        conclusion = "归因销售为零，ACOS 无定义；需核对归因与转化链路。"
    else:
        conclusion = "指标已按代码口径计算，可进入人工原因复核。"
    hypotheses = [
        EvidenceScore(
            hypothesis="库存约束影响转化",
            score=0.8 if inventory_units < 20 else 0.2,
            evidence=[*evidence, f"inventory_units={inventory_units}"],
        ),
        EvidenceScore(
            hypothesis="价格变化影响 CVR",
            score=0.7 if price_changed else 0.1,
            evidence=[*evidence, f"price_changed={price_changed}"],
        ),
        EvidenceScore(
            hypothesis="广告归因延迟",
            score=0.9 if (today - window_end).days < 14 else 0.2,
            evidence=[*evidence, "attribution_window=14d"],
        ),
    ]
    return AdvertisingRecommendation(
        report_id=report_id,
        campaign_id=campaign_id,
        window_start=window_start,
        window_end=window_end,
        metrics=metrics,
        conclusion=conclusion,
        hypotheses=hypotheses,
        suggested_action="保持当前 bid/budget，仅创建待审批分析卡片并继续观察。",
        observation_window_days=14,
        rollback_condition="若人工采纳后 CVR 连续 3 天下降超过 20%，恢复原配置。",
    )
