from fastapi.testclient import TestClient

from amazon_ai_platform.business_api import create_business_app
from amazon_ai_platform.feishu import FeishuBusinessHub


class Analyzer:
    async def analyze(self, query, *, operator_id):
        return {"summary": "synthetic", "trace_id": "trace"}


def test_feishu_webhook_rejects_forged_verification_token() -> None:
    app = create_business_app(
        FeishuBusinessHub(app_id="id", app_secret="secret", verification_token="expected"),
        Analyzer(),
    )
    with TestClient(app) as client:
        response = client.post("/webhooks/feishu", json={
            "header": {"token": "forged"},
            "event": {"message": {"message_type": "text", "content": "{}"}},
        })
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "feishu_event_rejected"
