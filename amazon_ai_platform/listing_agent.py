"""LangGraph Listing Optimization Agent for Amazon Germany.

The graph deliberately stops at a reviewable draft. Publishing, price changes and
advertising mutations are outside this agent's permissions.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .models import ComplianceIssue, ListingDraft, ListingVariant


class ProductBrief(BaseModel):
    sku: str
    product_name: str
    category: str
    material: str
    features: list[str] = Field(min_length=3)
    primary_keywords: list[str] = Field(min_length=1)
    target_customer: str
    manufacturer: str | None = None
    eu_responsible_person: str | None = None


class CompetitorEvidence(BaseModel):
    source_id: str
    asin: str
    observed_at: str
    title: str
    bullets: list[str]
    keywords: list[str]


class CompetitorSource(Protocol):
    async def read(self, brief: ProductBrief) -> list[CompetitorEvidence]: ...


class ListingGenerator(Protocol):
    async def generate(
        self, brief: ProductBrief, evidence: list[CompetitorEvidence], version: int
    ) -> ListingVariant: ...


class ListingState(TypedDict, total=False):
    request_id: str
    brief: dict[str, Any]
    competitor_evidence: list[dict[str, Any]]
    variants: list[dict[str, Any]]
    compliance_issues: list[dict[str, Any]]
    audit_log: list[dict[str, Any]]
    requires_human_review: bool
    result: dict[str, Any]


class InMemoryCompetitorSource:
    """Offline adapter; production replaces it with authorized SP-API/DB reads."""

    def __init__(self, rows: list[CompetitorEvidence]):
        self.rows = rows

    async def read(self, brief: ProductBrief) -> list[CompetitorEvidence]:
        wanted = {keyword.casefold() for keyword in brief.primary_keywords}
        return [
            row
            for row in self.rows
            if wanted.intersection(word.casefold() for word in row.keywords)
        ][:10]


class DeterministicGermanGenerator:
    """Repeatable offline generator used by tests and the GitHub demo."""

    async def generate(
        self, brief: ProductBrief, evidence: list[CompetitorEvidence], version: int
    ) -> ListingVariant:
        keyword = brief.primary_keywords[0]
        angles = [
            ("Komfort", "angenehmen Alltag"),
            ("Material", "verlässliche Nutzung"),
            ("Pflege", "unkomplizierte Routinen"),
        ]
        angle, benefit = angles[version]
        title = f"{keyword} – {brief.product_name}, {brief.material}, {angle} für {brief.target_customer}"
        features = (brief.features * 2)[:5]
        bullets = [
            f"{feature.upper()} – Aspekt {index}: sachlich beschrieben für {benefit}; bitte Maße und Lieferumfang prüfen."
            for index, feature in enumerate(features, start=1)
        ]
        return ListingVariant(
            title=title[:200],
            bullets=bullets,
            backend_keywords=list(dict.fromkeys(brief.primary_keywords)),
            rationale=f"Version {version + 1} priorisiert {angle}; basiert auf {len(evidence)} belegten Wettbewerbsdatensätzen.",
        )


class GermanMarketplaceCompliance:
    """Deterministic guardrails; this is engineering validation, not legal advice."""

    BLOCK_PATTERNS: tuple[tuple[str, str], ...] = (
        (r"\b(best|beste[rsn]?|nummer\s*1|nr\.?\s*1)\b", "unbelegter Superlativ"),
        (r"\b(garantiert\w*|guaranteed|100\s*%)\b", "unbelegtes Garantieversprechen"),
        (r"\b(heilt|therapiert|cures?|miracle)\b", "medizinisches Heilversprechen"),
        (r"\b(kostenlos|free)\b", "preisbezogene Werbeaussage"),
    )

    @classmethod
    def check(
        cls, brief: ProductBrief, variants: list[ListingVariant]
    ) -> list[ComplianceIssue]:
        issues: list[ComplianceIssue] = []
        for index, variant in enumerate(variants, start=1):
            cls._check_text(f"variant[{index}].title", variant.title, issues)
            for bullet_index, bullet in enumerate(variant.bullets, start=1):
                cls._check_text(f"variant[{index}].bullets[{bullet_index}]", bullet, issues)
            if len(variant.title) > 200:
                issues.append(ComplianceIssue(
                    severity="block", field=f"variant[{index}].title",
                    rule="Amazon title length", evidence=f"length={len(variant.title)}",
                ))
            if brief.primary_keywords[0].casefold() not in variant.title.casefold():
                issues.append(ComplianceIssue(
                    severity="warn", field=f"variant[{index}].title",
                    rule="primary keyword missing", evidence=brief.primary_keywords[0],
                ))
        if not brief.manufacturer:
            issues.append(ComplianceIssue(
                severity="warn", field="brief.manufacturer",
                rule="GPSR/product traceability metadata must be reviewed", evidence="missing",
            ))
        if not brief.eu_responsible_person:
            issues.append(ComplianceIssue(
                severity="warn", field="brief.eu_responsible_person",
                rule="EU responsible-person applicability must be reviewed", evidence="missing",
            ))
        return issues

    @classmethod
    def _check_text(
        cls, field: str, text: str, issues: list[ComplianceIssue]
    ) -> None:
        for pattern, rule in cls.BLOCK_PATTERNS:
            if match := re.search(pattern, text, re.IGNORECASE):
                issues.append(ComplianceIssue(
                    severity="block", field=field, rule=rule, evidence=match.group(0),
                ))


class ListingOptimizationAgent:
    def __init__(self, source: CompetitorSource, generator: ListingGenerator) -> None:
        self.source = source
        self.generator = generator
        self.graph = self._compile()

    @staticmethod
    def _audit(state: ListingState, node: str, detail: str) -> list[dict[str, Any]]:
        return state.get("audit_log", []) + [{
            "node": node,
            "detail": detail,
            "at": datetime.now(timezone.utc).isoformat(),
        }]

    async def read_competitor_data(self, state: ListingState) -> dict[str, Any]:
        """Node A: read authorized competitor evidence; never invent observations."""
        brief = ProductBrief.model_validate(state["brief"])
        evidence = await self.source.read(brief)
        return {
            "competitor_evidence": [item.model_dump() for item in evidence],
            "audit_log": self._audit(state, "read_competitor_data", f"sources={len(evidence)}"),
        }

    async def generate_three_versions(self, state: ListingState) -> dict[str, Any]:
        """Node B: generate exactly three structured five-bullet variants."""
        brief = ProductBrief.model_validate(state["brief"])
        evidence = [
            CompetitorEvidence.model_validate(item)
            for item in state.get("competitor_evidence", [])
        ]
        variants = await asyncio.gather(
            *(self.generator.generate(brief, evidence, version) for version in range(3))
        )
        return {
            "variants": [variant.model_dump() for variant in variants],
            "audit_log": self._audit(state, "generate_three_versions", "variants=3; bullets=5 each"),
        }

    async def compliance_check(self, state: ListingState) -> dict[str, Any]:
        """Node C: deterministic Amazon.de checks plus mandatory human handoff."""
        brief = ProductBrief.model_validate(state["brief"])
        variants = [ListingVariant.model_validate(item) for item in state["variants"]]
        issues = GermanMarketplaceCompliance.check(brief, variants)
        evidence = [CompetitorEvidence.model_validate(item) for item in state.get("competitor_evidence", [])]
        draft = ListingDraft(
            request_id=state["request_id"],
            variants=variants,
            compliance_issues=issues,
            source_ids=[item.source_id for item in evidence],
            requires_human_review=True,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        blocks = sum(issue.severity == "block" for issue in issues)
        return {
            "compliance_issues": [issue.model_dump() for issue in issues],
            "requires_human_review": True,
            "result": draft.model_dump(mode="json"),
            "audit_log": self._audit(state, "compliance_check", f"issues={len(issues)}; blocks={blocks}"),
        }

    def _compile(self):
        graph = StateGraph(ListingState)
        graph.add_node("read_competitor_data", self.read_competitor_data)
        graph.add_node("generate_three_versions", self.generate_three_versions)
        graph.add_node("compliance_check", self.compliance_check)
        graph.add_edge(START, "read_competitor_data")
        graph.add_edge("read_competitor_data", "generate_three_versions")
        graph.add_edge("generate_three_versions", "compliance_check")
        graph.add_edge("compliance_check", END)
        return graph.compile()

    async def run(self, brief: ProductBrief, *, request_id: str | None = None) -> ListingDraft:
        initial: ListingState = {
            "request_id": request_id or str(uuid.uuid4()),
            "brief": brief.model_dump(),
            "audit_log": [],
        }
        final = await self.graph.ainvoke(initial)
        return ListingDraft.model_validate(final["result"])


async def demo() -> ListingDraft:
    evidence = [CompetitorEvidence(
        source_id="spapi:catalog:B0DEMO:2026-07-16",
        asin="B0DEMO",
        observed_at="2026-07-16T08:00:00Z",
        title="Hundeteppich für den Innenbereich",
        bullets=["Waschbares Material", "Rutschhemmende Unterseite"],
        keywords=["Hundeteppich", "Schmutzfangmatte Hund"],
    )]
    brief = ProductBrief(
        sku="DE-PET-001",
        product_name="Schmutzfangmatte für Haustiere",
        category="Haustierbedarf",
        material="Mikrofaser",
        features=["waschbar", "saugfähig", "rutschhemmend", "weiche Oberfläche", "pflegeleicht"],
        primary_keywords=["Hundeteppich", "Schmutzfangmatte Hund"],
        target_customer="Hundehaushalte",
        manufacturer="Demo Pet GmbH",
        eu_responsible_person="Demo Pet GmbH, Berlin",
    )
    agent = ListingOptimizationAgent(InMemoryCompetitorSource(evidence), DeterministicGermanGenerator())
    return await agent.run(brief, request_id="demo-listing-001")


if __name__ == "__main__":
    print(json.dumps(asyncio.run(demo()).model_dump(mode="json"), ensure_ascii=False, indent=2))
