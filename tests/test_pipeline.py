from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from amazon_ai_platform.models import StandardSalesTrafficRow
from amazon_ai_platform.pipeline import DataPipeline, InMemoryPipelineRepository, PipelineError


def rows(count: int = 60) -> list[StandardSalesTrafficRow]:
    return [
        StandardSalesTrafficRow(
            metric_date=date(2026, 1, 1) + timedelta(days=index),
            sku="SYNTHETIC-SKU",
            parent_asin="B0PARENT01",
            child_asin="B0CHILD001",
            currency="EUR",
            units=index,
            sessions=index * 10,
            revenue=Decimal(index),
        )
        for index in range(count)
    ]


def run_ingest(repository: InMemoryPipelineRepository, *, fail_at: int | None = None):
    payload = json.dumps([row.model_dump(mode="json") for row in rows()]).encode()
    return asyncio.run(DataPipeline(repository.transaction).ingest_sales_metrics(
        rows=rows(),
        raw_payload=payload,
        seller_id="synthetic-seller",
        request_id="spapi-request-001",
        trace_id="trace-pipeline-001",
        window_start=date(2026, 1, 1),
        window_end=date(2026, 3, 1),
        fail_at_row=fail_at,
    ))


def test_row_50_failure_rolls_back_whole_batch() -> None:
    repository = InMemoryPipelineRepository()
    with pytest.raises(PipelineError, match="synthetic row 50"):
        run_ingest(repository, fail_at=50)
    assert repository.raw_payloads == {}
    assert repository.metrics == {}
    assert repository.cursors == {}


def test_replay_is_idempotent_and_trace_reaches_raw_request() -> None:
    repository = InMemoryPipelineRepository()
    first = run_ingest(repository)
    second = run_ingest(repository)
    assert len(repository.metrics) == 60
    assert len(repository.raw_payloads) == 1
    assert first.payload_hash == second.payload_hash
    raw = repository.raw_payloads[first.payload_hash]
    assert raw["trace_id"] == "trace-pipeline-001"
    assert raw["request_id"] == "spapi-request-001"
