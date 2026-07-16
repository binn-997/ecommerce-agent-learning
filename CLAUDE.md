# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

本文件覆盖 `ecommerce-agent-learning-plan/`（Amazon AI Platform 作品集项目）。本目录的 [AGENTS.md](AGENTS.md) 是完整协作规范（安全边界、测试要求、Git 规则、Definition of Done），规则冲突时以它为准；仓库根目录的 `../CLAUDE.md` 覆盖整个学习工作区。

## 常用命令

本项目使用独立的 `.venv`（不同于根目录 `projects/` 下各项目直接 pip install 的模式）：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # Key 可留空，所有示例和测试均可离线运行

# 测试与静态检查（必须离线、确定，不依赖真实账号或公网）
pytest                                     # pytest.ini: testpaths=tests, pythonpath=.
pytest tests/test_spapi.py                 # 单文件
pytest tests/test_gateway.py::test_名称    # 单测试
ruff check amazon_ai_platform tests examples

# 离线示例（薄入口，一律用 python -m 运行）
python -m examples.01_spapi_client
python -m examples.02_feishu_bot
python -m examples.04_listing_agent
python -m examples.05_amazon_ads_client --demo
python -m examples.06_rag_knowledge_base --demo

# LLM 网关
uvicorn amazon_ai_platform.llm_gateway:app --port 8000
curl http://127.0.0.1:8000/health

# Docker（macOS 上 Docker Engine 跑在 Colima 里，先 colima status）
docker compose config --quiet
docker compose up -d --build
docker compose logs --tail=100 gateway
docker compose down          # 默认保留卷；未经用户明确要求不执行 down -v
```

提交前最低验证：`pytest` + `ruff check amazon_ai_platform tests examples` + `python -m examples.04_listing_agent`。

## 架构

单一可复用 Python 包 `amazon_ai_platform/` + 薄示例 + 离线测试。模块间唯一的耦合点是 `models.py`——所有跨模块数据结构（SP-API 报表、Listing、订单、告警）都定义在这里，其余四个模块只从它导入；改 API 契约先改这里，并同步测试。

- `spapi.py` — `AsyncSPAPIClient`：LWA token 双检锁刷新、按 operation 隔离的 Token Bucket 限流（Amazon usage plan 是 operation 维度）、读 rate-limit 响应头自适应、429/5xx 全抖动重试、Sales & Traffic 报表创建/轮询/GZIP 解压/Pydantic 校验。默认走 LWA 流程，**不要求 AWS SigV4**（保留可注入 `signer` 兼容旧设施，勿把签名重新设为默认）。
- `llm_gateway.py` — FastAPI 应用（Compose 服务名 `gateway`）：OpenAI 兼容 `/v1/chat/completions`、Claude/DeepSeek/OpenAI adapter 降级链、熔断、并发闸门、服务端注册 JSON Schema + Pydantic 二次校验（provider 返回的 JSON 不可信）。provider 特有请求/响应必须封装在 adapter 边界内，新增 provider 需带 fallback 测试。
- `listing_agent.py` — LangGraph 三节点显式图：带来源的竞品/SP-API 数据 → 并发生成三版德语五点描述 → 确定性合规规则检查 → 人工审核草稿。硬规则（标题长度、绝对化用语、五点数量）用确定性代码检查，不用 LLM 自证。
- `feishu.py` — 飞书卡片纯函数、Bitable 幂等 upsert（稳定业务键，重跑不产生重复事件）、`/选品` 指令路由。

`examples/` 只负责组装依赖和演示数据，不承载业务逻辑；`tests/` mock 外部系统的协议边界（HTTP/LLM），不 mock 被测逻辑本身；`sql/init.sql` 是 PostgreSQL 幂等事实表结构。

## 硬性边界

- Agent 只产出草稿/建议：**不得**自动发布 Listing、改价、操作广告、创建采购单或群发消息——高风险动作一律 human-in-the-loop。
- 测试与 CI 不依赖 Amazon、飞书、LLM 真实账号；测试数据必须是 synthetic，不含真实订单和买家 PII。
- 密钥只从 `.env`/环境变量读取；新增环境变量同步更新 `.env.example`（只放空值或安全默认值）。
- 当前工作分支为 `codex/new`；只暂存本任务相关路径，不用 `git add .`；未经用户要求不 push、不建 PR。
- 文档统一简体中文（命令、类型名、API 字段保留英文）；行为变更需按 AGENTS.md §11 同步 `README.md`、`LEARNING_PLAN.md`、`DOCKER_BEGINNER_GUIDE.md`。
- 未经真实联调验证的能力，不得在文档中写成已完成。
