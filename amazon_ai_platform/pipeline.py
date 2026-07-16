"""Transactional, replayable ingestion pipeline with traceable raw evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from .models import StandardSalesTrafficRow


class PipelineError(RuntimeError):
    pass


class PipelineTransaction(Protocol):
    async def store_raw(self, payload_hash: str, payload: bytes, trace: dict[str, Any]) -> None: ...

    async def upsert_metric(self, row: StandardSalesTrafficRow, trace_id: str) -> None: ...

    async def update_cursor(self, seller_hash: str, operation: str, cursor: str) -> None: ...


TransactionFactory = Callable[[], Any]


@dataclass(frozen=True)
class PipelineRun:
    trace_id: str
    seller_id_hash: str
    operation: str
    request_id: str
    date_window: str
    row_count: int
    payload_hash: str
    latency_ms: int


class DataPipeline:
    def __init__(self, transaction: TransactionFactory) -> None:
        self.transaction = transaction

    async def ingest_sales_metrics(
        self,
        *,
        rows: list[StandardSalesTrafficRow],
        raw_payload: bytes,
        seller_id: str,
        request_id: str,
        trace_id: str,
        window_start: date,
        window_end: date,
        fail_at_row: int | None = None,
    ) -> PipelineRun:
        """Commit raw evidence, standardized rows and cursor as one atomic unit."""
        started = time.perf_counter()
        seller_hash = hashlib.sha256(seller_id.encode()).hexdigest()[:16]
        payload_hash = hashlib.sha256(raw_payload).hexdigest()
        date_window = f"{window_start.isoformat()}/{window_end.isoformat()}"
        trace = {
            "trace_id": trace_id,
            "seller_id_hash": seller_hash,
            "operation": "sales_metrics_sync",
            "request_id": request_id,
            "date_window": date_window,
        }
        try:
            async with self.transaction() as tx:
                await tx.store_raw(payload_hash, raw_payload, trace)
                for row_number, row in enumerate(rows, start=1):
                    if fail_at_row == row_number:
                        raise PipelineError(f"sales_metrics_sync failed at synthetic row {row_number}")
                    await tx.upsert_metric(row, trace_id)
                await tx.update_cursor(seller_hash, "sales_metrics_sync", window_end.isoformat())
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError(f"sales_metrics_sync transaction failed trace_id={trace_id}") from exc
        return PipelineRun(
            **trace,
            row_count=len(rows),
            payload_hash=payload_hash,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


@dataclass
class InMemoryPipelineRepository:
    """Deterministic transaction double; rollback semantics mirror PostgreSQL."""

    raw_payloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    metrics: dict[tuple[date, str], dict[str, Any]] = field(default_factory=dict)
    cursors: dict[tuple[str, str], str] = field(default_factory=dict)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["InMemoryPipelineRepository"]:
        snapshot = copy.deepcopy((self.raw_payloads, self.metrics, self.cursors))
        try:
            yield self
        except Exception:
            self.raw_payloads, self.metrics, self.cursors = snapshot
            raise

    async def store_raw(self, payload_hash: str, payload: bytes, trace: dict[str, Any]) -> None:
        self.raw_payloads[payload_hash] = {
            "payload": json.loads(payload),
            **trace,
        }

    async def upsert_metric(self, row: StandardSalesTrafficRow, trace_id: str) -> None:
        self.metrics[row.idempotency_key] = {**row.model_dump(), "trace_id": trace_id}

    async def update_cursor(self, seller_hash: str, operation: str, cursor: str) -> None:
        self.cursors[(seller_hash, operation)] = cursor


class AsyncPGPipelineRepository:
    """Thin asyncpg adapter; SQL owns uniqueness and transaction guarantees."""

    def __init__(self, pool: Any) -> None:
        self.pool = pool

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["AsyncPGPipelineTransaction"]:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                yield AsyncPGPipelineTransaction(connection)


class AsyncPGPipelineTransaction:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    async def store_raw(self, payload_hash: str, payload: bytes, trace: dict[str, Any]) -> None:
        await self.connection.execute(
            """INSERT INTO raw_imports
               (payload_hash, payload, trace_id, seller_id_hash, operation, request_id, date_window)
               VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7)
               ON CONFLICT (payload_hash) DO UPDATE SET last_replayed_at = NOW()""",
            payload_hash,
            payload.decode(),
            trace["trace_id"],
            trace["seller_id_hash"],
            trace["operation"],
            trace["request_id"],
            trace["date_window"],
        )

    async def upsert_metric(self, row: StandardSalesTrafficRow, trace_id: str) -> None:
        await self.connection.execute(
            """INSERT INTO daily_metrics
               (metric_date, sku, units_sold, revenue, sessions, currency, trace_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (metric_date, sku) DO UPDATE SET
                 units_sold=EXCLUDED.units_sold, revenue=EXCLUDED.revenue,
                 sessions=EXCLUDED.sessions, currency=EXCLUDED.currency,
                 trace_id=EXCLUDED.trace_id""",
            row.metric_date,
            row.sku,
            row.units,
            row.revenue,
            row.sessions,
            row.currency,
            trace_id,
        )

    async def update_cursor(self, seller_hash: str, operation: str, cursor: str) -> None:
        await self.connection.execute(
            """INSERT INTO sync_cursors (seller_id_hash, operation, cursor_value)
               VALUES ($1, $2, $3)
               ON CONFLICT (seller_id_hash, operation) DO UPDATE SET
                 cursor_value=EXCLUDED.cursor_value, updated_at=NOW()""",
            seller_hash,
            operation,
            cursor,
        )
