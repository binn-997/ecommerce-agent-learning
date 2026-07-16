"""Four narrow MCP tools with trusted tenant context and auditable draft-only actions."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Protocol

from pydantic import BaseModel, Field

from .listing_agent import ProductBrief
from .models import GroundedAnswer, ListingDraft


class ToolAccessDenied(PermissionError):
    pass


class AuthContext(BaseModel):
    """Trusted transport context; never populated from model tool arguments."""

    seller_id: str
    marketplace_id: str
    scopes: set[str]
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class SalesMetricsInput(BaseModel):
    sku: str
    start: date
    end: date


class InventoryRiskInput(BaseModel):
    sku: str
    as_of: date


class PolicySearchInput(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    category: str
    as_of: date


class ListingDraftInput(BaseModel):
    brief: ProductBrief
    request_id: str


class ToolResult(BaseModel):
    trace_id: str
    seller_id_hash: str
    marketplace_id: str
    data: dict[str, Any]
    requires_human_review: bool = False


class ToolBackend(Protocol):
    async def sales_metrics(
        self, seller_id: str, marketplace_id: str, request: SalesMetricsInput
    ) -> dict[str, Any]: ...

    async def inventory_risk(
        self, seller_id: str, marketplace_id: str, request: InventoryRiskInput
    ) -> dict[str, Any]: ...

    async def search_policy(
        self, context: AuthContext, request: PolicySearchInput
    ) -> GroundedAnswer: ...

    async def draft_listing(
        self, seller_id: str, marketplace_id: str, request: ListingDraftInput
    ) -> ListingDraft: ...


class MCPToolService:
    TOOL_SCOPES = {
        "get_sales_metrics": "sales:read",
        "get_inventory_risk": "inventory:read",
        "search_policy": "policy:read",
        "draft_listing": "listing:draft",
    }

    def __init__(self, context: AuthContext, backend: ToolBackend) -> None:
        self.context = context
        self.backend = backend
        self.audit_log: list[dict[str, str]] = []

    def _authorize(self, tool: str) -> None:
        required = self.TOOL_SCOPES[tool]
        if required not in self.context.scopes:
            self.audit_log.append({
                "trace_id": self.context.trace_id,
                "tool": tool,
                "outcome": "denied",
            })
            raise ToolAccessDenied(f"tool={tool} requires scope={required}")

    def _result(
        self, tool: str, data: dict[str, Any], *, human_review: bool = False
    ) -> ToolResult:
        import hashlib

        self.audit_log.append({
            "trace_id": self.context.trace_id,
            "tool": tool,
            "outcome": "success",
        })
        return ToolResult(
            trace_id=self.context.trace_id,
            seller_id_hash=hashlib.sha256(self.context.seller_id.encode()).hexdigest()[:16],
            marketplace_id=self.context.marketplace_id,
            data=data,
            requires_human_review=human_review,
        )

    async def get_sales_metrics(self, request: SalesMetricsInput) -> ToolResult:
        self._authorize("get_sales_metrics")
        data = await self.backend.sales_metrics(
            self.context.seller_id, self.context.marketplace_id, request
        )
        return self._result("get_sales_metrics", data)

    async def get_inventory_risk(self, request: InventoryRiskInput) -> ToolResult:
        self._authorize("get_inventory_risk")
        data = await self.backend.inventory_risk(
            self.context.seller_id, self.context.marketplace_id, request
        )
        return self._result("get_inventory_risk", data)

    async def search_policy(self, request: PolicySearchInput) -> ToolResult:
        self._authorize("search_policy")
        answer = await self.backend.search_policy(self.context, request)
        return self._result("search_policy", answer.model_dump(mode="json"))

    async def draft_listing(self, request: ListingDraftInput) -> ToolResult:
        self._authorize("draft_listing")
        draft = await self.backend.draft_listing(
            self.context.seller_id, self.context.marketplace_id, request
        )
        if not draft.requires_human_review:
            raise RuntimeError("draft_listing backend violated mandatory human review boundary")
        return self._result(
            "draft_listing", draft.model_dump(mode="json"), human_review=True
        )


def build_mcp_server(service: MCPToolService) -> Any:
    """Build an official MCP SDK v1 FastMCP server; business logic stays testable alone."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(
        "Amazon AI Platform",
        instructions=(
            "Read-only metrics/policy tools and a draft-only listing tool. "
            "No publishing, bid, budget, pricing or purchase-order actions exist."
        ),
    )

    @server.tool()
    async def get_sales_metrics(request: SalesMetricsInput) -> ToolResult:
        """Read sales metrics for the authenticated seller and marketplace."""
        return await service.get_sales_metrics(request)

    @server.tool()
    async def get_inventory_risk(request: InventoryRiskInput) -> ToolResult:
        """Read inventory risk for the authenticated seller and marketplace."""
        return await service.get_inventory_risk(request)

    @server.tool()
    async def search_policy(request: PolicySearchInput) -> ToolResult:
        """Search only currently effective policy documents allowed by auth scope."""
        return await service.search_policy(request)

    @server.tool()
    async def draft_listing(request: ListingDraftInput) -> ToolResult:
        """Create a review-required listing draft; it cannot publish changes."""
        return await service.draft_listing(request)

    return server


def main() -> None:
    raise SystemExit(
        "Wire a ToolBackend in the application composition root; "
        "the MCP transport intentionally has no credential fallback."
    )


if __name__ == "__main__":
    main()
