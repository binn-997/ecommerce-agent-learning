"""A fully runnable LangGraph listing workflow. Run: python 04_listing_agent.py --demo."""
from __future__ import annotations

import argparse
import asyncio
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class ListingState(TypedDict, total=False):
    product_name: str
    features: list[str]
    keywords: list[str]
    competitor_summary: str
    title: str
    violations: list[str]
    attempts: int
    approved: bool
    audit_log: list[str]


class MockListingLLM:
    """Deterministic offline model. Replace this class with an HTTP client to Phase 3 Gateway."""
    async def analyse_competitor(self, keywords: list[str]) -> str:
        return f"Competitor pattern: lead with primary keyword '{keywords[0]}', then material and use case."

    async def generate_title(self, state: ListingState) -> str:
        prefix = state["keywords"][0]
        feature_text = ", ".join(state["features"][:2])
        if state.get("attempts", 0) == 0:
            return f"BEST {prefix} - {state['product_name']} with {feature_text}, Guaranteed Miracle Results"
        return f"{prefix} - {state['product_name']} with {feature_text}"


BANNED_TERMS = {"guaranteed", "miracle", "best", "100%"}
MAX_TITLE_LENGTH = 180
llm = MockListingLLM()


async def analyse_competitor(state: ListingState) -> dict:
    summary = await llm.analyse_competitor(state["keywords"])
    return {"competitor_summary": summary, "audit_log": state.get("audit_log", []) + ["competitor analysis complete"]}


async def generate_title(state: ListingState) -> dict:
    title = await llm.generate_title(state)
    return {"title": title, "audit_log": state["audit_log"] + [f"title generated (attempt {state.get('attempts', 0) + 1})"]}


def safety_check(state: ListingState) -> dict:
    normalized = state["title"].lower()
    violations = [f"banned term: {term}" for term in BANNED_TERMS if term in normalized]
    if len(state["title"]) > MAX_TITLE_LENGTH: violations.append(f"title exceeds {MAX_TITLE_LENGTH} chars")
    if state["keywords"][0].lower() not in normalized: violations.append("primary keyword missing")
    return {"violations": violations, "approved": not violations, "audit_log": state["audit_log"] + [f"safety check: {len(violations)} violations"]}


def next_step(state: ListingState) -> str:
    if state["approved"]: return "approved"
    if state.get("attempts", 0) >= 1: return "human_review"
    return "auto_fix"


def auto_fix(state: ListingState) -> dict:
    return {"attempts": state.get("attempts", 0) + 1, "audit_log": state["audit_log"] + ["auto-fix requested"]}


def human_review(state: ListingState) -> dict:
    return {"audit_log": state["audit_log"] + ["sent to human review"]}


graph = StateGraph(ListingState)
graph.add_node("analyse_competitor", analyse_competitor)
graph.add_node("generate_title", generate_title)
graph.add_node("safety_check", safety_check)
graph.add_node("auto_fix", auto_fix)
graph.add_node("human_review", human_review)
graph.add_edge(START, "analyse_competitor")
graph.add_edge("analyse_competitor", "generate_title")
graph.add_edge("generate_title", "safety_check")
graph.add_conditional_edges("safety_check", next_step, {"approved": END, "auto_fix": "auto_fix", "human_review": "human_review"})
graph.add_edge("auto_fix", "generate_title")
graph.add_edge("human_review", END)
app = graph.compile()


async def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--demo", action="store_true"); parser.parse_args()
    result = await app.ainvoke({"product_name": "Washable Pet Rug", "features": ["non-slip backing", "machine washable", "soft fleece"], "keywords": ["pet rug", "dog mat"], "attempts": 0, "audit_log": []})
    print("TITLE:", result["title"])
    print("APPROVED:", result["approved"])
    print("VIOLATIONS:", result["violations"])
    print("AUDIT:", " -> ".join(result["audit_log"]))


if __name__ == "__main__": asyncio.run(main())
