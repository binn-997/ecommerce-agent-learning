"""Offline GET_SALES_AND_TRAFFIC_REPORT demo using httpx.MockTransport."""

from __future__ import annotations

import asyncio
import gzip
import json
from datetime import date

import httpx

from amazon_ai_platform.spapi import AsyncSPAPIClient


async def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if request.url.host == "api.amazon.com":
        return httpx.Response(200, json={"access_token": "demo-token", "expires_in": 3600})
    if path.endswith("/reports") and request.method == "POST":
        return httpx.Response(202, json={"reportId": "demo-report"})
    if path.endswith("/reports/demo-report"):
        return httpx.Response(200, json={"processingStatus": "DONE", "reportDocumentId": "demo-document"})
    if path.endswith("/documents/demo-document"):
        return httpx.Response(200, json={"url": "https://download.example/report", "compressionAlgorithm": "GZIP"})
    if request.url.host == "download.example":
        payload = {
            "reportSpecification": {
                "reportType": "GET_SALES_AND_TRAFFIC_REPORT",
                "marketplaceIds": ["A1PA6795UKMFR9"],
            },
            "salesAndTrafficByAsin": [{
                "parentAsin": "B0PARENT", "childAsin": "B0CHILD",
                "salesByAsin": {
                    "unitsOrdered": 23,
                    "orderedProductSales": {"amount": 1197.7, "currencyCode": "EUR"},
                },
                "trafficByAsin": {
                    "sessions": 250, "pageViews": 310, "unitSessionPercentage": 9.2,
                },
            }],
        }
        return httpx.Response(200, content=gzip.compress(json.dumps(payload).encode()))
    raise AssertionError(f"unexpected request: {request.method} {request.url}")


async def main() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AsyncSPAPIClient(
            client_id="demo", client_secret="demo", refresh_token="demo", http=http,
            sleep=lambda _: asyncio.sleep(0),
        )
        report = await client.get_sales_and_traffic_report(
            date(2026, 7, 1), date(2026, 7, 7), poll_interval=0
        )
    print(report.model_dump_json(indent=2, by_alias=True))


if __name__ == "__main__":
    asyncio.run(main())
