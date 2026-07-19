# AGENTS.md — Amazon AI Platform 项目协作规范

本文件适用于 `ecommerce-agent-learning-plan/` 及其所有子目录。进入本项目工作的 AI Agent 和开发者必须遵守本文件；仓库根目录的 `../AGENTS.md` 仍然有效，若规则冲突，以本文件中更具体的项目规则为准。

## 1. 项目目标

本项目是面向面试和 GitHub 展示的跨境电商 AI Agent 作品集，目标是把以下真实背景转化为可运行、可测试、可解释的工程成果：

- Amazon 德国站服装/宠物类目运营经验；
- 月 GMV 3 万美元以上的业务经验；
- C++、gRPC 和分布式后端开发能力；
- Python 报表与飞书自动化经验；
- 面向生产环境的 AI Agent 架构能力。

代码落地优先于概念堆砌。新增功能必须解决明确的跨境电商业务问题，并具备可运行入口、确定性测试、错误处理和文档说明。

项目当前定位是“可离线验证的核心骨架”。除非已有真实账号联调、测试证据和运行记录，否则不得声称某项能力已经生产上线。

## 2. 开工前必须阅读

按任务范围阅读以下文件：

1. `README.md`：当前架构、已实现能力、快速运行和代码地图；
2. `docs/LEARNING_PLAN.md`：12 周里程碑、15 阶段覆盖和简历升级门槛；
3. `docs/DOCKER_BEGINNER_GUIDE.md`：容器、Gateway、Compose、部署和排错；
4. `.env.example`：支持的环境变量；
5. 需要修改的模块及对应测试。

不要根据文件名猜测现状。修改前先检查源码、测试、Git 状态和当前分支。

## 3. 目录和职责

```text
ecommerce-agent-learning-plan/
├── amazon_ai_platform/       # 可复用的生产代码
│   ├── models.py             # 跨模块共享的 Pydantic 数据契约
│   ├── spapi.py / ads.py     # Amazon 销售与广告报表客户端
│   ├── pipeline.py           # raw→标准指标、事务与幂等持久化
│   ├── data_quality.py       # CSV 校验、质量规则与 reconciliation
│   ├── feishu.py             # 飞书卡片、Bitable 和指令处理
│   ├── llm_gateway.py        # FastAPI 多模型统一网关
│   ├── listing_agent.py      # LangGraph Listing 决策流程
│   ├── prompts.py / rag.py   # 版本化 Prompt、规则知识库与评测
│   ├── mcp_server.py         # 只读 MCP 工具与认证上下文
│   ├── business_api.py       # webhook/API 组装
│   └── worker.py / telemetry.py # Redis worker、遥测与优雅退出
├── examples/                 # 薄的可运行示例，不承载核心业务逻辑
├── tests/                    # 离线、确定性的 pytest 测试
├── sql/init.sql              # PostgreSQL 初始化脚本
├── Dockerfile                # gateway 镜像构建定义
├── docker-compose.yml        # gateway + worker + postgres + redis 编排
├── .env.example              # 环境变量模板，不含真实密钥
├── README.md                 # 面试官和使用者的项目入口
├── docs/LEARNING_PLAN.md          # 学习与交付路线
└── docs/DOCKER_BEGINNER_GUIDE.md  # Docker 零基础教材
```

放置规则：

- 可复用业务逻辑放入 `amazon_ai_platform/`；
- 示例仅负责组装依赖、构造演示数据和调用模块；
- 数据库结构变更放入 `sql/`，并说明兼容或迁移策略；
- 测试文件使用 `tests/test_<module>.py`；
- 不在示例脚本中复制生产模块实现；
- 不把第三方源码、生成缓存或真实业务导出文件放入项目。

## 4. 当前架构边界

### 4.1 SP-API Data Engine

`AsyncSPAPIClient` 负责：

- LWA OAuth2 Token 自动刷新；
- 并发刷新保护；
- 按 operation 管理令牌桶限流；
- 读取 Amazon rate-limit 响应头进行自适应；
- 对 429 和可恢复 5xx 做带抖动重试；
- 创建、轮询、下载和解析 Sales & Traffic Report；
- 使用 Pydantic 校验外部数据。

不要重新加入已经过时或当前流程不需要的 AWS SigV4 假设。若 Amazon 官方流程发生变化，必须依据最新官方文档更新代码与说明。

### 4.2 Feishu Business Hub

飞书模块负责消息卡片、Bitable 幂等同步和指令路由。所有写操作必须：

- 使用稳定业务键保证幂等；
- 处理 Token 失效和 API 错误；
- 避免在日志、卡片或测试夹具中泄露买家 PII；
- 对选品分析等 AI 结果标注 trace ID 或可追溯信息。

### 4.3 Multi-LLM Gateway

`gateway` 是 Compose 服务名，也是 FastAPI 提供的统一 LLM API 入口，不是 Docker 专有概念。网关负责：

- OpenAI 风格的 `/v1/chat/completions`；
- Claude、DeepSeek、OpenAI 等 provider adapter；
- Pydantic JSON Schema 结构化输出；
- 超时、并发上限、熔断和自动降级；
- 一致的错误响应和健康检查。

provider 特有的请求与响应必须封装在 adapter 边界内，不得污染共享业务模型。新增 provider 时应复用统一协议并添加 fallback 测试。

### 4.4 Data, Ads 与 Runtime

`pipeline.py` 将销售、订单和广告数据以 raw/standard/metric 分层处理，事务仓储支持回滚与游标；`data_quality.py` 负责 synthetic CSV 的结构、ASIN、金额和 reconciliation 检查。`ads.py` 只生成带证据和归因窗口保护的待审广告建议。`worker.py` 消费 Redis 任务并在 SIGTERM 时 draining；`business_api.py` 提供 webhook 入口，`telemetry.py`/`observability.py` 统一 trace、指标和脱敏事件。

### 4.5 LangGraph Decision Engine

Listing Agent 至少包含：

1. 读取可信的竞品或 SP-API 数据；
2. 生成 3 个版本、每版 5 条德语卖点；
3. 执行德国站确定性合规检查；
4. 输出草稿供人工审核。

Agent 不得自动发布 Listing、改价、暂停广告或创建采购单。高风险动作必须保持 human-in-the-loop，并且默认只生成建议或草稿。

## 5. 编码规范

- 支持 Python 3.11+，CI 与容器使用 Python 3.12；
- 使用 4 空格缩进；
- 函数、变量和模块使用 `snake_case`；
- 类和 Pydantic Model 使用 `PascalCase`；
- 常量使用 `UPPER_SNAKE_CASE`；
- 公共接口必须有类型标注；
- 外部 HTTP、数据库和 LLM 调用优先使用异步 I/O；
- 跨模块数据契约优先放入 `models.py`；
- 使用小而明确的函数，避免超长 orchestration 函数；
- 错误信息应包含 operation、provider 或 trace context，但不得包含密钥和 PII；
- 不使用裸 `except:`，不要静默吞掉异常；
- 不为“未来可能需要”预先引入抽象层；
- Ruff 默认规则是最低静态检查标准。

注释解释“为什么”和业务约束，不重复代码表面行为。公开 API 或复杂状态机应提供简短 docstring。

## 6. 测试规范

测试必须离线、确定、可重复。CI 不得依赖 Amazon、飞书、LLM 真实账号或公网。

每次行为变更至少覆盖相关场景：

- 正常成功路径；
- 超时、429、5xx 和重试上限；
- Token 刷新及并发刷新；
- provider fallback 和熔断；
- 非法或不完整的结构化输出；
- 幂等写入和重复事件；
- 合规规则命中及人工审核边界。

命名：

```text
tests/test_<module>.py
test_<observable_behavior>()
```

Mock 外部系统的协议边界，不要把被测业务逻辑本身 mock 掉。测试数据必须明确为 synthetic，不得使用真实订单、Buyer 信息或密钥。

提交前最低验证：

```bash
source .venv/bin/activate
pytest
ruff check amazon_ai_platform tests examples
python -m examples.04_listing_agent
python -m examples.05_amazon_ads_client --demo
python -m examples.06_rag_knowledge_base --demo
alembic upgrade head --sql > /tmp/amazon-ai-migration.sql
```

如果只修改文档，至少运行：

```bash
git diff --check
```

## 7. 本地开发命令

首次建立环境：

```bash
cd /Users/cpt/project/aiyy/ecommerce-agent-learning-plan
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

常用命令：

```bash
pytest
ruff check amazon_ai_platform tests examples
uvicorn amazon_ai_platform.llm_gateway:app --host 0.0.0.0 --port 8000
python -m examples.01_spapi_client
python -m examples.02_feishu_bot
python -m examples.03_llm_gateway
python -m examples.04_listing_agent
```

不需要真实 Key 的演示必须明确保持离线模式；需要真实账号的命令不得成为默认测试步骤。

## 8. Docker 与 Compose 操作规范

macOS 使用 Colima 承载 Docker Engine。详细原理见 `docs/DOCKER_BEGINNER_GUIDE.md`。

部署前：

```bash
colima status
docker info
cd /Users/cpt/project/aiyy/ecommerce-agent-learning-plan
docker compose config --quiet
```

构建、启动和验收：

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 gateway
curl http://127.0.0.1:8000/health
```

安全关闭：

```bash
docker compose down
```

规则：

- `docker compose pull` 只拉取远程镜像，不更新 Git 代码，也不启动服务；
- 修改当前 gateway 源码后，使用 `docker compose up -d --build gateway`；
- `docker compose down` 默认保留命名卷；
- 未经用户明确要求，不执行 `docker compose down -v`；
- 未经确认，不执行 `docker system prune -a --volumes` 等广泛清理；
- 排错优先查看 `docker compose ps -a`、`logs` 和 `config`；
- Compose 目前包含 `gateway`、`worker`、`postgres`、`redis`；容器间使用服务名通信，例如 `postgres:5432`、`redis:6379`；
- 完成验证后说明容器是否仍在运行，不把后台服务状态留给用户猜测。

## 9. 配置、密钥和数据安全

- 复制 `.env.example` 为 `.env` 后填写真实配置；
- 永远不提交 `.env`、API Key、Refresh Token 或 App Secret；
- 不在命令输出、日志、异常、测试快照或文档中暴露密钥；
- 不提交真实 Buyer PII、订单导出、数据库文件或 Seller Central 截图；
- 示例 ASIN、订单号和指标应明确为合成数据；
- 日志对 Authorization、Token、邮箱、地址等字段进行脱敏；
- PostgreSQL 默认密码只适合本地学习，不能作为生产配置；
- 生产环境数据库不应直接暴露公网端口。

若怀疑密钥已经进入 Git 历史，立即停止继续传播并告知用户轮换密钥；不要仅删除工作区文件后声称问题已经解决。

## 10. 业务安全边界

以下动作默认禁止自动执行：

- 发布或覆盖 Amazon Listing；
- 自动改价；
- 暂停、启用或修改广告预算；
- 创建采购单或补货单；
- 向真实客户或团队群发送未经确认的消息；
- 将未经审核的模型输出写回生产系统。

这些能力只能以 dry-run、建议、草稿或待审批操作实现。若未来加入真实写入能力，必须同时提供：

- 明确的人审节点；
- 幂等键；
- 审计日志；
- 权限范围；
- 失败补偿或回滚；
- 对应测试与运行手册。

## 11. 文档同步规则

代码与文档必须保持一致：

- 新增能力或入口：更新 `README.md` 的代码地图与运行方式；
- 改变学习顺序或交付门槛：更新 `docs/LEARNING_PLAN.md`；
- 改变 Dockerfile、Compose、端口、服务名或数据卷：同步更新 `docs/DOCKER_BEGINNER_GUIDE.md`；
- 新增环境变量：更新 `.env.example`，只放空值或安全默认值；
- 改变 API 契约：提供请求/响应示例并更新测试；
- 未完成的能力不得在 README 或简历表述中写成已经完成。

文档统一使用简体中文；命令、类型名、API 字段和必要术语保留英文。

## 12. Git 和提交规则

- 开工前执行 `git status --short` 和 `git branch --show-current`；
- 开工后保持当前工作分支，不擅自切换或扰乱用户原分支；若需创建分支，使用 `codex/` 前缀；
- 工作区可能存在用户自己的 staged、modified 或 untracked 文件；
- 只暂存本任务明确修改的路径，不使用无差别 `git add .`；
- 不覆盖、删除、回滚或提交与任务无关的用户改动；
- 禁止使用 `git reset --hard` 或 `git checkout --` 清理用户工作；
- 提交保持单一目的，使用简洁 Conventional Commit；
- 未经用户明确要求，不 push、不创建 PR、不改写历史。

推荐提交类型：

```text
feat:     新业务能力
fix:      缺陷修复
test:     测试补充
docs:     文档更新
refactor: 无行为变化的重构
chore:    工具或维护工作
```

PR 或交付说明应包含：

- 解决的业务痛点；
- 关键设计和风险边界；
- 修改文件；
- 实际运行的验证命令及结果；
- 尚未完成或需要真实账号验证的部分；
- UI 或飞书卡片变化的脱敏截图。

## 13. 完成定义 Definition of Done

一个功能只有同时满足以下条件才算完成：

1. 业务场景和输入输出清晰；
2. 核心逻辑位于正确模块；
3. 外部失败有超时、错误或重试策略；
4. 包含离线回归测试；
5. Ruff 和 pytest 通过；
6. 示例或 API 可以实际运行；
7. 密钥、PII 和高风险动作边界得到保护；
8. README、学习计划、环境模板或 Docker 文档按需同步；
9. Git diff 不包含无关文件；
10. 交付说明不夸大尚未验证的能力。

## 14. 明确不做的内容

本项目优先建设 SP-API、Agent、RAG、MCP、FastAPI、工作流和真实跨境业务闭环。除非用户明确改变方向，不引入：

- 从零训练深度学习模型；
- CNN、RNN 或 Transformer 源码推导项目；
- LoRA/QLoRA 微调流水线；
- GAN 或 Stable Diffusion 训练；
- 与 Amazon AI Platform 无关的大型前端或基础设施；
- 只有概念说明、没有可运行代码和验收标准的“架构功能”。

面对新需求，优先回答：它解决哪个运营痛点、数据从哪里来、决策如何验证、失败如何处理、结果如何被人审核，以及面试官如何在本地复现。
