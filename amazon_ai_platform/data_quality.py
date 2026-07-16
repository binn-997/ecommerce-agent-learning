"""Deterministic contracts, quality gates, idempotent import and reconciliation."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from .models import (
    DataQualityIssue,
    RawSalesTrafficRow,
    ReconciliationReport,
    StandardSalesTrafficRow,
)


QUALITY_RULES: tuple[str, ...] = (
    "DQ01_REQUIRED_COLUMNS",
    "DQ02_DATE_FORMAT",
    "DQ03_DATE_WINDOW",
    "DQ04_NOT_FUTURE",
    "DQ05_SKU_PRESENT",
    "DQ06_SKU_KNOWN",
    "DQ07_IDEMPOTENT_KEY_UNIQUE",
    "DQ08_CURRENCY_FORMAT",
    "DQ09_CURRENCY_EXPECTED",
    "DQ10_UNITS_INTEGER",
    "DQ11_UNITS_NON_NEGATIVE",
    "DQ12_SESSIONS_INTEGER",
    "DQ13_SESSIONS_NON_NEGATIVE",
    "DQ14_REVENUE_DECIMAL",
    "DQ15_REVENUE_NON_NEGATIVE",
    "DQ16_PARENT_ASIN_FORMAT",
    "DQ17_CHILD_ASIN_FORMAT",
    "DQ18_PARENT_CHILD_DIFFERENT",
    "DQ19_UNITS_WITH_REVENUE",
    "DQ20_PARENT_CHILD_PRESENT",
)

REQUIRED_COLUMNS = {
    "metric_date",
    "sku",
    "parent_asin",
    "child_asin",
    "currency",
    "units",
    "sessions",
    "revenue",
}


class DataQualityError(ValueError):
    def __init__(self, issues: list[DataQualityIssue]):
        super().__init__(f"data quality gate failed with {len(issues)} error(s)")
        self.issues = issues


def parse_sales_csv(text: str) -> list[RawSalesTrafficRow]:
    """Parse a de-identified export while preserving raw values for audit."""
    reader = csv.DictReader(io.StringIO(text))
    missing = REQUIRED_COLUMNS.difference(reader.fieldnames or [])
    if missing:
        raise DataQualityError([
            DataQualityIssue(
                rule_id="DQ01_REQUIRED_COLUMNS",
                severity="error",
                message=f"missing columns: {', '.join(sorted(missing))}",
            )
        ])
    return [RawSalesTrafficRow.model_validate(row) for row in reader]


def _is_asin(value: str | None) -> bool:
    return value is not None and len(value) == 10 and value.isalnum() and value.upper() == value


def audit_sales_rows(
    rows: Iterable[RawSalesTrafficRow],
    *,
    known_skus: set[str],
    start: date,
    end: date,
    today: date,
    expected_currency: str = "EUR",
) -> list[DataQualityIssue]:
    """Run the twenty documented assertions without stopping at the first bad row."""
    issues: list[DataQualityIssue] = []
    seen: set[tuple[date, str]] = set()
    for row_number, row in enumerate(rows, start=2):
        parsed_date: date | None = None
        try:
            parsed_date = date.fromisoformat(row.metric_date)
        except ValueError:
            issues.append(_issue("DQ02_DATE_FORMAT", row_number, "metric_date", "use YYYY-MM-DD"))
        if parsed_date is not None:
            if not start <= parsed_date <= end:
                issues.append(_issue("DQ03_DATE_WINDOW", row_number, "metric_date", "outside import window"))
            if parsed_date > today:
                issues.append(_issue("DQ04_NOT_FUTURE", row_number, "metric_date", "future date"))
        if not row.sku.strip():
            issues.append(_issue("DQ05_SKU_PRESENT", row_number, "sku", "SKU is blank"))
        elif row.sku not in known_skus:
            issues.append(_issue("DQ06_SKU_KNOWN", row_number, "sku", "unknown SKU"))
        if parsed_date is not None:
            key = (parsed_date, row.sku)
            if key in seen:
                issues.append(_issue("DQ07_IDEMPOTENT_KEY_UNIQUE", row_number, "sku", "duplicate metric_date + sku"))
            seen.add(key)
        if len(row.currency) != 3 or not row.currency.isalpha() or row.currency.upper() != row.currency:
            issues.append(_issue("DQ08_CURRENCY_FORMAT", row_number, "currency", "currency must be uppercase ISO-4217"))
        elif row.currency != expected_currency:
            issues.append(_issue("DQ09_CURRENCY_EXPECTED", row_number, "currency", f"expected {expected_currency}"))
        units = _parse_int(row.units, "DQ10_UNITS_INTEGER", row_number, "units", issues)
        if units is not None and units < 0:
            issues.append(_issue("DQ11_UNITS_NON_NEGATIVE", row_number, "units", "units cannot be negative"))
        sessions = _parse_int(row.sessions, "DQ12_SESSIONS_INTEGER", row_number, "sessions", issues)
        if sessions is not None and sessions < 0:
            issues.append(_issue("DQ13_SESSIONS_NON_NEGATIVE", row_number, "sessions", "sessions cannot be negative"))
        revenue = _parse_decimal(row.revenue, row_number, issues)
        if revenue is not None and revenue < 0:
            issues.append(_issue("DQ15_REVENUE_NON_NEGATIVE", row_number, "revenue", "revenue cannot be negative"))
        if row.parent_asin and not _is_asin(row.parent_asin):
            issues.append(_issue("DQ16_PARENT_ASIN_FORMAT", row_number, "parent_asin", "invalid parent ASIN"))
        if row.child_asin and not _is_asin(row.child_asin):
            issues.append(_issue("DQ17_CHILD_ASIN_FORMAT", row_number, "child_asin", "invalid child ASIN"))
        if row.parent_asin and row.parent_asin == row.child_asin:
            issues.append(_issue("DQ18_PARENT_CHILD_DIFFERENT", row_number, "child_asin", "parent and child ASIN are equal"))
        if units is not None and units > 0 and revenue == 0:
            issues.append(_issue("DQ19_UNITS_WITH_REVENUE", row_number, "revenue", "positive units with zero revenue", "warning"))
        if not row.parent_asin or not row.child_asin:
            issues.append(_issue("DQ20_PARENT_CHILD_PRESENT", row_number, "parent_asin", "parent and child ASIN are required"))
    return issues


def normalize_sales_rows(rows: Iterable[RawSalesTrafficRow]) -> list[StandardSalesTrafficRow]:
    normalized: list[StandardSalesTrafficRow] = []
    issues: list[DataQualityIssue] = []
    for row_number, row in enumerate(rows, start=2):
        try:
            normalized.append(StandardSalesTrafficRow.model_validate(row.model_dump()))
        except ValidationError as exc:
            issues.append(DataQualityIssue(
                rule_id="SCHEMA_STANDARD_LAYER",
                severity="error",
                row_number=row_number,
                message=str(exc),
            ))
    if issues:
        raise DataQualityError(issues)
    return normalized


class IdempotentMetricStore:
    """Small offline store proving the same database key used by PostgreSQL upsert."""

    def __init__(self) -> None:
        self.rows: dict[tuple[date, str], StandardSalesTrafficRow] = {}

    async def upsert_many(self, rows: Iterable[StandardSalesTrafficRow]) -> int:
        for row in rows:
            self.rows[row.idempotency_key] = row
        return len(self.rows)


def reconcile_revenue(
    rows: Iterable[StandardSalesTrafficRow],
    seller_central_total: Decimal,
    *,
    tolerance: Decimal = Decimal("0.005"),
    explanation: str | None = None,
) -> ReconciliationReport:
    normalized_total = sum((row.revenue for row in rows), start=Decimal("0"))
    difference = normalized_total - seller_central_total
    ratio = None if seller_central_total == 0 else float(abs(difference) / seller_central_total)
    return ReconciliationReport(
        source_total=seller_central_total,
        normalized_total=normalized_total,
        difference=difference,
        difference_ratio=ratio,
        within_tolerance=ratio is None and difference == 0 or ratio is not None and ratio <= float(tolerance),
        explanation=explanation,
    )


def _issue(
    rule_id: str,
    row_number: int,
    field: str,
    message: str,
    severity: str = "error",
) -> DataQualityIssue:
    return DataQualityIssue(
        rule_id=rule_id,
        severity=severity,
        row_number=row_number,
        field=field,
        message=message,
    )


def _parse_int(
    value: str,
    rule_id: str,
    row_number: int,
    field: str,
    issues: list[DataQualityIssue],
) -> int | None:
    try:
        return int(value)
    except ValueError:
        issues.append(_issue(rule_id, row_number, field, "must be an integer"))
        return None


def _parse_decimal(
    value: str, row_number: int, issues: list[DataQualityIssue]
) -> Decimal | None:
    try:
        return Decimal(value)
    except InvalidOperation:
        issues.append(_issue("DQ14_REVENUE_DECIMAL", row_number, "revenue", "must be a decimal"))
        return None
