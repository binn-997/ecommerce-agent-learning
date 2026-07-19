# 项目结构说明

## 项目目的与边界

Amazon AI Platform 是面向德国站跨境电商运营流程的个人实战项目。它将报表数据、规则知识、模型生成和人工审核串为可验证的工程链路，重点展示异步 I/O、数据契约、可靠性设计、Provider adapter 和 AI Agent 安全边界。

仓库默认提供离线 synthetic 验证，不包含真实 Amazon、Ads、飞书或 LLM 凭据，也不将任何高风险运营动作自动写回外部系统。

## 目录职责

| 路径 | 职责 |
|---|---|
| `amazon_ai_platform/models.py` | 跨模块 Pydantic v2 数据契约，包括销售、订单、广告与 Listing 草稿模型 |
| `amazon_ai_platform/spapi.py` | 异步 SP-API 报表客户端、LWA 刷新、限流与可恢复失败重试 |
| `amazon_ai_platform/pipeline.py`、`data_quality.py` | Raw → Standard → Metric 管道、事务、幂等、质量规则与对账 |
| `amazon_ai_platform/llm_gateway.py` | OpenAI 兼容 Gateway、Provider adapter、fallback、熔断与结构化输出校验 |
| `amazon_ai_platform/listing_agent.py`、`prompts.py`、`rag.py` | Listing 决策图、Prompt 版本、规则检索、引用和德国站合规检查 |
| `amazon_ai_platform/ads.py`、`feishu.py` | 广告报表与待审建议、飞书卡片、Bitable 幂等同步和指令路由 |
| `amazon_ai_platform/mcp_server.py` | 最小只读 MCP 工具与认证上下文注入 |
| `amazon_ai_platform/business_api.py`、`worker.py`、`telemetry.py` | Webhook、Redis worker、优雅退出、trace 与指标 |
| `tests/` | 离线、确定、可重复的 pytest 测试；只 mock 外部协议边界 |
| `examples/` | 可直接运行的薄演示入口 |
| `sql/`、`alembic/` | PostgreSQL 初始化、迁移与数据结构演进 |
| `workflows/` | 低代码调度、Webhook 和等待人工审核流程 |

## 三条业务链路

### 1. 报表与数据质量

`AsyncSPAPIClient` 创建、轮询并解析报表，管道将数据保存为 raw、standard、metric 三层。事务和稳定业务键防止重试造成重复数据；质量规则、reconciliation 与 trace 让异常可以追溯到原始文件和请求上下文。

### 2. Listing 决策草稿

读取可信商品事实和版本化规则后，LangGraph 生成三个候选版本、执行确定性合规检查，并返回待审草稿。2026-07-27 起，非媒体类目的 `title` 最多 75 字符，`item_highlight` 最多 125 字符。流程不包含 Seller Central 发布接口；每一份草稿都要求人工审核。

### 3. 协作与运行

飞书层将订单/建议写入 Bitable 时通过业务键 upsert，避免重复通知与重复记录。Gateway 屏蔽不同模型 Provider 的请求协议差异，Redis worker 处理后台任务并在 SIGTERM 时停止拉取新任务、等待当前任务结束。日志和 telemetry 以 trace 关联请求，同时避免记录密钥和 Buyer PII。

## 本地验收

```bash
source .venv/bin/activate
pytest
ruff check amazon_ai_platform tests examples
python -m examples.01_spapi_client
python -m examples.04_listing_agent
python -m examples.05_amazon_ads_client --demo
python -m examples.06_rag_knowledge_base --demo
alembic upgrade head --sql > /tmp/amazon-ai-migration.sql
docker compose config --quiet
```

需要检查容器编排时：

```bash
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8000/health
docker compose down
```

Docker Compose 包含 `gateway`、`worker`、`postgres` 和 `redis` 四个服务。`gateway` 提供 `/health`，服务间通过 Compose 服务名访问数据库和 Redis；普通 `down` 不删除命名卷。

## 外部验证边界

真实账号验证应在最小权限的 sandbox 或测试租户中完成，并记录脱敏后的 request ID、测试时间范围、Bitable 幂等结果和 Provider 故障切换证据。真实订单、Buyer 信息、Token、应用密钥、生产数据库与未脱敏截图不得进入 Git。

离线测试能够证明代码对模拟协议和故障路径的行为，不能替代真实 Amazon 或飞书环境的联调结论。
