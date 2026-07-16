# 威胁模型

## 资产与信任边界

资产包括 LWA/LLM/飞书凭据、seller 数据、聚合指标、规则文档、草稿和人审记录。外部边界为 SP-API/Ads、模型 Provider、飞书 webhook、MCP client 与低代码平台；内部边界为 Gateway、worker、PostgreSQL、Redis。

| 威胁 | 控制 | 验证 |
|---|---|---|
| Prompt injection 请求他人 seller 或写操作 | tenant 从认证上下文注入；MCP 无写工具；scope allowlist | `test_mcp_server.py` |
| 伪造飞书事件 | verification token；操作者 ID；安全错误响应 | `test_business_api.py`、`test_feishu.py` |
| Token/PII 进入日志或模型 | 日志字段 allowlist + seller hash；模型契约无 Buyer 字段 | `test_observability.py` |
| 重试制造重复订单/告警 | DB 唯一键、事务、Bitable search+upsert、状态去重 | pipeline/Feishu 测试 |
| 过期或越权 RAG | effective window、marketplace/category/language/scope 过滤 | `test_rag.py` |
| 模型供应链故障/非法 JSON | timeout、semaphore、熔断、Schema + Pydantic、fallback | `test_gateway.py` |
| 高风险建议被自动执行 | 草稿模型固定 `requires_human_review=true`；无发布方法 | Listing/Ads/MCP 测试 |
| 依赖或镜像漏洞 | `pip-audit`、Trivy、Gitleaks、固定大版本镜像 | GitHub Actions |

PII 类 SP-API 操作不在当前权限域。未来加入时必须单独实现 RDT、细粒度 role、审计与短期存储；不得复用普通报表 token 路径。
