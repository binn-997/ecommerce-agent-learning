"""FastAPI webhook boundary for Feishu verification and read-only command routing."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from .feishu import FeishuBusinessHub, FeishuError, ProductAnalyzer


def create_business_app(hub: FeishuBusinessHub, analyzer: ProductAnalyzer) -> FastAPI:
    app = FastAPI(title="Amazon AI Platform Business Hub", version="1.0.0")

    @app.post("/webhooks/feishu")
    async def feishu_webhook(event: dict[str, Any]) -> dict[str, Any]:
        try:
            return await hub.handle_event(event, analyzer)
        except FeishuError as exc:
            status = 403 if "verification token" in str(exc) else 502
            raise HTTPException(
                status_code=status,
                detail={"code": "feishu_event_rejected", "feishu_code": exc.code},
            ) from exc

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
