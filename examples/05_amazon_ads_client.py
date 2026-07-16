"""Thin offline Amazon Ads Reporting v3 demo."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
from datetime import date

import httpx
from dotenv import load_dotenv

from amazon_ai_platform.ads import AmazonAdsClient


async def demo_handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "api.amazon.com":
        return httpx.Response(200, json={"access_token": "synthetic-token", "expires_in": 3600})
    if request.method == "POST":
        return httpx.Response(202, json={"reportId": "synthetic-ads-report-001"})
    if request.url.host == "download.example":
        rows = [{
            "date": "2026-07-01",
            "campaignId": "synthetic-campaign-001",
            "impressions": 2000,
            "clicks": 80,
            "purchases14d": 8,
            "cost": 40,
            "sales14d": 200,
        }]
        return httpx.Response(200, content=gzip.compress(json.dumps(rows).encode()))
    return httpx.Response(200, json={
        "reportId": "synthetic-ads-report-001",
        "status": "COMPLETED",
        "url": "https://download.example/report",
    })


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    if args.demo:
        async with httpx.AsyncClient(transport=httpx.MockTransport(demo_handler)) as http:
            client = AmazonAdsClient(
                client_id="synthetic-client",
                client_secret="synthetic-secret",
                refresh_token="synthetic-refresh",
                profile_id="123456789",
                marketplace_id="A1PA6795UKMFR9",
                http=http,
                sleep=lambda _: asyncio.sleep(0),
            )
            report_id, rows = await client.get_campaign_report(
                date(2026, 7, 1),
                date(2026, 7, 2),
                sku="SYNTHETIC-SKU",
                poll_interval=0,
            )
        print(report_id, rows[0].model_dump_json())
        return
    required = [
        "LWA_CLIENT_ID",
        "LWA_CLIENT_SECRET",
        "LWA_REFRESH_TOKEN",
        "AMAZON_ADS_PROFILE_ID",
        "SPAPI_MARKETPLACE_ID",
    ]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise SystemExit(f"Missing {', '.join(missing)}. Use --demo or fill .env.")
    async with AmazonAdsClient(
        client_id=os.environ["LWA_CLIENT_ID"],
        client_secret=os.environ["LWA_CLIENT_SECRET"],
        refresh_token=os.environ["LWA_REFRESH_TOKEN"],
        profile_id=os.environ["AMAZON_ADS_PROFILE_ID"],
        marketplace_id=os.environ["SPAPI_MARKETPLACE_ID"],
    ) as client:
        report_id = await client.create_campaign_report(date.today(), date.today())
        print("Created report:", report_id)


if __name__ == "__main__":
    asyncio.run(main())
