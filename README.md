# Amazon AI Platform

> Docker 完全零基础读者请先阅读：[Docker 与 Docker Compose 零基础学习手册](DOCKER_BEGINNER_GUIDE.md)。

面向 Amazon 德国站的生产级 AI Agent 作品集。项目把简历中的真实经历——服装/宠物类目运营、月 GMV 3 万美元、Python 报表、飞书自动化、C++ 高并发后端——收敛为三条可以现场演示的业务链路，而不是一组互不相连的教程脚本。

> 当前版本完成了可离线验证的核心骨架；真实账号联调、RAG 评测、MCP 和观测平台按 [12 周通关计划](LEARNING_PLAN.md) 逐周完成。README 只把已经有代码和测试的能力标记为完成，避免简历能力先于事实。

## 面试官可以看到什么

1. **销售与流量数据链路**：LWA token 自动刷新 → 分操作令牌桶 → 429/5xx 全抖动重试 → 异步报表轮询 → GZIP 解压 → Pydantic 校验。
2. **Listing 决策链路**：带来源的竞品数据 → LangGraph 三节点 → 并发生成三版德语五点描述 → 确定性规则检查 → 人工审核草稿。
3. **协作链路**：订单幂等同步 Bitable → 销售/库存卡片 → `/选品` 指令 → AI 分析 → trace ID 留痕。
4. **模型基础设施**：OpenAI 兼容的 `/v1/chat/completions` → Claude / DeepSeek / OpenAI 降级链 → 熔断与并发上限 → 服务端注册的 Pydantic Schema 校验。

系统**不会**自动发布 Listing、改价、暂停广告或下采购单。这些动作必须走人工审批。

## 架构

```mermaid
flowchart LR
  A["SP-API / Ads / CSV"] --> B["AsyncSPAPIClient"]
  B --> C["PostgreSQL\n幂等事实表"]
  C --> D["只读业务工具"]
  E["德国站规则 / SOP"] --> F["RAG\n带版本与引用"]
  D --> G["LangGraph Agent"]
  F --> G
  G --> H["Multi-LLM Gateway"]
  G --> I["Human Review"]
  I --> J["Feishu Card / Bitable"]
  K["n8n / Schedule"] --> B
  K --> J
```

共享数据契约位于 `amazon_ai_platform/models.py`，避免 SP-API、Agent、飞书和网关各自维护不一致的 JSON。

## 快速运行

要求 Python 3.11+，CI 使用 Python 3.12。

```bash
cd ecommerce-agent-learning-plan
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# 全部离线，不需要 Amazon、飞书或 LLM Key
python -m examples.01_spapi_client
python -m examples.02_feishu_bot
python -m examples.04_listing_agent
python -m examples.05_amazon_ads_client --demo
python -m examples.06_rag_knowledge_base --demo
pytest
ruff check amazon_ai_platform tests
```

启动网关：

```bash
cp .env.example .env       # Key 可先留空
uvicorn amazon_ai_platform.llm_gateway:app --port 8000
curl http://127.0.0.1:8000/health
```

填入至少一个模型 Key 后调用结构化输出：

```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H 'content-type: application/json' \
  -H 'x-request-id: interview-demo-001' \
  -d '{
    "model":"listing-quality",
    "messages":[{"role":"user","content":"为德国站宠物地毯生成一个德语 Listing 方案"}],
    "response_format":{"type":"json_schema","name":"listing_variant"}
  }'
```

一键启动网关和 PostgreSQL：

```bash
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8000/health
```

## 代码地图

| 模块 | 核心文件 | 已实现的工程细节 |
|---|---|---|
| Data Engine | `amazon_ai_platform/spapi.py` | `AsyncSPAPIClient`、LWA 双检锁刷新、操作级 Token Bucket、动态 rate header、全抖动退避、Sales & Traffic 报表 |
| Business Hub | `amazon_ai_platform/feishu.py` | token 缓存、卡片纯函数、Bitable search + update/create 幂等写、订单同步、事件验签 token、选品指令 |
| Brain Gateway | `amazon_ai_platform/llm_gateway.py` | 标准接口、多 Provider Adapter、fallback、circuit breaker、并发闸门、注册 Schema + Pydantic 二次校验 |
| Decision Engine | `amazon_ai_platform/listing_agent.py` | 三节点显式图、三版五点、来源 ID、德国站规则、GPSR 元数据提醒、人工接管 |
| Business Contracts | `amazon_ai_platform/models.py` | SP-API、Listing、订单、告警的统一 Pydantic 模型 |
| Persistence | `sql/init.sql` | SKU、订单、日指标、告警表及幂等约束 |
| Tests | `tests/` | 报表全链路、429、Bitable upsert、模型降级、非法 JSON、Agent 输出与合规规则 |

四个核心模块的实现均超过 100 行；示例文件只是薄入口，核心逻辑可被服务、任务和测试共同复用。

## 设计选择

- **当前 SP-API 请求默认不要求 AWS Key/SigV4。** 当前 Amazon 上手文档的常规调用凭据是 LWA client/secret、refresh token 与区域 endpoint；客户端仍允许注入 `signer`，用于兼容仍需签名的旧基础设施，但不把历史方案设为默认。
- **限流按操作隔离。** Amazon 的 usage plan 是 operation 维度且可能动态变化；不同 API 共用一个桶会导致低频 Reports 拖垮 Orders。
- **模型输出要验证两次。** Provider 收到 JSON Schema 只是请求，Gateway 仍用 Pydantic 解析；无效 JSON 与超时一样触发下一 Provider。
- **规则检查不用 LLM 自证。** 标题长度、绝对化用语、五点数量等由确定性代码检查；法律适用性和类目规则交给人工与版本化知识库。
- **幂等先于自动化。** 订单以 `AmazonOrderId`、告警以 `source_key` upsert；重跑不会制造重复业务事件。
- **PII 不进入模型。** 当前模型只含订单业务字段，不含姓名、地址、邮箱。需要 PII 的 SP-API 操作必须单独实现 Restricted Data Token 和更严格审计。

## 真实账号联调顺序

1. 先用 Amazon dynamic/static sandbox 验证请求形状。
2. 私有应用自授权，只申请完成演示所需的最小角色；Sales & Traffic 报表需要 Brand Analytics。
3. 首次只拉 7 天并保存 `request_id`、时间范围和原始文件哈希；同一时间范围命中本地缓存。
4. 飞书先用测试群和测试 Bitable；用固定 `source_key` 连续执行两次，证明第二次为更新而非新增。
5. 网关先只开一个低成本模型，再人为让主 Provider 返回 503，展示 fallback_count 和熔断行为。
6. Listing 输出只进入“待审核”表；面试现场由人选择版本，不调用 Amazon 写接口。

## GitHub 展示清单

- `README` 首屏给出业务结果、架构、三条 demo 命令。
- CI 必须通过：`ruff + pytest + offline listing demo`。
- 提交一张脱敏飞书卡片截图、一段 2–3 分钟演示视频和一份 `docs/demo-script.md`。
- 增加 `docs/adr/`：为什么不用一个大 Prompt、为什么不用 LLM 做硬规则、为什么不直接自动执行。
- 测试数据必须标注 `synthetic`；真实销售数字只能写汇总，不上传订单、token、买家信息。
- Release v1.0 的 tag 只在 12 周验收全部通过后创建。

## 参考依据

- [Amazon SP-API onboarding](https://developer-docs.amazon.com/sp-api/docs/onboarding-overview)
- [Amazon Usage Plans and Rate Limits](https://developer-docs.amazon.com/sp-api/docs/usage-plans-and-rate-limits)
- [Sales and Traffic Business Report](https://developer-docs.amazon.com/sp-api/docs/report-type-values-analytics)
- [Reports API request tutorial](https://developer-docs.amazon.com/sp-api/docs/reports-api-v2021-06-30-tutorial-request-a-report)
- [Feishu server API calling process](https://open.feishu.cn/document/server-docs/api-call-guide/calling-process/get-)
- [EU Regulation 2023/988 (GPSR)](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32023R0988)

完整周计划、避坑矩阵、验收条件与面试 Point 见 [LEARNING_PLAN.md](LEARNING_PLAN.md)。
