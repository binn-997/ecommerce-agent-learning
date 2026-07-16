"""Amazon Ads Reporting v3 pattern. Run: python 05_amazon_ads_client.py --demo."""
from __future__ import annotations

import argparse
import asyncio
import os
from datetime import date
from typing import Any

import httpx
from dotenv import load_dotenv


class AmazonAdsClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str, profile_id: str,
                 endpoint: str = "https://advertising-api-eu.amazon.com", http: httpx.AsyncClient | None = None) -> None:
        self.client_id, self.client_secret, self.refresh_token, self.profile_id = client_id, client_secret, refresh_token, profile_id
        self.endpoint, self.http, self._owns_http, self._token = endpoint.rstrip("/"), http or httpx.AsyncClient(timeout=30), http is None, ""

    async def __aenter__(self) -> "AmazonAdsClient": return self
    async def __aexit__(self, *_: object) -> None:
        if self._owns_http: await self.http.aclose()

    async def _headers(self) -> dict[str, str]:
        if not self._token:
            response = await self.http.post("https://api.amazon.com/auth/o2/token", data={"grant_type": "refresh_token", "refresh_token": self.refresh_token, "client_id": self.client_id, "client_secret": self.client_secret})
            response.raise_for_status(); self._token = response.json()["access_token"]
        return {"Authorization": f"Bearer {self._token}", "Amazon-Advertising-API-ClientId": self.client_id, "Amazon-Advertising-API-Scope": self.profile_id, "Content-Type": "application/json"}

    async def create_campaign_report(self, start: date, end: date) -> str:
        payload = {"name": f"campaign-{start}-{end}", "startDate": start.isoformat(), "endDate": end.isoformat(), "configuration": {"adProduct": "SPONSORED_PRODUCTS", "groupBy": ["campaign"], "columns": ["campaignId", "campaignName", "cost", "sales14d", "clicks", "purchases14d"], "reportTypeId": "spCampaigns", "timeUnit": "DAILY", "format": "GZIP_JSON"}}
        response = await self.http.post(f"{self.endpoint}/reporting/reports", headers=await self._headers(), json=payload)
        response.raise_for_status()
        return response.json()["reportId"]

    async def get_report_status(self, report_id: str) -> dict[str, Any]:
        response = await self.http.get(f"{self.endpoint}/reporting/reports/{report_id}", headers=await self._headers())
        response.raise_for_status()
        return response.json()


async def main() -> None:
    load_dotenv(); parser = argparse.ArgumentParser(); parser.add_argument("--demo", action="store_true"); args = parser.parse_args()
    if args.demo:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "auth/o2/token" in str(request.url): return httpx.Response(200, json={"access_token": "demo"})
            if request.method == "POST": return httpx.Response(202, json={"reportId": "demo-report-001"})
            return httpx.Response(200, json={"reportId": "demo-report-001", "status": "SUCCESS", "url": "https://example.invalid/report"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            async with AmazonAdsClient("id", "secret", "refresh", "123", http=http) as client:
                report_id = await client.create_campaign_report(date(2026, 7, 1), date(2026, 7, 2))
                print(report_id, await client.get_report_status(report_id))
        return
    required = ["LWA_CLIENT_ID", "LWA_CLIENT_SECRET", "LWA_REFRESH_TOKEN", "AMAZON_ADS_PROFILE_ID"]
    if missing := [key for key in required if not os.getenv(key)]: raise SystemExit(f"Missing {', '.join(missing)}. Use --demo or fill .env.")
    async with AmazonAdsClient(os.environ["LWA_CLIENT_ID"], os.environ["LWA_CLIENT_SECRET"], os.environ["LWA_REFRESH_TOKEN"], os.environ["AMAZON_ADS_PROFILE_ID"]) as client:
        report_id = await client.create_campaign_report(date.today(), date.today())
        print("Created report:", report_id)


if __name__ == "__main__": asyncio.run(main())
