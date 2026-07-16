"""Shared, provider-independent business contracts."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Money(BaseModel):
    amount: float = 0
    currency_code: str = Field(default="EUR", alias="currencyCode")


class TrafficByAsin(BaseModel):
    model_config = ConfigDict(extra="allow")

    sessions: int = 0
    page_views: int = Field(default=0, alias="pageViews")
    buy_box_percentage: float | None = Field(default=None, alias="buyBoxPercentage")
    unit_session_percentage: float | None = Field(default=None, alias="unitSessionPercentage")


class SalesByAsin(BaseModel):
    model_config = ConfigDict(extra="allow")

    units_ordered: int = Field(default=0, alias="unitsOrdered")
    ordered_product_sales: Money = Field(default_factory=Money, alias="orderedProductSales")


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
    """A German-market listing proposal, not an instruction to publish it."""

    title: str = Field(min_length=10, max_length=200)
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
