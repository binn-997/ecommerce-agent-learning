# 跨境电商 AI Agent 架构师：12 周实战通关计划

## 使用方式

这不是按 `aiyy/docs/01` 到 `15` 顺序读完的课程。每周从一个德国站业务痛点出发，反向选择所需知识并交付可测试代码。建议每周投入 15–20 小时：20% 阅读、60% 编码、20% 测试/复盘。没有达到验收条件，不进入简历“已完成”表述。

最终项目只承诺三条深链路：

1. 销售/库存异常：SP-API → PostgreSQL → 指标 → 飞书 → 人工审批。
2. Listing 优化：竞品证据 + RAG 规则 → LangGraph → 三版德语文案 → 合规报告。
3. 广告解释：Ads 报表 → ACOS/CTR/CVR → 有时间范围的归因 → 飞书留痕。

`aiyy` 15 个阶段全部覆盖，但被重组为“数据可靠性 → 模型基础设施 → 决策系统 → 企业化交付”四个里程碑。

---

## 里程碑 A：数据可靠性（第 1–3 周）

### 第 1 周：把真实运营报表变成可信数据契约

**业务痛点：** 简历已有 Python 报表自动化，但 CSV 列名、币种、日期和父子 ASIN 口径容易漂移，错误数据进入 Agent 后只会生成更自信的错误建议。

**整合章节：** 01 AI 原理（模型边界）、02 Python/Pydantic/asyncio、03 SP-API 入门、现有 `sales_report_generator.py` 与简历 GMV/CVR/ACOS 口径。

**编码任务：**

- 为 Sales & Traffic、订单、广告三类输入建立 Pydantic schema；区分原始层、标准层、指标层。
- 导入简历项目中的脱敏销售 CSV，建立 `metric_date + sku` 联合幂等键。
- 实现 `ACOS = spend / attributed_sales`、`CTR = clicks / impressions`、`CVR = purchases / clicks`，分母为 0 返回 `None` 而非 0。
- 建 20 条数据质量断言：币种、日期范围、负数、重复订单、未知 SKU、父子 ASIN。

**验收：** 同一文件执行两次数据行数不增加；给出一份 reconciliation 报告，说明与 Seller Central 汇总差异不超过 0.5%，或明确解释差异来源。

**面试 Point：** “我先做数据契约和 reconciliation，再做 Agent；GMV、广告归因销售和自然销售不是同一口径。”

### 第 2 周：生产级 AsyncSPAPIClient

**业务痛点：** 403/429、token 过期、动态 usage plan 和长时间异步报表让“能调 API”的脚本无法稳定运行。

**整合章节：** 02 asyncio/httpx、03 SP-API、14 部署基础、15 企业 Agent 的审计要求。

**编码任务：**

- 完成 `amazon_ai_platform/spapi.py`：LWA 刷新双检锁、按 operation 令牌桶、`x-amzn-RateLimit-Limit` 自适应、全抖动指数退避。
- 完成 `create → poll → document → download → gzip → Pydantic` 的 `GET_SALES_AND_TRAFFIC_REPORT`。
- 记录 `x-amzn-RequestId`；只重试 429/临时 5xx/网络错误，400/403 快速失败。
- 增加日期窗口缓存键：seller、marketplace、report type、start/end、options。

**验收：** mock 中前两次 429、第三次成功；20 个并发请求只刷新一次 LWA token；GZIP 报表解析出 units/sessions/CVR；超时和 FATAL 有明确异常。

**面试 Point：** Amazon 限流是 operation + seller/application pair 维度，不能给所有端点硬编码同一个 QPS；全抖动避免多个 worker 同步重试。

### 第 3 周：PostgreSQL、增量同步与可观测数据管道

**业务痛点：** 网络重试或调度重跑会重复订单、重复告警；出了错找不到原始请求与指标来源。

**整合章节：** 03 SP-API、12 n8n、14 Docker、15 Observability。

**编码任务：**

- 使用 `sql/init.sql` 的订单、SKU、日指标、告警表；补 Alembic migration。
- 事务内执行 raw payload 入库、标准化 upsert、同步游标更新；失败整体回滚。
- 增加结构化日志字段：trace_id、seller_id_hash、operation、request_id、date_window、row_count、latency。
- 用 n8n 只负责定时和错误升级，不在 Code Node 中藏核心业务计算。

**验收：** 人为在第 50 行抛错，数据库无半批数据；重跑后行数稳定；可由 trace_id 追到 SP-API request ID 和原始文件哈希。

**面试 Point：** “Exactly once” 不靠口号，而靠至少一次交付 + 数据库幂等键 + 事务 + 可回放原始层。

---

## 里程碑 B：模型基础设施（第 4–6 周）

### 第 4 周：Multi-LLM Gateway 与结构化输出

**业务痛点：** Claude、DeepSeek、OpenAI 参数与错误语义不同，业务 Agent 直接依赖供应商会让降级、成本和审计失控。

**整合章节：** 01 模型/API 原理、02 FastAPI、04 Prompt、05 LLM 网关、14 部署。

**编码任务：**

- 完成 `/v1/chat/completions`，Provider Adapter 隔离 Anthropic 与 OpenAI-compatible 协议。
- 路由别名不绑定易过时的模型 ID；模型 ID 由环境变量配置。
- 主链 Claude → DeepSeek → OpenAI；超时、5xx、非法 JSON 进入 fallback，认证/配额错误告警人工。
- 只允许服务端注册的 Schema；Listing 用 `ListingVariant.model_json_schema()` 请求并用 Pydantic 二次解析。
- 增加 semaphore、熔断、request ID、token、latency、fallback_count；日志不记录 PII/prompt 全文。

**验收：** 主模型 503 时备用成功；主模型返回缺 5 个 bullets 的 JSON 时备用成功；所有 Provider 失败返回不泄露 Key/堆栈的 503。

**面试 Point：** Structured Output 不是“提示模型返回 JSON”，而是 schema 请求 + 本地验证 + 失败路由三层保证。

### 第 5 周：Prompt 资产化与回归评测

**业务痛点：** Prompt 改一行可能提升宠物类目，却破坏西服类目；只凭肉眼挑几个漂亮样例无法上线。

**整合章节：** 04 Prompt、01 模型评测、简历中的西服与宠物两个真实类目。

**编码任务：**

- Prompt 由 `prompt_id/version/marketplace/category/input_schema/output_schema` 管理，不散落在节点函数中。
- 建 40 条脱敏 golden set：西服 20、宠物地毯 20；覆盖德语关键词、尺寸、材质、禁词、证据不足。
- 指标：schema pass rate、硬规则通过率、关键词覆盖、引用正确率、人工偏好；不使用单一“LLM-as-judge 总分”。
- CI 对 schema pass 和硬规则设硬门槛，对主观指标只报告趋势。

**验收：** schema pass 100%，硬规则 block 漏检 0；Prompt 新版本的差异报告可复现，失败样例能定位到版本。

**面试 Point：** 用两个真实经营类目做 domain shift 测试，比展示一个通用 Prompt 更有说服力。

### 第 6 周：RAG 德国站合规与 SOP 知识库

**业务痛点：** Amazon 规则、退货 SOP、品牌语气和 GPSR 信息会变化；把所有规则塞入系统 Prompt 无版本、无引用、无权限。

**整合章节：** 06 LangChain 的文档/检索抽象、08 RAG、德国站运营、15 权限边界。

**编码任务：**

- 文档 metadata：document_id、version、effective_from/to、marketplace、category、language、access_scope、source_url。
- 先实现 paragraph-aware chunk，再接 pgvector/Qdrant；实时订单和销量不进入向量库。
- 建 50 个检索问题，其中 15 个应拒答；测 Recall@5、MRR、引用正确率和过期规则泄漏率。
- 生成答案必须返回 citations；无足够证据输出 `insufficient_evidence` 并转人工。

**验收：** Recall@5 ≥ 0.90；过期文档不会参与当前检索；越权用户无法检索品牌私有 SOP；拒答集正确率 ≥ 0.90。

**面试 Point：** RAG 质量先看 retrieval 和权限过滤，再看答案是否流畅；订单状态走只读工具，不走 RAG。

---

## 里程碑 C：决策与协作闭环（第 7–9 周）

### 第 7 周：LangGraph Listing Optimization Agent

**业务痛点：** 一个大 Prompt 无法证明竞品事实来源，也无法稳定做三版本生成、规则检查和人工接管。

**整合章节：** 06 LangChain、07 LangGraph、04 Prompt、08 RAG、15 Human-in-the-Loop。

**编码任务：**

- Node A `read_competitor_data`：只读授权数据并保留 source_id/observed_at。
- Node B `generate_three_versions`：调用 Gateway 并发生成三个 `ListingVariant`，每版严格五条 bullets。
- Node C `compliance_check`：标题长度、绝对化宣传、医疗声明、主关键词、GPSR 元数据；规则与法务判断分离。
- 加 checkpoint、幂等 request_id、最大重试次数、人工 approve/reject/edit 节点。

**验收：** 离线 demo 固定输出三版；每版五点；每个事实有来源；违规词必被 block；任何结果 `requires_human_review=true`。

**面试 Point：** 图的价值是可观测状态转移与可中断恢复，不是把三个 Python 函数画成图。

### 第 8 周：飞书 Business Hub

**业务痛点：** AI 分析如果停留在命令行，运营团队无法留痕、协作和接管；重复推送又会制造告警疲劳。

**整合章节：** 13 飞书、02 FastAPI webhook、12 n8n、15 审批/权限。

**编码任务：**

- 完成 `FeishuBusinessHub`：tenant token 缓存、消息卡片、Bitable 幂等 upsert、订单状态同步。
- `/选品 关键词/ASIN` 事件验证、操作者 ID、trace ID、超时友好回复；机器人只调用只读工具。
- 卡片同时展示时间范围、指标口径、来源、置信/限制、人工按钮。
- 对重复 `source_key` 只更新 Bitable；只有状态/严重度变化才再次通知。

**验收：** 同一订单同步两次只一条记录；伪造 verification token 被拒绝；飞书错误码被转成可检索异常；选品命令 5 秒内先确认接收。

**面试 Point：** 飞书不是展示皮肤，而是 Agent 的 human-in-the-loop 控制面与审计入口。

### 第 9 周：广告异常解释 Agent

**业务痛点：** “ACOS 上升就降价/关词”忽略归因窗口、自然单、库存和活动阶段，容易做出错误动作。

**整合章节：** 03 数据底座、05 Gateway、07 LangGraph、12 n8n、简历中的 CPC/PPC 经验。

**编码任务：**

- Ads Reporting v3 异步创建、轮询、下载；明确 profile ID 与 marketplace ID 不同。
- 规则引擎先计算 ACOS、CTR、CVR、CPC、TACOS 与样本量；LLM 只解释已计算事实。
- 图：检测异常 → 查询库存/价格/自然销售 → 生成三条假设 → 证据评分 → 人工建议卡片。
- 禁止自动调 budget/bid；建议包含观察窗口和回滚条件。

**验收：** 分母 0、低曝光、归因延迟不会产生武断结论；每条建议引用日期和 campaign；飞书卡片能追到原始报表 ID。

**面试 Point：** 先确定指标变化是否统计上/业务上有效，再让模型解释；LLM 不负责算财务指标。

---

## 里程碑 D：企业化交付（第 10–12 周）

### 第 10 周：MCP 与低代码平台的正确边界

**业务痛点：** MCP、Dify、Coze、n8n 容易变成简历名词堆砌，或让低代码节点绕过服务权限。

**整合章节：** 09 MCP、10 Dify、11 Coze、12 n8n、13 飞书。

**编码任务：**

- MCP Server 只暴露 `get_sales_metrics`、`get_inventory_risk`、`search_policy`、`draft_listing` 四个窄工具。
- 工具输入输出均为 Pydantic；seller/marketplace 从认证上下文注入，不允许模型自由指定他人账号。
- Dify/Coze 只做演示 UI/客服编排，核心规则仍调用本项目 API。
- n8n 只做 schedule、webhook、错误分支和人工升级；工作流 JSON 版本化并提供导入说明。

**验收：** Prompt injection 不能调用写工具；无权限 scope 返回明确拒绝；MCP 工具每次调用有 trace；删除低代码平台后核心 API 仍可运行。

**面试 Point：** 协议层不是安全边界；最小工具面、认证上下文和审计才是企业 MCP 的关键。

### 第 11 周：Docker、CI/CD、安全与可观测

**业务痛点：** 本机脚本无法让面试官复现，真实 token、PII 或模型日志泄漏会直接否定工程能力。

**整合章节：** 14 部署、02 FastAPI、15 Observability/Safety，复用 C++ 高并发经验理解背压与资源上限。

**编码任务：**

- Docker 非 root、healthcheck、graceful shutdown；Compose 启动 gateway/PostgreSQL/Redis/worker。
- GitHub Actions 执行 lint、unit、integration、secret scan、依赖漏洞扫描、镜像构建。
- OpenTelemetry/Prometheus：请求量、P95、429、fallback、token/cost、Agent node latency、人工拒绝率。
- 敏感字段 allowlist、日志 hash、secret manager；SP-API PII 操作单独 RDT 与权限域。

**验收：** 新机器 10 分钟内跑通离线 demo；Key 不存在于 git history；SIGTERM 不丢正在处理的 job；故障能由 trace 定位到节点和 Provider。

**面试 Point：** 把 C++ Reactor 中的背压、资源隔离思维迁移到 Python async/LLM 高延迟服务，展示技术连续性。

### 第 12 周：Portfolio Release 与系统设计答辩

**业务痛点：** 功能多但没有证据、演示路径和可量化结果，面试官无法判断哪些是真实完成。

**整合章节：** 15 企业 Agent、00 总览、全部项目复盘。

**编码任务：**

- 完成三条 golden path 的端到端测试和失败演示：429、Provider 503、飞书权限不足。
- 录 2–3 分钟视频：架构 → 离线 demo → 测试 → fallback → 飞书人工审核。
- 写 3 份 ADR、威胁模型、容量估算和成本表；给出单 seller 与 100 sellers 两档架构。
- 用真实但聚合/脱敏的数据做 before/after：报表耗时、告警去重、Listing 审核时间；不可编造 GMV 因果。

**验收：** CI 全绿；全新 clone 可运行；README 每个“已实现”都有代码/测试；Release tag；准备 10 分钟系统设计讲解和 20 个追问答案。

**面试 Point：** 最有力量的表述是“这是边界、这是失败路径、这是验证证据”，不是组件数量。

---

## 15 阶段覆盖矩阵

| `aiyy` 阶段 | 在本计划中的落点 | 最终证据 |
|---|---|---|
| 01 AI 原理 | 周 1、4、5 | 模型边界、Provider 差异、评测集 |
| 02 Python 开发 | 周 1–4、11 | async、Pydantic、FastAPI、测试 |
| 03 SP-API | 周 1–3、9 | Client、Reports、Ads、幂等入库 |
| 04 Prompt 工程 | 周 5、7 | Prompt 版本与回归评测 |
| 05 LLM 网关 | 周 4 | 标准接口、fallback、熔断 |
| 06 LangChain | 周 6–7 | 文档/检索与模型适配抽象 |
| 07 LangGraph | 周 7、9 | Listing 与广告决策图 |
| 08 RAG | 周 6 | 版本、权限、引用、拒答评测 |
| 09 MCP | 周 10 | 四个最小只读/草稿工具 |
| 10 Dify | 周 10 | 可替换的客服/演示 UI |
| 11 Coze | 周 10 | 受控 Plugin 接口 |
| 12 n8n | 周 3、8–10 | 调度、错误升级、版本化 workflow |
| 13 飞书 | 周 8 | 卡片、Bitable、指令、人工接管 |
| 14 部署 | 周 3、11 | Docker、CI/CD、观测 |
| 15 企业 Agent | 周 3、7–12 | 权限、checkpoint、HITL、成本与 trace |

---

## SP-API / 飞书 / LLM 工程避坑

| 现象 | 根因判断 | 工程处理 |
|---|---|---|
| SP-API 401 | LWA token 无效/过期、header 格式 | token 提前 60 秒刷新；并发双检锁；不记录 token |
| SP-API 403 | 缺角色、seller 未授权、RDT/旧签名问题 | 先看 `x-amzn-RequestId` 与 role mapping；Sales & Traffic 需 Brand Analytics；PII 用 RDT；不要盲重试 |
| SP-API 429 | operation usage plan、重复报表请求 | 独立 token bucket；读取 rate header；Retry-After/全抖动；缓存相同窗口；事件优先于轮询 |
| Report 一直 IN_PROGRESS | 窗口大、峰值、处理异常 | 7–30 天窗口；有 timeout；生产优先 SQS `REPORT_PROCESSING_FINISHED` |
| Report CANCELLED/FATAL | 无数据、参数/权限或 Amazon 处理失败 | 记录 report ID/request ID；有限次数重新创建；升级人工，不无限轮询 |
| Bitable 重复行 | 直接 create，没有幂等查询 | `AmazonOrderId` / `source_key` search + update/create；数据库也设唯一键 |
| 飞书 99991663/权限类错误 | scope、应用版本或机器人未入群 | 错误码结构化；启动时做权限 smoke test；测试群先行 |
| LLM 返回“合法 JSON”但字段错 | 只做 JSON parse | 注册 schema + Provider schema + Pydantic 二次验证；失败切换模型 |
| 模型雪崩 | 无并发上限、超时或熔断 | semaphore、per-provider timeout、circuit breaker、队列背压 |
| Agent 无限循环 | 自修复没有次数和人工出口 | 明确最大尝试、checkpoint、block 后人工审核 |
| RAG 引用过期规则 | metadata 无版本/生效日期 | ingestion 时版本化；检索过滤 effective window；答案携带 citation |
| 指标建议错误 | ACOS/CVR 分母、归因窗口不清 | 代码计算、时间范围随输出、低样本拒绝建议 |

## 简历表述升级门槛

只有完成对应验收后才使用以下动词：

- **“实现 AsyncSPAPIClient”**：周 2 测试全过并完成一次 sandbox/真实最小调用。
- **“构建 Multi-LLM Gateway”**：周 4 能现场演示 503 与非法 JSON 两种 fallback。
- **“开发 LangGraph Listing Agent”**：周 7 有三版五点、来源、规则报告、人工审核记录。
- **“搭建 RAG 知识库”**：周 6 有评测集和 Recall@5，不是只成功入库。
- **“MCP/飞书/CI/CD”**：对应周验收与可复现配置存在。

月 GMV 3 万美元是运营经历；平台带来的效率或质量提升要单独 A/B 或前后对比，不能把既有 GMV 直接归因给尚未上线的平台。
