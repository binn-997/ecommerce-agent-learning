from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

from amazon_ai_platform.data_quality import (
    QUALITY_RULES,
    IdempotentMetricStore,
    audit_sales_rows,
    normalize_sales_rows,
    parse_sales_csv,
    reconcile_revenue,
)
from amazon_ai_platform.models import AdvertisingMetrics, RawSalesTrafficRow


CSV = """metric_date,sku,parent_asin,child_asin,currency,units,sessions,revenue
2026-07-01,SYNTHETIC-1,B0PARENT01,B0CHILD001,EUR,8,100,399.20
2026-07-02,SYNTHETIC-1,B0PARENT01,B0CHILD001,EUR,2,0,100.00
"""


def test_twenty_quality_assertions_and_valid_normalization() -> None:
    rows = parse_sales_csv(CSV)
    issues = audit_sales_rows(
        rows,
        known_skus={"SYNTHETIC-1"},
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
        today=date(2026, 7, 31),
    )
    assert len(QUALITY_RULES) == 20
    assert len(set(QUALITY_RULES)) == 20
    assert issues == []
    normalized = normalize_sales_rows(rows)
    assert normalized[0].cvr == 0.08
    assert normalized[1].cvr is None


def test_quality_gate_reports_multiple_bad_fields() -> None:
    row = RawSalesTrafficRow(
        metric_date="bad-date",
        sku="UNKNOWN",
        parent_asin="bad",
        child_asin="bad",
        currency="usd",
        units="-2",
        sessions="nope",
        revenue="-1",
    )
    issues = audit_sales_rows(
        [row],
        known_skus={"SYNTHETIC-1"},
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
        today=date(2026, 7, 31),
    )
    rule_ids = {issue.rule_id for issue in issues}
    assert {"DQ02_DATE_FORMAT", "DQ06_SKU_KNOWN", "DQ08_CURRENCY_FORMAT"} <= rule_ids
    assert {"DQ11_UNITS_NON_NEGATIVE", "DQ13_SESSIONS_NON_NEGATIVE"} & rule_ids


def test_same_file_twice_is_idempotent_and_reconciles() -> None:
    rows = normalize_sales_rows(parse_sales_csv(CSV))

    async def scenario() -> int:
        store = IdempotentMetricStore()
        await store.upsert_many(rows)
        return await store.upsert_many(rows)

    assert asyncio.run(scenario()) == 2
    report = reconcile_revenue(rows, Decimal("500.00"))
    assert report.within_tolerance is True
    assert report.difference_ratio == 0.0016
    assert report.difference_ratio <= 0.005


def test_advertising_denominator_zero_is_none() -> None:
    metrics = AdvertisingMetrics.calculate(
        impressions=0,
        clicks=0,
        purchases=0,
        spend=Decimal("0"),
        attributed_sales=Decimal("0"),
        total_sales=Decimal("0"),
    )
    assert metrics.acos is None
    assert metrics.ctr is None
    assert metrics.cvr is None
    assert metrics.cpc is None
    assert metrics.tacos is None
