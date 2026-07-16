"""Production-shaped asynchronous Amazon Selling Partner API client.

The default path follows Amazon's current LWA-only request flow. A callable signer can
be injected for legacy/private infrastructure without coupling the client to boto3.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

import httpx

from .models import SalesAndTrafficReport


class SPAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, request_id: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id


class ReportFailed(SPAPIError):
    pass


class ReportCache(Protocol):
    async def get(self, key: str) -> SalesAndTrafficReport | None: ...

    async def set(self, key: str, value: SalesAndTrafficReport) -> None: ...


class InMemoryReportCache:
    def __init__(self) -> None:
        self.values: dict[str, SalesAndTrafficReport] = {}

    async def get(self, key: str) -> SalesAndTrafficReport | None:
        return self.values.get(key)

    async def set(self, key: str, value: SalesAndTrafficReport) -> None:
        self.values[key] = value


@dataclass
class AsyncTokenBucket:
    """Concurrency-safe token bucket using a monotonic clock."""

    rate: float
    capacity: float
    tokens: float = field(init=False)
    updated_at: float = field(default_factory=time.monotonic)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        if self.rate <= 0 or self.capacity < 1:
            raise ValueError("rate must be positive and capacity must be at least one")
        self.tokens = self.capacity

    async def acquire(self, cost: float = 1.0) -> None:
        if cost <= 0 or cost > self.capacity:
            raise ValueError("cost must be positive and no greater than capacity")
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = max(0.0, now - self.updated_at)
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.updated_at = now
                if self.tokens >= cost:
                    self.tokens -= cost
                    return
                delay = (cost - self.tokens) / self.rate
            await asyncio.sleep(delay)

    async def update_rate(self, rate: float) -> None:
        """Accept a dynamic usage-plan rate without changing the safe burst."""
        if rate <= 0:
            return
        async with self._lock:
            self.rate = rate


Signer = Callable[[str, str, Mapping[str, str], bytes | None], Mapping[str, str]]


class AsyncSPAPIClient:
    RETRYABLE = {429, 500, 502, 503, 504}
    REPORTS_PATH = "/reports/2021-06-30"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        marketplace_id: str = "A1PA6795UKMFR9",
        seller_id: str = "self",
        endpoint: str = "https://sellingpartnerapi-eu.amazon.com",
        http: httpx.AsyncClient | None = None,
        signer: Signer | None = None,
        max_attempts: int = 5,
        sleep: Callable[[float], Any] = asyncio.sleep,
        report_cache: ReportCache | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.marketplace_id = marketplace_id
        self.seller_id = seller_id
        self.endpoint = endpoint.rstrip("/")
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10))
        self._owns_http = http is None
        self.signer = signer
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.report_cache = report_cache
        self._token = ""
        self._token_expiry = 0.0
        self._token_lock = asyncio.Lock()
        self.retry_counts: dict[int, int] = {}
        self._buckets = {
            "reports": AsyncTokenBucket(rate=0.0167, capacity=15),
            "orders": AsyncTokenBucket(rate=0.0167, capacity=20),
            "default": AsyncTokenBucket(rate=0.1, capacity=10),
        }

    async def __aenter__(self) -> "AsyncSPAPIClient":
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
                raise SPAPIError("LWA token refresh failed", status_code=response.status_code)
            try:
                payload = response.json()
                self._token = str(payload["access_token"])
            except (ValueError, KeyError, TypeError) as exc:
                raise SPAPIError("LWA token refresh returned an invalid response") from exc
            self._token_expiry = time.monotonic() + int(payload.get("expires_in", 3600))
            return self._token

    @staticmethod
    def _retry_after(response: httpx.Response, attempt: int) -> float:
        value = response.headers.get("Retry-After")
        if value:
            try:
                return max(0.0, float(value))
            except ValueError:
                try:
                    target = parsedate_to_datetime(value)
                    return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
                except (TypeError, ValueError):
                    pass
        ceiling = min(2 ** attempt, 30)
        return random.uniform(0, ceiling)  # full jitter avoids synchronized retries

    async def request(
        self,
        method: str,
        path: str,
        *,
        operation: str = "default",
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        bucket = self._buckets.get(operation, self._buckets["default"])
        url = f"{self.endpoint}{path}"
        for attempt in range(self.max_attempts):
            await bucket.acquire()
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "x-amz-access-token": await self.access_token(),
            }
            body = json.dumps(json_body).encode() if json_body is not None else None
            if self.signer:
                headers.update(self.signer(method, url, headers, body))
            try:
                response = await self.http.request(
                    method, url, params=params, content=body, headers=headers
                )
            except httpx.TransportError as exc:
                if attempt == self.max_attempts - 1:
                    raise SPAPIError(f"SP-API network failure: {type(exc).__name__}") from exc
                await self.sleep(random.uniform(0, min(2 ** attempt, 30)))
                continue

            if limit := response.headers.get("x-amzn-RateLimit-Limit"):
                try:
                    await bucket.update_rate(float(limit))
                except ValueError:
                    pass
            request_id = response.headers.get("x-amzn-RequestId")
            if response.status_code < 400:
                return response.json()
            if response.status_code not in self.RETRYABLE or attempt == self.max_attempts - 1:
                message = self._safe_error(response)
                raise SPAPIError(message, status_code=response.status_code, request_id=request_id)
            self.retry_counts[response.status_code] = self.retry_counts.get(response.status_code, 0) + 1
            await self.sleep(self._retry_after(response, attempt))
        raise AssertionError("retry loop must return or raise")

    @staticmethod
    def _safe_error(response: httpx.Response) -> str:
        try:
            errors = response.json().get("errors", [])
            detail = errors[0].get("message", "") if errors else ""
        except (ValueError, AttributeError, IndexError):
            detail = ""
        return f"SP-API returned HTTP {response.status_code}" + (f": {detail[:200]}" if detail else "")

    async def create_sales_and_traffic_report(
        self, start: date, end: date, *, asin_granularity: str = "CHILD"
    ) -> str:
        if end < start:
            raise ValueError("end date must not precede start date")
        if (end - start).days > 29:  # inclusive range: difference 29 == 30 calendar days
            raise ValueError("use 7-30 day windows and merge locally")
        payload = await self.request(
            "POST",
            f"{self.REPORTS_PATH}/reports",
            operation="reports",
            json_body={
                "reportType": "GET_SALES_AND_TRAFFIC_REPORT",
                "marketplaceIds": [self.marketplace_id],
                "dataStartTime": f"{start.isoformat()}T00:00:00Z",
                "dataEndTime": f"{end.isoformat()}T23:59:59Z",
                "reportOptions": {
                    "dateGranularity": "DAY",
                    "asinGranularity": asin_granularity,
                },
            },
        )
        return str(payload["reportId"])

    async def wait_for_report(
        self, report_id: str, *, poll_interval: float = 15, timeout: float = 600
    ) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            report = await self.request(
                "GET", f"{self.REPORTS_PATH}/reports/{report_id}", operation="reports"
            )
            status = report.get("processingStatus")
            if status == "DONE":
                if not report.get("reportDocumentId"):
                    raise ReportFailed("DONE report did not contain reportDocumentId")
                return str(report["reportDocumentId"])
            if status in {"CANCELLED", "FATAL"}:
                raise ReportFailed(f"report {report_id} ended with {status}")
            await self.sleep(poll_interval)
        raise TimeoutError(f"report {report_id} was not ready within {timeout}s")

    async def download_report(self, document_id: str) -> SalesAndTrafficReport:
        metadata = await self.request(
            "GET", f"{self.REPORTS_PATH}/documents/{document_id}", operation="reports"
        )
        try:
            download = await self.http.get(str(metadata["url"]))
            download.raise_for_status()
        except httpx.HTTPError as exc:
            raise SPAPIError(f"report download failed: {type(exc).__name__}") from exc
        raw = download.content
        if metadata.get("compressionAlgorithm") == "GZIP":
            raw = gzip.decompress(raw)
        return SalesAndTrafficReport.model_validate_json(raw)

    async def get_sales_and_traffic_report(
        self, start: date, end: date, *, poll_interval: float = 15, timeout: float = 600
    ) -> SalesAndTrafficReport:
        cache_key = self.report_cache_key(start, end, asin_granularity="CHILD")
        if self.report_cache and (cached := await self.report_cache.get(cache_key)):
            return cached
        report_id = await self.create_sales_and_traffic_report(start, end)
        document_id = await self.wait_for_report(
            report_id, poll_interval=poll_interval, timeout=timeout
        )
        report = await self.download_report(document_id)
        if self.report_cache:
            await self.report_cache.set(cache_key, report)
        return report

    def report_cache_key(
        self, start: date, end: date, *, asin_granularity: str
    ) -> str:
        options = json.dumps(
            {"asinGranularity": asin_granularity, "dateGranularity": "DAY"},
            sort_keys=True,
            separators=(",", ":"),
        )
        return "|".join((
            self.seller_id,
            self.marketplace_id,
            "GET_SALES_AND_TRAFFIC_REPORT",
            start.isoformat(),
            end.isoformat(),
            options,
        ))
