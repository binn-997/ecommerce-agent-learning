"""Versioned prompt assets and reproducible multi-metric regression evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from .listing_agent import GermanMarketplaceCompliance, ProductBrief
from .models import ListingVariant


class PromptAsset(BaseModel):
    prompt_id: str
    version: str
    marketplace: str
    category: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    template: str


class GoldenCase(BaseModel):
    case_id: str
    category: str
    brief: ProductBrief
    required_keywords: list[str]
    expected_block_rules: list[str] = Field(default_factory=list)
    expected_citation_ids: list[str] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    prompt_id: str
    version: str
    total: int
    schema_pass_rate: float
    hard_rule_pass_rate: float
    block_misses: int
    keyword_coverage: float
    citation_accuracy: float
    human_preference_rate: float | None = None
    failed_case_ids: list[str] = Field(default_factory=list)


class PromptRegistry:
    def __init__(self) -> None:
        self._assets: dict[tuple[str, str, str], PromptAsset] = {}

    def register(self, asset: PromptAsset) -> None:
        key = asset.prompt_id, asset.version, asset.category
        if key in self._assets:
            raise ValueError(f"prompt asset already registered: {key}")
        self._assets[key] = asset

    def get(self, prompt_id: str, version: str, category: str) -> PromptAsset:
        try:
            return self._assets[(prompt_id, version, category)]
        except KeyError as exc:
            raise KeyError(
                f"unknown prompt asset: {prompt_id}/{version}/{category}"
            ) from exc


def listing_prompt(category: str, *, version: str = "2.0.0") -> PromptAsset:
    return PromptAsset(
        prompt_id="listing-de",
        version=version,
        marketplace="amazon.de",
        category=category,
        input_schema=ProductBrief.model_json_schema(),
        output_schema=ListingVariant.model_json_schema(),
        template=(
            "Erzeuge genau eine sachliche Amazon.de Listing-Variante für {category}. "
            "Nutze ausschließlich die übergebenen Fakten und source_ids. "
            "Der Titel darf einschließlich Leerzeichen höchstens 75 Zeichen haben. "
            "Gib zusätzlich genau ein Item Highlight mit höchstens 125 Zeichen für "
            "Material oder empfohlenen Verwendungszweck zurück. "
            "Gib exakt fünf unterschiedliche Bulletpoints zurück; unbelegte absolute, "
            "medizinische oder zertifizierende Aussagen sind verboten."
        ),
    )


@dataclass(frozen=True)
class CaseOutput:
    payload: dict[str, Any]
    citation_ids: list[str]
    human_preferred: bool | None = None


def evaluate_prompt(
    asset: PromptAsset,
    cases: list[GoldenCase],
    outputs: dict[str, CaseOutput],
) -> EvaluationResult:
    """Use deterministic gates; subjective preference is reported, never a release gate."""
    schema_passes = 0
    hard_rule_passes = 0
    block_misses = 0
    keyword_hits = 0
    keyword_total = 0
    citation_hits = 0
    citation_total = 0
    preferences: list[bool] = []
    failures: set[str] = set()
    for case in cases:
        output = outputs.get(case.case_id)
        if output is None:
            failures.add(case.case_id)
            continue
        try:
            variant = ListingVariant.model_validate(output.payload)
            schema_passes += 1
        except ValueError:
            failures.add(case.case_id)
            continue
        issues = GermanMarketplaceCompliance.check(case.brief, [variant])
        actual_blocks = {issue.rule for issue in issues if issue.severity == "block"}
        expected = set(case.expected_block_rules)
        missed = expected.difference(actual_blocks)
        block_misses += len(missed)
        if not missed and not actual_blocks.difference(expected):
            hard_rule_passes += 1
        else:
            failures.add(case.case_id)
        searchable = " ".join(
            [
                variant.title,
                variant.item_highlight,
                *variant.bullets,
                *variant.backend_keywords,
            ]
        ).casefold()
        keyword_total += len(case.required_keywords)
        keyword_hits += sum(
            keyword.casefold() in searchable for keyword in case.required_keywords
        )
        citation_total += len(case.expected_citation_ids)
        citation_hits += len(
            set(case.expected_citation_ids).intersection(output.citation_ids)
        )
        if output.human_preferred is not None:
            preferences.append(output.human_preferred)
    total = len(cases)
    return EvaluationResult(
        prompt_id=asset.prompt_id,
        version=asset.version,
        total=total,
        schema_pass_rate=schema_passes / total if total else 0,
        hard_rule_pass_rate=hard_rule_passes / total if total else 0,
        block_misses=block_misses,
        keyword_coverage=keyword_hits / keyword_total if keyword_total else 1,
        citation_accuracy=citation_hits / citation_total if citation_total else 1,
        human_preference_rate=(
            sum(preferences) / len(preferences) if preferences else None
        ),
        failed_case_ids=sorted(failures),
    )


def compare_evaluations(
    baseline: EvaluationResult, candidate: EvaluationResult
) -> dict[str, float | int | str]:
    if baseline.prompt_id != candidate.prompt_id:
        raise ValueError("cannot compare different prompt IDs")
    return {
        "prompt_id": baseline.prompt_id,
        "baseline_version": baseline.version,
        "candidate_version": candidate.version,
        "schema_pass_rate_delta": candidate.schema_pass_rate
        - baseline.schema_pass_rate,
        "hard_rule_pass_rate_delta": candidate.hard_rule_pass_rate
        - baseline.hard_rule_pass_rate,
        "block_miss_delta": candidate.block_misses - baseline.block_misses,
        "keyword_coverage_delta": candidate.keyword_coverage
        - baseline.keyword_coverage,
        "citation_accuracy_delta": candidate.citation_accuracy
        - baseline.citation_accuracy,
    }
