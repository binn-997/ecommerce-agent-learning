"""Shared, provider-independent business contracts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


LISTING_TITLE_MAX_LENGTH = 75
LISTING_ITEM_HIGHLIGHT_MAX_LENGTH = 125


def safe_ratio(
    numerator: int | float | Decimal, denominator: int | float | Decimal
) -> float | None:
    """Return a ratio without turning missing evidence into a misleading zero."""
    if denominator == 0:
        return None
    return float(numerator / denominator)


class Money(BaseModel):
    amount: float = 0
    currency_code: str = Field(default="EUR", alias="currencyCode")


class TrafficByAsin(BaseModel):
    model_config = ConfigDict(extra="allow")

    sessions: int = 0
    page_views: int = Field(default=0, alias="pageViews")
    buy_box_percentage: float | None = Field(default=None, alias="buyBoxPercentage")
    unit_session_percentage: float | None = Field(
        default=None, alias="unitSessionPercentage"
    )


class SalesByAsin(BaseModel):
    model_config = ConfigDict(extra="allow")

    units_ordered: int = Field(default=0, alias="unitsOrdered")
    ordered_product_sales: Money = Field(
        default_factory=Money, alias="orderedProductSales"
    )


class AsinPerformance(BaseModel):
    model_config = ConfigDict(extra="allow")

    parent_asin: str | None = Field(default=None, alias="parentAsin")
    child_asin: str | None = Field(default=None, alias="childAsin")
    sku: str | None = None
    sales_by_asin: SalesByAsin = Field(alias="salesByAsin")
    traffic_by_asin: TrafficByAsin = Field(alias="trafficByAsin")


class ReportSpecification(BaseModel):
    model_config = ConfigDict(extra="allow")

    report_type: str = Field(alias="reportType")
    data_start_time: str | None = Field(default=None, alias="dataStartTime")
    data_end_time: str | None = Field(default=None, alias="dataEndTime")
    marketplace_ids: list[str] = Field(default_factory=list, alias="marketplaceIds")


class SalesAndTrafficReport(BaseModel):
    """Useful subset of Amazon's JSON report; unknown fields remain available."""

    model_config = ConfigDict(extra="allow")

    report_specification: ReportSpecification = Field(alias="reportSpecification")
    sales_and_traffic_by_asin: list[AsinPerformance] = Field(
        default_factory=list, alias="salesAndTrafficByAsin"
    )


class ListingVariant(BaseModel):
    """A post-July-2026 German-market proposal, never an instruction to publish."""

    title: str = Field(min_length=10, max_length=LISTING_TITLE_MAX_LENGTH)
    item_highlight: str = Field(
        min_length=10, max_length=LISTING_ITEM_HIGHLIGHT_MAX_LENGTH
    )
    bullets: list[str] = Field(min_length=5, max_length=5)
    backend_keywords: list[str] = Field(default_factory=list, max_length=20)
    rationale: str = Field(min_length=10, max_length=1000)

    @model_validator(mode="after")
    def unique_bullets(self) -> "ListingVariant":
        normalized = {bullet.casefold().strip() for bullet in self.bullets}
        if len(normalized) != 5:
            raise ValueError("the five bullets must be distinct")
        return self


class ComplianceIssue(BaseModel):
    severity: Literal["block", "warn"]
    field: str
    rule: str
    evidence: str


class ListingDraft(BaseModel):
    request_id: str
    marketplace: Literal["amazon.de"] = "amazon.de"
    variants: list[ListingVariant] = Field(min_length=3, max_length=3)
    compliance_issues: list[ComplianceIssue] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    fact_sources: dict[str, list[str]] = Field(default_factory=dict)
    requires_human_review: bool = True
    generated_at: str


class OrderSnapshot(BaseModel):
    amazon_order_id: str
    status: str
    purchase_date: str
    order_total: float | None = None
    currency: str | None = None
    marketplace_id: str
    raw_payload: dict[str, Any] = Field(default_factory=dict, exclude=True)


class SalesAlert(BaseModel):
    source_key: str
    sku: str
    metric_date: date
    revenue_eur: float = Field(ge=0)
    change_ratio: float
    acos: float | None = Field(default=None, ge=0)
    days_of_cover: int = Field(ge=0)
    reason: str


class RawSalesTrafficRow(BaseModel):
    """Raw CSV contract; strings are retained so normalization remains auditable."""

    metric_date: str
    sku: str
    parent_asin: str | None = None
    child_asin: str | None = None
    currency: str
    units: str
    sessions: str
    revenue: str


class RawOrderRow(BaseModel):
    amazon_order_id: str
    sku: str
    purchase_date: str
    status: str
    currency: str
    amount: str


class RawAdvertisingRow(BaseModel):
    metric_date: str
    campaign_id: str
    sku: str
    currency: str
    impressions: str
    clicks: str
    purchases: str
    spend: str
    attributed_sales: str


class StandardSalesTrafficRow(BaseModel):
    metric_date: date
    sku: str = Field(min_length=1, max_length=128)
    parent_asin: str | None = Field(default=None, pattern=r"^[A-Z0-9]{10}$")
    child_asin: str | None = Field(default=None, pattern=r"^[A-Z0-9]{10}$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    units: int = Field(ge=0)
    sessions: int = Field(ge=0)
    revenue: Decimal = Field(ge=0, max_digits=14, decimal_places=2)

    @property
    def idempotency_key(self) -> tuple[date, str]:
        return self.metric_date, self.sku

    @property
    def cvr(self) -> float | None:
        return safe_ratio(self.units, self.sessions)


class StandardOrderRow(BaseModel):
    amazon_order_id: str = Field(min_length=1, max_length=64)
    sku: str = Field(min_length=1, max_length=128)
    purchase_date: datetime
    status: str = Field(min_length=1, max_length=64)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class StandardAdvertisingRow(BaseModel):
    metric_date: date
    campaign_id: str = Field(min_length=1, max_length=128)
    sku: str = Field(min_length=1, max_length=128)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    impressions: int = Field(ge=0)
    clicks: int = Field(ge=0)
    purchases: int = Field(ge=0)
    spend: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    attributed_sales: Decimal = Field(ge=0, max_digits=14, decimal_places=2)

    @model_validator(mode="after")
    def counts_are_consistent(self) -> "StandardAdvertisingRow":
        if self.clicks > self.impressions:
            raise ValueError("clicks cannot exceed impressions")
        if self.purchases > self.clicks:
            raise ValueError("purchases cannot exceed clicks")
        return self


class AdvertisingMetrics(BaseModel):
    impressions: int = Field(ge=0)
    clicks: int = Field(ge=0)
    purchases: int = Field(ge=0)
    spend: Decimal = Field(ge=0)
    attributed_sales: Decimal = Field(ge=0)
    total_sales: Decimal | None = Field(default=None, ge=0)
    acos: float | None
    ctr: float | None
    cvr: float | None
    cpc: float | None
    tacos: float | None

    @classmethod
    def calculate(
        cls,
        *,
        impressions: int,
        clicks: int,
        purchases: int,
        spend: Decimal,
        attributed_sales: Decimal,
        total_sales: Decimal | None = None,
    ) -> "AdvertisingMetrics":
        return cls(
            impressions=impressions,
            clicks=clicks,
            purchases=purchases,
            spend=spend,
            attributed_sales=attributed_sales,
            total_sales=total_sales,
            acos=safe_ratio(spend, attributed_sales),
            ctr=safe_ratio(clicks, impressions),
            cvr=safe_ratio(purchases, clicks),
            cpc=safe_ratio(spend, clicks),
            tacos=safe_ratio(spend, total_sales) if total_sales is not None else None,
        )


class DailyBusinessMetrics(BaseModel):
    """Metric-layer contract; financial ratios are calculated, never supplied by an LLM."""

    metric_date: date
    sku: str
    units: int = Field(ge=0)
    sessions: int = Field(ge=0)
    revenue: Decimal = Field(ge=0)
    advertising: AdvertisingMetrics | None = None
    sales_cvr: float | None

    @classmethod
    def from_sales(
        cls,
        sales: StandardSalesTrafficRow,
        advertising: AdvertisingMetrics | None = None,
    ) -> "DailyBusinessMetrics":
        return cls(
            metric_date=sales.metric_date,
            sku=sales.sku,
            units=sales.units,
            sessions=sales.sessions,
            revenue=sales.revenue,
            advertising=advertising,
            sales_cvr=sales.cvr,
        )


class DataQualityIssue(BaseModel):
    rule_id: str
    severity: Literal["error", "warning"]
    row_number: int | None = None
    field: str | None = None
    message: str


class ReconciliationReport(BaseModel):
    source_total: Decimal
    normalized_total: Decimal
    difference: Decimal
    difference_ratio: float | None
    within_tolerance: bool
    explanation: str | None = None


class PolicyDocument(BaseModel):
    document_id: str
    version: str
    title: str
    text: str
    effective_from: date
    effective_to: date | None = None
    marketplace: str
    category: str
    language: str
    access_scope: str
    source_url: str

    @field_validator("source_url")
    @classmethod
    def source_must_be_traceable(cls, value: str) -> str:
        if not value.startswith(("https://", "urn:")):
            raise ValueError("source_url must be https or an internal urn")
        return value


class Citation(BaseModel):
    chunk_id: str
    document_id: str
    version: str
    source_url: str
    score: float


class GroundedAnswer(BaseModel):
    status: Literal["answered", "insufficient_evidence", "access_denied"]
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    requires_human_review: bool = False
