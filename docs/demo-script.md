# 2–3 分钟演示脚本

1. 20 秒：展示 README 架构和三条 golden path，说明所有高风险动作停在人工审核。
2. 35 秒：运行 `python -m examples.01_spapi_client`，指出 LWA、报表轮询、GZIP 和 Pydantic；运行对应 429×2 与事务第 50 行回滚测试。
3. 35 秒：运行 Listing demo，展示三版×五点、`fact_sources`、block/warn、`requires_human_review`；展示 40 条 Prompt 与 50 条 RAG 评测。
4. 30 秒：运行 Gateway fallback 测试，主 Provider 503/非法 JSON 后备用成功；认证错误不 fallback，安全 503 不泄露 Key。
5. 25 秒：展示飞书卡片脱敏截图（需账号持有人补录）、Bitable 同一业务键两次只一行、人工 approve/reject/edit。
6. 20 秒：展示 `docker compose ps`、`/health`、`/metrics` 和 trace；说明 Redis worker SIGTERM draining。

录制前运行 `pytest`、Ruff 和全部离线示例。真实账号画面必须遮蔽 token、订单号、Buyer、群 ID、表 token；没有真实运行证据时明确说 mock demo。
