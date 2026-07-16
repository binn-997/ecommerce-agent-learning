from __future__ import annotations

import asyncio
import gzip
import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from amazon_ai_platform.ads import (
    AdsReportFailed,
    AmazonAdsClient,
    explain_advertising_anomaly,
)
from amazon_ai_platform.feishu import FeishuBusinessHub


def client(http: httpx.AsyncClient, **kwargs) -> AmazonAdsClient:
    return AmazonAdsClient(
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
        profile_id="123456",
        marketplace_id="A1PA6795UKMFR9",
        http=http,
        sleep=lambda _: asyncio.sleep(0),
        **kwargs,
    )


def test_ads_two_429_then_success() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.host == "api.amazon.com":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        attempts += 1
        if attempts < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(202, json={"reportId": "ads-1"})

    async def scenario() -> str:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await client(http).create_campaign_report(date(2026, 7, 1), date(2026, 7, 2))

    assert asyncio.run(scenario()) == "ads-1"
    assert attempts == 3


def test_ads_full_gzip_report_flow() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.amazon.com":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        if request.url.host == "download.example":
            data = [{
                "date": "2026-07-01",
                "campaignId": "campaign-1",
                "impressions": 1000,
                "clicks": 50,
                "purchases14d": 5,
                "cost": 25,
                "sales14d": 100,
            }]
            return httpx.Response(200, content=gzip.compress(json.dumps(data).encode()))
        if request.method == "POST":
            return httpx.Response(202, json={"reportId": "ads-1"})
        return httpx.Response(200, json={"status": "COMPLETED", "url": "https://download.example/r"})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await client(http).get_campaign_report(
                date(2026, 7, 1), date(2026, 7, 2), sku="SYNTHETIC", poll_interval=0
            )

    report_id, result = asyncio.run(scenario())
    assert report_id == "ads-1"
    assert result[0].clicks == 50


def test_ads_fatal_and_timeout_are_explicit() -> None:
    async def fatal_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.amazon.com":
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(200, json={"status": "FAILURE"})

    async def fatal() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(fatal_handler)) as http:
            await client(http).wait_for_report("ads-1", poll_interval=0)

    with pytest.raises(AdsReportFailed, match="FAILURE"):
        asyncio.run(fatal())


def test_low_exposure_and_attribution_delay_never_auto_execute() -> None:
    recommendation = explain_advertising_anomaly(
        report_id="synthetic-report",
        campaign_id="synthetic-campaign",
        window_start=date(2026, 7, 1),
        window_end=date(2026, 7, 15),
        impressions=50,
        clicks=0,
        purchases=0,
        spend=Decimal("10"),
        attributed_sales=Decimal("0"),
        total_sales=Decimal("100"),
        inventory_units=10,
        price_changed=False,
        today=date(2026, 7, 16),
    )
    assert "样本不足" in recommendation.conclusion
    assert recommendation.metrics.acos is None
    assert recommendation.requires_human_review is True
    assert recommendation.executable is False
    assert all("campaign_id=" in " ".join(item.evidence) for item in recommendation.hypotheses)
    card = FeishuBusinessHub.advertising_recommendation_card(recommendation)
    assert "synthetic-report" in str(card)
    assert "人工审批" in str(card)
