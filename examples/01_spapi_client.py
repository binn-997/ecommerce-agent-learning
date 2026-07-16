"""Minimal but production-shaped SP-API client. Run: python 01_spapi_client.py --demo."""
from __future__ import annotations

import argparse
import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from dotenv import load_dotenv


class SPAPIError(RuntimeError):
    pass


@dataclass
class TokenBucket:
    """Async token bucket; tune rate/capacity to the endpoint usage plan."""
    rate_per_second: float
    capacity: float
    tokens: float = field(init=False)
    updated_at: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self.tokens = self.capacity

    async def acquire(self) -> None:
        while True:
            async with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated_at) * self.rate_per_second)
                self.updated_at = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait_seconds = (1 - self.tokens) / self.rate_per_second
            await asyncio.sleep(wait_seconds)


class SPAPIClient:
    def __init__(self, *, client_id: str, client_secret: str, refresh_token: str,
                 aws_access_key: str, aws_secret_key: str, marketplace_id: str,
                 endpoint: str, region: str, http: httpx.AsyncClient | None = None) -> None:
        self.client_id, self.client_secret, self.refresh_token = client_id, client_secret, refresh_token
        self.credentials = Credentials(aws_access_key, aws_secret_key, os.getenv("AWS_SESSION_TOKEN"))
        self.marketplace_id, self.endpoint, self.region = marketplace_id, endpoint.rstrip("/"), region
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=False)
        self._owns_http = http is None
        self._access_token = ""
        self._access_token_expires_at = 0.0
        self._bucket = TokenBucket(rate_per_second=0.0167, capacity=20)  # Orders default: confirm current usage plan

    async def __aenter__(self) -> "SPAPIClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_http:
            await self.http.aclose()

    async def _lwa_access_token(self) -> str:
        if self._access_token and time.monotonic() < self._access_token_expires_at - 60:
            return self._access_token
        response = await self.http.post("https://api.amazon.com/auth/o2/token", data={
            "grant_type": "refresh_token", "refresh_token": self.refresh_token,
            "client_id": self.client_id, "client_secret": self.client_secret,
        })
        response.raise_for_status()
        payload = response.json()
        self._access_token = payload["access_token"]
        self._access_token_expires_at = time.monotonic() + int(payload.get("expires_in", 3600))
        return self._access_token

    async def request(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(5):
            await self._bucket.acquire()
            token = await self._lwa_access_token()
            url = f"{self.endpoint}{path}" + (f"?{urlencode(params, doseq=True)}" if params else "")
            aws_request = AWSRequest(method=method, url=url, headers={"x-amz-access-token": token, "accept": "application/json"})
            SigV4Auth(self.credentials, "execute-api", self.region).add_auth(aws_request)
            response = await self.http.request(method, url, headers=dict(aws_request.headers.items()))
            if response.status_code not in {429, 500, 502, 503, 504}:
                response.raise_for_status()
                return response.json()
            retry_after = float(response.headers.get("Retry-After", 0) or 0)
            await asyncio.sleep(max(retry_after, min(2 ** attempt, 16)))
        raise SPAPIError(f"SP-API {method} {path} failed after retries")

    async def get_orders(self, created_after: datetime) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"MarketplaceIds": [self.marketplace_id], "CreatedAfter": created_after.isoformat()}
        orders: list[dict[str, Any]] = []
        while True:
            payload = await self.request("GET", "/orders/v0/orders", params=params)
            orders.extend(payload.get("payload", {}).get("Orders", []))
            next_token = payload.get("payload", {}).get("NextToken")
            if not next_token:
                return orders
            params = {"NextToken": next_token}


async def demo() -> None:
    calls = 0
    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if "auth/o2/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "demo-token", "expires_in": 3600})
        return httpx.Response(200, json={"payload": {"Orders": [{"AmazonOrderId": "DEMO-001", "OrderStatus": "Shipped"}]}})
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        async with SPAPIClient(client_id="id", client_secret="secret", refresh_token="refresh", aws_access_key="key", aws_secret_key="secret", marketplace_id="A1PA6795UKMFR9", endpoint="https://sellingpartnerapi-eu.amazon.com", region="eu-west-1", http=http) as client:
            print(await client.get_orders(datetime.now(timezone.utc) - timedelta(days=1)))
    print(f"demo completed with {calls} HTTP calls")


async def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    if args.demo:
        await demo()
        return
    required = ["LWA_CLIENT_ID", "LWA_CLIENT_SECRET", "LWA_REFRESH_TOKEN", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise SystemExit(f"Missing {', '.join(missing)}. Use --demo or fill .env.")
    async with SPAPIClient(client_id=os.environ["LWA_CLIENT_ID"], client_secret=os.environ["LWA_CLIENT_SECRET"], refresh_token=os.environ["LWA_REFRESH_TOKEN"], aws_access_key=os.environ["AWS_ACCESS_KEY_ID"], aws_secret_key=os.environ["AWS_SECRET_ACCESS_KEY"], marketplace_id=os.getenv("SPAPI_MARKETPLACE_ID", "A1PA6795UKMFR9"), endpoint=os.getenv("SPAPI_ENDPOINT", "https://sellingpartnerapi-eu.amazon.com"), region=os.getenv("SPAPI_REGION", "eu-west-1")) as client:
        orders = await client.get_orders(datetime.now(timezone.utc) - timedelta(days=1))
        print(f"Fetched {len(orders)} orders")


if __name__ == "__main__":
    asyncio.run(main())
