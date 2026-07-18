from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal

from amazon_ai_platform.ads import explain_advertising_anomaly
from amazon_ai_platform.feishu import FeishuBusinessHub
from amazon_ai_platform.listing_agent import (
    CompetitorEvidence,
    DeterministicGermanGenerator,
    InMemoryCompetitorSource,
    ListingOptimizationAgent,
    ProductBrief,
)
from amazon_ai_platform.models import SalesAlert, StandardSalesTrafficRow
from amazon_ai_platform.pipeline import DataPipeline, InMemoryPipelineRepository


def test_sales_pipeline_to_human_alert_golden_path() -> None:
    row = StandardSalesTrafficRow(
        metric_date=date(2026, 7, 16),
        sku="SYNTHETIC",
        parent_asin="B0PARENT01",
        child_asin="B0CHILD001",
        currency="EUR",
        units=20,
        sessions=100,
        revenue=Decimal("500"),
    )
    repository = InMemoryPipelineRepository()

    async def scenario():
        return await DataPipeline(repository.transaction).ingest_sales_metrics(
            rows=[row],
            raw_payload=json.dumps([row.model_dump(mode="json")]).encode(),
            seller_id="synthetic-seller",
            request_id="spapi-001",
            trace_id="trace-sales-001",
            window_start=row.metric_date,
            window_end=row.metric_date,
        )

    run = asyncio.run(scenario())
    alert = SalesAlert(
        source_key=run.trace_id,
        sku=row.sku,
        metric_date=row.metric_date,
        revenue_eur=float(row.revenue),
        change_ratio=-0.2,
        days_of_cover=5,
        reason="synthetic low inventory",
    )
    card = FeishuBusinessHub.sales_alert_card(alert)
    assert run.request_id == "spapi-001"
    assert len(repository.metrics) == 1
    assert "人工审批" in str(card)


def test_evidence_to_listing_human_review_golden_path() -> None:
    brief = ProductBrief(
        sku="SYNTHETIC",
        product_name="Schmutzfangmatte",
        category="pet",
        material="Mikrofaser",
        features=["waschbar", "weich", "rutschhemmend", "saugfähig", "pflegeleicht"],
        primary_keywords=["Hundeteppich"],
        target_customer="Hundehaushalte",
        manufacturer="Synthetic GmbH",
        eu_responsible_person="Synthetic GmbH, Berlin",
    )
    evidence = [
        CompetitorEvidence(
            source_id="synthetic:competitor:B0TEST0001",
            asin="B0TEST0001",
            observed_at="2026-07-16T00:00:00Z",
            title="Hundeteppich",
            bullets=["Waschbar"],
            keywords=["Hundeteppich"],
        )
    ]
    draft = asyncio.run(
        ListingOptimizationAgent(
            InMemoryCompetitorSource(evidence), DeterministicGermanGenerator()
        ).run(brief, request_id="trace-listing-001")
    )
    assert len(draft.variants) == 3
    assert all(len(variant.bullets) == 5 for variant in draft.variants)
    assert all(len(variant.title) <= 75 for variant in draft.variants)
    assert all(len(variant.item_highlight) <= 125 for variant in draft.variants)
    assert draft.source_ids == ["synthetic:competitor:B0TEST0001"]
    assert draft.requires_human_review is True


def test_ads_report_to_human_card_golden_path() -> None:
    recommendation = explain_advertising_anomaly(
        report_id="synthetic-ads-report",
        campaign_id="synthetic-campaign",
        window_start=date(2026, 7, 1),
        window_end=date(2026, 7, 2),
        impressions=2000,
        clicks=100,
        purchases=10,
        spend=Decimal("50"),
        attributed_sales=Decimal("200"),
        total_sales=Decimal("500"),
        inventory_units=100,
        price_changed=False,
        today=date(2026, 7, 16),
    )
    card = FeishuBusinessHub.advertising_recommendation_card(recommendation)
    assert recommendation.metrics.acos == 0.25
    assert recommendation.executable is False
    assert "synthetic-ads-report" in str(card)
