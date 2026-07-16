from __future__ import annotations

import asyncio
import gzip
import json
from datetime import date

import httpx

from amazon_ai_platform.spapi import AsyncSPAPIClient, SPAPIError


def run(coro):
    return asyncio.run(coro)


def report_payload() -> dict:
    return {
        "reportSpecification": {
            "reportType": "GET_SALES_AND_TRAFFIC_REPORT",
            "marketplaceIds": ["A1PA6795UKMFR9"],
        },
        "salesAndTrafficByAsin": [{
            "parentAsin": "B0PARENT",
            "childAsin": "B0CHILD",
            "salesByAsin": {
                "unitsOrdered": 8,
                "orderedProductSales": {"amount": 399.2, "currencyCode": "EUR"},
            },
            "trafficByAsin": {
                "sessions": 100, "pageViews": 130, "unitSessionPercentage": 8.0,
            },
        }],
    }


def test_sales_and_traffic_report_full_async_flow() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path)
        if path == "/auth/o2/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        if path.endswith("/reports") and request.method == "POST":
            body = json.loads(request.content)
            assert body["reportType"] == "GET_SALES_AND_TRAFFIC_REPORT"
            assert body["reportOptions"]["asinGranularity"] == "CHILD"
            return httpx.Response(202, json={"reportId": "report-1"})
        if path.endswith("/reports/report-1"):
            return httpx.Response(200, json={
                "processingStatus": "DONE", "reportDocumentId": "document-1"
            })
        if path.endswith("/documents/document-1"):
            return httpx.Response(200, json={
                "url": "https://download.example/report", "compressionAlgorithm": "GZIP"
            })
        if request.url.host == "download.example":
            return httpx.Response(200, content=gzip.compress(json.dumps(report_payload()).encode()))
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = AsyncSPAPIClient(
                client_id="id", client_secret="secret", refresh_token="refresh", http=http,
                sleep=lambda _: asyncio.sleep(0),
            )
            return await client.get_sales_and_traffic_report(
                date(2026, 7, 1), date(2026, 7, 7), poll_interval=0
            )

    report = run(scenario())
    assert report.sales_and_traffic_by_asin[0].sales_by_asin.units_ordered == 8
    assert report.sales_and_traffic_by_asin[0].sales_by_asin.ordered_product_sales.currency_code == "EUR"
    assert calls.count("/auth/o2/token") == 1


def test_429_uses_retry_after_and_preserves_request_id() -> None:
    attempts = 0
    delays: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.host == "api.amazon.com":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        attempts += 1
        return httpx.Response(
            429,
            headers={"Retry-After": "0", "x-amzn-RequestId": "req-429"},
            json={"errors": [{"message": "quota exceeded"}]},
        )

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = AsyncSPAPIClient(
                client_id="id", client_secret="secret", refresh_token="refresh", http=http,
                max_attempts=2, sleep=fake_sleep,
            )
            await client.request("GET", "/orders/v0/orders", operation="orders")

    try:
        run(scenario())
        raise AssertionError("SPAPIError was not raised")
    except SPAPIError as exc:
        assert exc.status_code == 429
        assert exc.request_id == "req-429"
        assert attempts == 2
        assert delays == [0]


def test_concurrent_callers_refresh_lwa_token_once() -> None:
    token_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        token_calls += 1
        await asyncio.sleep(0)
        return httpx.Response(200, json={"access_token": "shared-token", "expires_in": 3600})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = AsyncSPAPIClient(
                client_id="id", client_secret="secret", refresh_token="refresh", http=http
            )
            return await asyncio.gather(*(client.access_token() for _ in range(20)))

    assert set(run(scenario())) == {"shared-token"}
    assert token_calls == 1
