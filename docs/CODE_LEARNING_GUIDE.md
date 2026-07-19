# Amazon AI Platform 逐代码学习手册

> 这是一份“打开源码、运行测试、做一个小改动、解释结果”的学习手册。<br>
> 它不重复 [README.md](../README.md) 的项目展示，也不重复 [LEARNING_PLAN.md](LEARNING_PLAN.md) 的 12 周交付计划。

## 1. 这份手册怎么用

README 回答“这个项目能做什么”，LEARNING_PLAN 回答“每周交付什么”，本手册只回答以下问题：

- 第一遍应该按什么顺序读代码；
- 每个类和函数为什么存在；
- 数据从入口到输出经过了哪些对象；
- 哪一个测试能证明某条工程约束；
- 修改一处代码后，怎样观察成功和失败路径；
- 学到什么程度才算真正理解，而不是只把示例运行成功。

建议每次只完成一个学习单元。一个单元通常需要 45–90 分钟，不必按照“周”推进。每个单元使用同一个循环：

1. **先预测**：在运行前写下你认为输入、输出和异常是什么。
2. **再读代码**：只读本单元列出的文件和符号，不一次性浏览整个仓库。
3. **运行单测**：先运行一个测试，再运行该模块的全部测试。
4. **做小实验**：只改变一个输入或一条规则，观察测试为什么失败。
5. **恢复并复盘**：保留有价值的测试，确保全量验收重新通过。

所有实验都应使用 synthetic 数据。不要把真实订单、Buyer PII、Amazon/飞书 Token 或模型 Key 写进源码、测试、终端截图和学习笔记。

## 2. 学习地图

| 单元 | 主题 | 首要源码 | 能回答的问题 |
|---:|---|---|---|
| 0 | 环境与测试方法 | `requirements*.txt`、`pytest.ini` | 怎样证明代码是离线、确定、可重复的？ |
| 1 | Pydantic 数据契约 | `models.py` | 为什么 Raw、Standard、Metric 不能混为一层？ |
| 2 | 数据质量与幂等 | `data_quality.py` | 如何阻止错误报表进入 Agent？ |
| 3 | Async SP-API | `spapi.py` | Token、限流、重试和异步报表如何组合？ |
| 4 | 事务数据管道 | `pipeline.py`、`sql/init.sql` | 为什么第 50 行失败后不能留下前 49 行？ |
| 5 | Multi-LLM Gateway | `llm_gateway.py` | Provider 差异、Schema 和 fallback 在哪里隔离？ |
| 6 | Prompt 回归评测 | `prompts.py` | Prompt 改版如何像代码一样做回归？ |
| 7 | RAG 知识库 | `rag.py` | 版本、有效期、权限、引用和拒答如何落到代码？ |
| 8 | LangGraph Listing Agent | `listing_agent.py` | 为什么图必须停在人工审核，而不是自动发布？ |
| 9 | 飞书控制面 | `feishu.py`、`business_api.py` | ACK、幂等写、验签和去重通知如何协作？ |
| 10 | 广告解释 | `ads.py` | 为什么指标由代码计算，LLM 只解释证据？ |
| 11 | MCP 安全边界 | `mcp_server.py` | 为什么认证上下文不能来自模型参数？ |
| 12 | Worker、观测与 Docker | `worker.py`、Compose | 如何验证非 root、健康检查和优雅退出？ |
| 13 | 三条 Golden Path | `test_golden_paths.py` | 怎样把独立模块串成可讲解的业务闭环？ |

推荐严格按 0 → 13 学习。单元 3、5、8 是三个难点，不理解前置单元时不要急着跳到 Agent。

## 3. 单元 0：建立可重复的学习环境

### 3.1 本单元目标

完成后，你应该能区分生产依赖、开发依赖、离线测试和真实账号联调，并能只运行一个指定测试。

### 3.2 创建环境

```bash
cd /Users/cpt/project/aiyy/ecommerce-agent-learning-plan
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

确认解释器和工具来自虚拟环境：

```bash
which python
python --version
python -m pytest --version
ruff --version
```

项目支持 Python 3.11+，CI 与容器使用 Python 3.12。本地 Python 小版本不同可能产生第三方库 warning，但不能产生测试失败。

### 3.3 先学会运行最小范围

```bash
# 一个测试文件
pytest tests/test_data_quality.py -q

# 一个测试函数
pytest tests/test_data_quality.py::test_advertising_denominator_zero_is_none -q

# 显示 print/log 输出和更完整的失败上下文
pytest tests/test_data_quality.py -q -s

# 静态检查
ruff check amazon_ai_platform tests examples
```

测试命名是行为描述。例如 `test_same_file_twice_is_idempotent_and_reconciles` 比 `test_store` 更明确，因为它告诉你要证明的是“重复导入不会增加行数”。

### 3.4 怎样读一个测试

按 Arrange、Act、Assert 三段理解：

```text
Arrange：构造 synthetic 输入和 Mock 外部边界
Act：调用真实业务逻辑
Assert：检查可观察结果、异常或副作用
```

本项目只 mock Amazon、飞书、LLM、Redis 等协议边界，不 mock 正在验证的重试、计算、幂等和权限逻辑。

### 3.5 完成标准

- 能只运行一个测试函数；
- 能指出 `requirements.txt` 与 `requirements-dev.txt` 的区别；
- 能解释为什么 CI 不应访问真实 Amazon、飞书或 LLM；
- `pytest tests/test_data_quality.py -q` 和 Ruff 均通过。

## 4. 单元 1：从数据契约理解整个项目

### 4.1 阅读顺序

打开 `amazon_ai_platform/models.py`，按以下符号顺序阅读：

1. `safe_ratio`
2. `RawSalesTrafficRow`
3. `StandardSalesTrafficRow`
4. `AdvertisingMetrics`
5. `DailyBusinessMetrics`
6. `ListingVariant` 与 `ListingDraft`
7. `PolicyDocument`、`Citation` 与 `GroundedAnswer`

不要从第一行机械地读到最后一行。先理解三个数据层：

```text
外部字符串/JSON
      │
      ▼
Raw contract：尽量保留原值，便于审计
      │ 质量检查 + 标准化
      ▼
Standard contract：日期、Decimal、范围和业务关系已验证
      │ 确定性计算
      ▼
Metric contract：CVR/ACOS/CTR 等可用于决策的指标
```

### 4.2 为什么分母为 0 返回 `None`

核心函数是：

```python
def safe_ratio(numerator, denominator):
    if denominator == 0:
        return None
    return float(numerator / denominator)
```

`0` 表示“比率确实为零”，`None` 表示“当前没有定义或证据不足”。例如没有点击时，CVR 不是 0%，而是无法由 `purchases / clicks` 定义。这个区别会直接影响广告建议是否武断。

运行：

```bash
pytest tests/test_data_quality.py::test_advertising_denominator_zero_is_none -q
```

### 4.3 Pydantic 在这里做什么

`StandardAdvertisingRow.counts_are_consistent` 不只检查字段类型，还检查业务关系：

```text
purchases <= clicks <= impressions
```

`ListingVariant` 同时约束：

- title 长度；
- bullets 必须恰好 5 条；
- 5 条 bullets 不能只是大小写或首尾空格不同；
- rationale 必须有最小信息量。

这类约束是跨模块合同。SP-API、Gateway、Agent 和飞书都不应各自重新定义同一份 JSON 形状。

### 4.4 小实验

在 Python REPL 中构造错误广告数据：

```bash
python - <<'PY'
from amazon_ai_platform.models import StandardAdvertisingRow

StandardAdvertisingRow(
    metric_date="2026-07-01",
    campaign_id="synthetic-campaign",
    sku="SYNTHETIC-SKU",
    currency="EUR",
    impressions=10,
    clicks=11,
    purchases=1,
    spend="1.00",
    attributed_sales="2.00",
)
PY
```

预期得到 Pydantic validation error。错误发生在对象进入业务逻辑之前，这就是 Data Contract 的价值。

### 4.5 复盘题

1. 为什么金额使用 `Decimal`，而最终比例可以是 `float`？

   **参考答案：** 金额需要十进制精确性。例如二进制浮点数不能精确表示 `0.1`，连续求和可能产生肉眼难以理解的尾差；`Decimal` 能按财务口径保存和计算金额。比例通常用于监控、排序或展示，允许极小的浮点误差，而且许多指标接口最终就是 `float`。关键原则是：先用 `Decimal` 完成金额计算，再在明确的边界转换比例，不要把 `float` 计算结果重新当作账务金额。

2. 为什么 `OrderSnapshot.raw_payload` 设置 `exclude=True`？

   **参考答案：** 原始 Amazon 响应用于追查解析问题，但可能包含当前业务输出不需要的字段，甚至包含 Buyer PII。`exclude=True` 让 `model_dump()`、API 响应、日志和模型输入默认不携带它，减少误泄漏和上下文污染；需要审计原始证据时，应走受权限保护的专用存储，而不是普通序列化路径。对应契约在 `models.py::OrderSnapshot`。

3. 为什么 `ListingDraft.requires_human_review` 默认是 `True`？

   **参考答案：** Listing 更新会影响合规、搜索流量和真实销售，属于高风险动作。默认 `True` 使用“安全失败”原则：调用方即使忘记设置，也只能得到待审草稿。`ListingOptimizationAgent` 始终生成待审结果，MCP 层还会拒绝后端返回的非待审草稿；人工 `approve` 只记录决定，不授予自动发布权限。2026 新规下的 75 字符 Title 和 125 字符 Item Highlight 也必须一起人工核对。

4. 如果增加“退货率”，分母为 0 时应返回什么？

   **参考答案：** 应返回 `None`，表示“没有足够分母，指标无定义”，而不是返回 `0`。零订单时的 `0%` 会错误暗示“存在订单且没有退货”。展示层可以把 `None` 显示为 `N/A`，并保留订单数作为解释证据。可复用 `models.py::safe_ratio` 的语义。

完成标准：能从任意一个输出模型向前追溯它依赖的 Standard/Raw 数据，并能解释至少三条 Pydantic 业务约束。

## 5. 单元 2：数据质量、标准化、幂等与对账

### 5.1 阅读顺序

打开 `amazon_ai_platform/data_quality.py`：

1. `QUALITY_RULES`
2. `parse_sales_csv`
3. `audit_sales_rows`
4. `normalize_sales_rows`
5. `IdempotentMetricStore`
6. `reconcile_revenue`

再对照 `tests/test_data_quality.py`。

### 5.2 一条报表的处理顺序

```text
CSV text
  → DictReader
  → RawSalesTrafficRow
  → 20 条质量规则一次性收集问题
  → StandardSalesTrafficRow
  → 以 (metric_date, sku) upsert
  → 与 Seller Central 汇总做 reconciliation
```

质量审计不在第一个错误处停止，因为运营人员需要一次看到整份文件的问题，而不是修一个字段、重跑、再发现下一个字段。

### 5.3 幂等键不是随机 UUID

`StandardSalesTrafficRow.idempotency_key` 使用：

```text
(metric_date, sku)
```

它来自稳定的业务事实。相同日期和 SKU 重跑时覆盖同一记录，不创建新记录。随机 UUID 每次都不同，不能用于导入去重。

运行：

```bash
pytest tests/test_data_quality.py::test_same_file_twice_is_idempotent_and_reconciles -q
```

观察两个断言：第二次导入后行数稳定；标准化金额与来源汇总的差异在 0.5% 容差内。

### 5.4 小实验

在 `tests/test_data_quality.py` 的 synthetic CSV 中依次尝试：

- 把 `EUR` 改成 `eur`；
- 让 units 为负数；
- 让 parent ASIN 与 child ASIN 相同；
- 复制同一天同 SKU 的一行。

每次只改一项，运行：

```bash
pytest tests/test_data_quality.py::test_quality_gate_reports_multiple_bad_fields -q
```

记录命中的 `DQxx` 编号。实验完成后恢复测试夹具。

### 5.5 复盘题

1. “CSV 能被 pandas 读取”为什么不等于数据可信？

   **参考答案：** 可读取只证明语法大致成立，不证明业务语义正确。日期可能超出导入窗口，SKU 可能未知，币种可能不符，units 可能为负数，同一天同 SKU 可能重复，parent/child ASIN 也可能相同。`audit_sales_rows` 的 20 条规则验证的是这些业务事实；通过后还要标准化、幂等写入并与 Seller Central 总额对账。

2. DQ19 为什么是 warning，而负收入是 error？

   **参考答案：** “销量大于 0 但收入为 0”可能来自赠品、促销、替换件或报表时间差，值得人工调查但不一定是假数据，所以 DQ19 是 warning。当前 Sales & Traffic 标准层把 revenue 定义为非负销售收入，负值违反该数据集的合同，可能意味着列映射错误或把退款报表混入，因此 DQ15 是 error。若未来接入退款数据，应建立独立合同，而不是放宽现有字段含义。

3. 如果 Seller Central 总额本身为 0，reconciliation 应怎样解释？

   **参考答案：** 不能计算相对差异率，所以 `difference_ratio` 应为 `None`。如果标准化总额也为 0，则绝对差额为 0，可以判定对账通过；如果标准化总额非 0，则对账失败，并报告绝对差额，不能用除零后的伪比例。当前 `reconcile_revenue` 正是这样处理。

4. 幂等键应该在内存、数据库还是两处都存在？

   **参考答案：** 业务键定义应在领域模型中清晰可见，数据库唯一约束/`ON CONFLICT` 才是生产环境的最终保证。内存字典只适合离线测试和单进程演示，无法阻止多进程或多机器并发重复写。项目用 `(metric_date, sku)` 同时驱动内存测试替身和 PostgreSQL upsert，使测试语义与生产约束一致。

完成标准：能解释 20 条规则中至少 10 条的业务原因，并能设计一个新的稳定业务键。

## 6. 单元 3：生产级 Async SP-API 客户端

### 6.1 先画出四条独立机制

打开 `amazon_ai_platform/spapi.py`。不要把所有 async 代码看成一个大流程，先拆成四条机制：

```text
认证：access_token → 双检锁 → LWA 刷新
限流：operation → 独立 AsyncTokenBucket → 动态 rate 更新
重试：request → 状态码分类 → Retry-After/全抖动
报表：create → poll → document → download → gzip/json → Pydantic
```

### 6.2 双检锁解决什么问题

20 个协程同时发现 token 过期时：

1. 锁外第一次检查让有效 token 无需加锁；
2. 只有一个协程获得 `_token_lock` 并刷新；
3. 其他协程获得锁后再次检查，复用新 token；
4. 最终只发送一次 LWA 刷新请求。

运行并阅读计数断言：

```bash
pytest tests/test_spapi.py::test_concurrent_callers_refresh_lwa_token_once -q
```

### 6.3 为什么限流按 operation 隔离

`AsyncSPAPIClient` 为不同 operation 保存不同 `AsyncTokenBucket`。Reports 和 Orders 的 usage plan 不同；共用一个全局桶会让慢端点阻塞无关请求。响应头 `x-amzn-RateLimit-Limit` 可用于更新当前 operation 的 rate。

`AsyncTokenBucket.acquire` 的学习重点不是公式，而是三个状态：

- 上次补充 token 的时间；
- 当前可用 token 数；
- 还缺多少 token，需要异步等待多久。

### 6.4 重试不是“所有错误再试一次”

可恢复：

- HTTP 429；
- 临时 5xx；
- `httpx.TransportError`。

快速失败：

- 400 参数错误；
- 403 权限错误；
- 达到最大尝试次数。

异常只携带 status、operation、request ID 等安全上下文，不携带 token 和响应中的潜在 PII。

运行：

```bash
pytest tests/test_spapi.py::test_first_two_429_then_success -q
pytest tests/test_spapi.py::test_429_uses_retry_after_and_preserves_request_id -q
```

### 6.5 异步报表状态机

`get_sales_and_traffic_report` 不是一次 HTTP 请求：

```text
计算稳定窗口缓存键
  ├─ 命中：直接返回已验证的 SalesAndTrafficReport
  └─ 未命中：
      create_sales_and_traffic_report
      → wait_for_report
          ├─ DONE：取得 reportDocumentId
          ├─ CANCELLED/FATAL：明确异常
          └─ 超时：TimeoutError
      → download_report
      → gzip 解压（如需要）
      → JSON 解析
      → Pydantic 校验
      → 写缓存
```

运行：

```bash
pytest tests/test_spapi.py::test_sales_and_traffic_report_full_async_flow -q
pytest tests/test_spapi.py::test_report_fatal_and_timeout_are_explicit -q
pytest tests/test_spapi.py::test_report_window_cache_avoids_duplicate_creation -q
python -m examples.01_spapi_client
```

### 6.6 小实验

在 `tests/test_spapi.py` 的 MockTransport handler 中把第三次响应也改成 429，确认最终抛出 `SPAPIError`，并检查异常文本不包含测试 secret。不要修改生产重试次数来强行让测试通过。

### 6.7 复盘题

1. 为什么 async 函数中不能使用 `time.sleep`？

   **参考答案：** `time.sleep` 会阻塞整个事件循环线程，睡眠期间其他请求、token 刷新和报表轮询都不能运行，异步并发会退化成串行。`await asyncio.sleep()` 会把控制权交回事件循环，让其他协程继续执行。网络等待也应使用异步客户端并设置明确 timeout。

2. 为什么网络错误可重试，而 403 默认不重试？

   **参考答案：** timeout、连接重置、429 和部分 5xx 往往是瞬时故障，经过有上限的抖动退避可能恢复。403 通常表示角色、scope、应用授权或 RDT 不满足，等待不会改变权限；盲目重试只会放大流量并掩盖配置错误。因此应携带 operation/request context 升级人工处理，同时避免在异常中泄漏 token。

3. report window cache key 为什么要包含 seller、marketplace、type、日期和 options？

   **参考答案：** 这些字段共同决定“这是哪一份报表”。少 seller 会造成跨租户串数据，少 marketplace 会混站点，少 report type 会混口径，少日期会复用错误时间窗，少 options 会忽略聚合粒度等请求差异。完整稳定键既防止重复创建报表，也防止更危险的错误缓存命中。

4. 如果两个 worker 同时创建相同报表，仅内存缓存够不够？生产环境应放在哪里？

   **参考答案：** 不够。两个 worker 有独立内存，都可能先看到 cache miss，然后各自创建报表。生产环境应把稳定报表键放入共享存储，例如 PostgreSQL 唯一约束的 report-jobs 表，或带原子 `SET NX`/租约的 Redis；创建状态、report ID、过期时间和失败状态也应持久化。数据库唯一约束仍应作为最后一道并发保护。

完成标准：能白板画出 token 刷新、429 重试和报表状态机，并能解释每一个停止重试的条件。

## 7. 单元 4：事务、回滚、Upsert 和可追溯管道

### 7.1 阅读顺序

1. `amazon_ai_platform/pipeline.py` 的 `PipelineTransaction`；
2. `DataPipeline.ingest_sales_metrics`；
3. `InMemoryPipelineRepository.transaction`；
4. `AsyncPGPipelineRepository` 与 `AsyncPGPipelineTransaction`；
5. `sql/init.sql`；
6. `tests/test_pipeline.py`。

### 7.2 Protocol 是业务逻辑与数据库的接缝

`DataPipeline` 只依赖三种操作：

```text
store_raw
upsert_metric
update_cursor
```

测试注入内存事务，生产可注入 asyncpg 事务。业务编排不需要知道连接池、SQL 驱动或 Mock 的细节。这是“依赖协议”，不是为了抽象而抽象。

### 7.3 一次提交的原子边界

```text
BEGIN
  保存 raw payload + hash + trace
  对每一行执行 metric upsert
  更新同步 cursor
COMMIT
```

任一步失败都应 ROLLBACK。否则 cursor 可能显示任务完成，但事实表只写入前一部分。

运行：

```bash
pytest tests/test_pipeline.py::test_row_50_failure_rolls_back_whole_batch -q
pytest tests/test_pipeline.py::test_replay_is_idempotent_and_trace_reaches_raw_request -q
```

内存仓库通过事务开始前的深拷贝模拟回滚；PostgreSQL 版本依靠数据库事务。两者验证的是同一个可观察行为。

### 7.4 从 trace 追到原始证据

`PipelineRun` 保留：

- `trace_id`；
- hash 后的 seller ID；
- operation 与 Amazon request ID；
- date window 与 row count；
- raw payload SHA-256；
- latency。

日志只应输出 allowlist 字段；原始 payload 存储在受控数据层，不直接打进日志。

### 7.5 SQL 学习点

在 `sql/init.sql` 中重点找：

- `PRIMARY KEY (metric_date, sku)`；
- `UNIQUE` 业务键；
- `JSONB` raw/trace 字段；
- cursor 表；
- human review 与 audit 表。

再看 `alembic/versions/0001_transactional_pipeline.py`，理解“新环境初始化 SQL”和“已有环境迁移”是两个入口。

### 7.6 小实验

把 `fail_at_row` 分别设为 1、50、最后一行，确认三种情况下仓库都不留下半批数据。然后去掉故障，使用相同输入重跑两次，确认事实表行数不增加。

完成标准：能解释“至少一次投递 + 幂等键 + 事务”为何比口头承诺 exactly-once 更可靠。

## 8. 单元 5：Multi-LLM Gateway

### 8.1 先分清四层

打开 `amazon_ai_platform/llm_gateway.py`：

```text
HTTP contract：ChatCompletionRequest / ChatCompletionResponse
Provider adapter：AnthropicProvider / DeepSeekChatProvider / OpenAIResponsesProvider
Routing policy：ModelRouter / RouteTarget / CircuitState
Web application：create_app / app_from_environment
```

Provider 特有字段只应出现在 adapter。业务方只使用 OpenAI 风格消息、服务端注册 Schema 和统一响应。

当前三种 provider 协议并不相同：OpenAI 使用 Responses API 的 `input`、`text.format` 和 typed `output`；Anthropic 使用 Messages API 的 `output_config.format`；DeepSeek 使用 Chat Completions 的 `json_object` 模式。网关对外仍保留 `/v1/chat/completions` 兼容契约，adapter 负责协议翻译，Pydantic 负责第二次本地校验。

### 8.2 Structured Output 的三层保证

1. 请求只能选择服务端 `SCHEMA_REGISTRY` 已注册的 schema 名；
2. adapter 把 schema 转换为相应 Provider 的请求格式；
3. 返回后 `_validate` 再执行 JSON parse 与 Pydantic 校验。

仅在 Prompt 中写“请返回 JSON”不等于结构化输出。

运行：

```bash
pytest tests/test_gateway.py::test_router_falls_back_and_validates_pydantic_schema -q
pytest tests/test_gateway.py::test_invalid_structured_output_also_triggers_fallback -q
```

### 8.3 fallback、熔断与并发闸门

`ModelRouter.complete` 的控制顺序：

```text
解析 alias
→ 取得 RouteTarget 列表
→ 跳过打开中的 circuit
→ semaphore 限制并发
→ provider timeout
→ 本地 schema validation
→ 成功则清零失败状态并返回
→ 可恢复错误则记录失败并尝试下一个 provider
→ 认证/配额类错误则 ProviderEscalation，停止自动 fallback 并升级人工
```

注意 `None` 与空列表的区别：

- `routes.get(alias) is None`：alias 未注册，属于请求错误；
- `routes[alias] == []`：alias 已注册，但环境没有配置 Provider，属于服务暂不可用。

后者必须安全返回 503，而不是误报 unknown model。

运行：

```bash
pytest tests/test_gateway.py::test_registered_alias_without_provider_returns_safe_503 -q
pytest tests/test_gateway.py::test_authentication_error_does_not_fall_back -q
pytest tests/test_gateway.py::test_provider_timeout_falls_back_and_metrics_are_exported -q
pytest tests/test_gateway.py::test_all_providers_fail_with_safe_503_without_secret_or_stack -q
```

### 8.4 本地启动与安全失败

Key 留空时也能启动健康检查：

```bash
uvicorn amazon_ai_platform.llm_gateway:app --host 127.0.0.1 --port 8000
```

另一个终端：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/metrics
```

此时调用 `listing-quality` 应返回不含 Key、堆栈和 Provider 原始响应的安全 503。只有需要真实 Provider 联调时才在未提交的 `.env` 中配置 Key。

### 8.5 小实验

在 `tests/test_gateway.py` 中把 FakeProvider 的主模型依次设置为：503、timeout、非法 JSON、缺少一条 bullet。观察哪些情况会 fallback，哪种认证错误会停止 fallback。

完成标准：能指出任何一个 Provider 特有字段应放在哪一层，并能解释“非法 JSON”和“网络超时”为什么都可能触发降级。

## 9. 单元 6：把 Prompt 当作版本化资产

### 9.1 阅读顺序

1. `PromptAsset`；
2. `PromptRegistry`；
3. `listing_prompt`；
4. `GoldenCase` 与 `CaseOutput`；
5. `evaluate_prompt`；
6. `compare_evaluations`；
7. `tests/fixtures/golden_listing_cases.json`。

Prompt 资产由 `prompt_id + version + category` 定位。输入和输出 schema 也是资产的一部分，不能把 Prompt 字符串散落在 Agent 节点中。

### 9.2 为什么需要多指标

`EvaluationResult` 分开记录：

- schema pass rate；
- 硬规则通过率；
- block 漏检数；
- 关键词覆盖率；
- 引用准确率；
- 人工偏好率。

前两项可作为 CI 硬门槛，人工偏好只能报告趋势。一个总分会隐藏“文字更顺但违规词漏检”的严重回归。

运行：

```bash
pytest tests/test_prompts.py::test_forty_case_prompt_gates_are_reproducible -q
pytest tests/test_prompts.py::test_prompt_version_diff_identifies_regression -q
```

### 9.3 小实验

复制一个 synthetic golden case，给它增加必需关键词但不修改对应输出。重新运行测试，确认失败样例 ID 能定位到具体 case。随后补齐输出或删除实验数据。

### 9.4 复盘题

1. 为什么西服和宠物类目要分别评测？

   **参考答案：** 两个类目的词汇、材料、使用场景和合规风险不同。只测宠物类可能让 Prompt 在西服尺码、版型和场景表达上退化，反之亦然。分层统计还能发现“总通过率没变，但某一类目明显变差”的平均数掩盖问题。项目用 20 条西服和 20 条宠物 synthetic case 做最低回归集。

2. 什么指标适合阻断 CI，什么指标只适合观察？

   **参考答案：** 可确定、可重复且错误代价高的指标适合阻断 CI，例如 schema pass rate、硬规则通过率、block 漏检数和必需引用准确率。措辞自然度、人工偏好率等主观指标受评审者和样本变化影响，更适合观察趋势或人工发布门槛。关键词覆盖率可按业务风险设置硬门槛，但不能为了覆盖而鼓励堆词。

3. Prompt 版本变了但 schema 不变，为什么仍需要回归？

   **参考答案：** Schema 只约束输出形状，不保证事实正确、关键词覆盖、引用准确或不出现违规宣传。Prompt 的一个词就可能改变模型行为，即使 JSON 字段完全相同。每次版本变化都应在相同 golden cases 上比较 baseline 与 candidate，并保留版本号和失败 case ID，才能定位行为回归。

完成标准：能新增一条 golden case，并能用差异报告说明 candidate 相对 baseline 改善或退化在哪里。

## 10. 单元 7：有版本、权限、引用和拒答的 RAG

### 10.1 阅读顺序

1. `models.py` 中的 `PolicyDocument`；
2. `rag.py` 的 `chunk_document`；
3. `HashEmbedder`；
4. `PolicyKnowledgeBase.add_documents`；
5. `search`；
6. `answer`；
7. `evaluate_retrieval`。

`HashEmbedder` 是离线确定性实现，用于学习检索机械过程和回归测试，不代表生产 embedding 质量。生产可替换 Embedder 或向量存储，但版本、权限和拒答规则不能丢。

### 10.2 检索过滤早于相似度排序

一个 chunk 必须同时满足：

```text
effective_from <= as_of <= effective_to（如果有）
access_scope 在调用者 scopes 中，或文档是 public
marketplace 匹配
category 匹配
language 匹配
similarity >= min_score
```

过期或越权文档不应先召回再让 LLM“自觉忽略”，而应在检索层排除。

运行：

```bash
pytest tests/test_rag.py::test_expired_and_unauthorized_documents_are_filtered -q
pytest tests/test_rag.py::test_grounded_answer_contains_citations_or_refuses -q
```

### 10.3 回答与拒答是同等重要的输出

有证据时返回 `answered + citations`；无证据时返回：

```text
status = insufficient_evidence
requires_human_review = True
```

不要为了“回答率”让模型根据常识补全 Amazon 规则。

### 10.4 评测指标

- Recall@5：可回答问题的相关文档是否出现在前 5；
- MRR：第一个相关结果出现得多靠前；
- citation accuracy：返回的引用有多少确实相关；
- refusal accuracy：应拒答和应回答是否判断正确；
- expired leakage rate：过期规则是否泄漏。

运行完整 50 题评测：

```bash
pytest tests/test_rag.py::test_fifty_question_retrieval_acceptance_set -q
python -m examples.06_rag_knowledge_base --demo
```

### 10.5 小实验

把一个文档的 `effective_to` 改到查询日期之前，确认它消失；再把其 scope 改为调用者没有的私有 scope，确认仍无法召回。最后恢复 fixture。

完成标准：能解释一次错误答案究竟是 ingestion、过滤、retrieval、citation 还是 generation 问题，而不是笼统归因于“模型不好”。

## 11. 单元 8：LangGraph Listing Optimization Agent

### 11.1 先读边界，再读图

文件开头已经声明：Agent 只生成待审核草稿，不发布 Listing、不改价、不改广告。然后依次阅读：

1. `ProductBrief` 与 `CompetitorEvidence`；
2. 三个 Protocol：source、generator、checkpoint；
3. `ListingState`；
4. 三个节点；
5. `_compile`；
6. `run` 与 `review`。

### 11.2 图中数据怎样变化

```text
START
  → read_competitor_data
      输入 brief
      输出带 source_id/observed_at 的 evidence
  → generate_three_versions
      并发生成 3 个 ListingVariant
      每个由 Pydantic 保证恰好 5 条 bullet
  → compliance_check
      确定性规则扫描 + fact_sources
      输出 requires_human_review=True 的 ListingDraft
  → END
```

`ListingState` 是节点共享状态；每个节点返回自己新增或更新的字段。`audit_log` 记录节点、摘要和时间，但不记录完整 Prompt 或 Buyer PII。

### 11.3 为什么生成三个版本用 `asyncio.gather`

三个版本彼此独立，真实 LLM 调用主要等待网络，因此可并发。`_generate_with_retry` 对每个版本单独限制尝试次数，避免整个 Agent 无限自修复。

运行：

```bash
pytest tests/test_listing_agent.py::test_graph_generates_three_five_bullet_variants_with_sources -q
```

### 11.4 合规为何不用 LLM 自评

`GermanMarketplaceCompliance` 用正则和明确规则检查：

- 未经证实的最高级；
- 保证/100% 声明；
- 医疗治疗声明；
- 免费/价格型宣传；
- 主关键词和 GPSR 元数据提醒。

确定性规则可复现、可定位、可回归。法律适用性仍需人工，不把规则引擎包装成法律意见。

运行：

```bash
pytest tests/test_listing_agent.py::test_german_compliance_blocks_unsubstantiated_claims -q
```

### 11.5 checkpoint 与人工审核

相同 `request_id` 再次运行时先读取 checkpoint，避免重复生成和重复计费。`review` 只记录 approve/reject/edit：

```text
publishes_listing = False
```

即使人工点了 approve，也只是批准草稿，不代表本模块有 Amazon 发布权限。

运行：

```bash
pytest tests/test_listing_agent.py::test_request_checkpoint_is_idempotent_and_human_review_never_publishes -q
python -m examples.04_listing_agent
```

### 11.6 小实验

写一个测试 generator：第一次抛 `RuntimeError`，第二次返回合法 `ListingVariant`。确认每个 version 最多重试配置次数。再让它始终失败，确认 Agent 明确退出，不进入无限循环。

完成标准：能画出三节点状态变化，并能指出 source、generator、compliance、checkpoint 和 review 各自负责什么、不负责什么。

## 12. 单元 9：飞书是控制面，不是展示皮肤

### 12.1 阅读顺序

打开 `amazon_ai_platform/feishu.py`：

1. `tenant_token` 与 `_call`；
2. `sales_alert_card`；
3. `_search_record` 与 `upsert_record`；
4. `sync_order` 与 `publish_alert`；
5. `parse_command` 与 `handle_event`；
6. `advertising_recommendation_card`；
7. `business_api.create_business_app`。

### 12.2 Token 过期重试

`tenant_token` 使用和 SP-API 相似的双检锁。业务 API 返回飞书 token 失效码时，`_call` 清除缓存并只重试一次。其他权限或业务错误转换为带 operation 和 code 的 `FeishuError`，避免无界重试。

```bash
pytest tests/test_feishu.py::test_expired_tenant_token_refreshes_once -q
```

### 12.3 Bitable upsert

写入流程是：

```text
按稳定 source_key 搜索
  ├─ 已存在：update record
  └─ 不存在：create record
```

订单使用 `AmazonOrderId`。告警使用 `source_key`，且只有状态或严重度变化才再次通知，防止调度重跑造成群消息风暴。

```bash
pytest tests/test_feishu.py::test_order_sync_updates_existing_bitable_record -q
pytest tests/test_feishu.py::test_duplicate_alert_only_updates_record_without_second_notification -q
```

### 12.4 webhook 的四个安全/体验点

1. verification token 不匹配立即拒绝；
2. operator ID 来自事件上下文并传入 analyzer；
3. `/选品` 先发 ACK，再执行可能较慢的分析；
4. 超时返回友好卡片，不让用户一直等待。

```bash
pytest tests/test_business_api.py::test_feishu_webhook_rejects_forged_verification_token -q
pytest tests/test_feishu.py::test_product_command_sends_ack_before_analysis -q
```

### 12.5 卡片中必须出现什么

- 日期窗口和指标口径；
- source/report/trace ID；
- 置信与限制；
- 明确的“人工审批/待审核”；
- 不出现 Buyer 姓名、地址、邮箱、Token。

完成标准：能解释“记录幂等”和“通知去重”不是同一件事，并能指出 webhook 认证失败发生在哪一层。

## 13. 单元 10：广告报表与证据优先解释

### 13.1 阅读顺序

1. `AmazonAdsClient.access_token`；
2. `request`；
3. `create_campaign_report`；
4. `wait_for_report`；
5. `download_report`；
6. `explain_advertising_anomaly`。

Ads profile ID 与 marketplace ID 是不同标识，构造函数主动拒绝把二者错误地设成相同值。

### 13.2 指标由代码计算

`AdvertisingMetrics.calculate` 计算：

```text
ACOS  = spend / attributed_sales
CTR   = clicks / impressions
CVR   = purchases / clicks
CPC   = spend / clicks
TACOS = spend / total_sales
```

LLM 不负责除法、分母零处理或归因窗口判断。它只能解释已经计算并带来源的事实。

### 13.3 三个拒绝武断结论的条件

`explain_advertising_anomaly` 会显式处理：

- impressions < 1000：样本不足；
- 14 天归因窗口未闭合：ACOS 可能高估；
- attributed sales = 0：ACOS 无定义。

无论哪种结果：

```text
requires_human_review = True
executable = False
```

```bash
pytest tests/test_ads.py::test_low_exposure_and_attribution_delay_never_auto_execute -q
```

### 13.4 报表协议测试

```bash
pytest tests/test_ads.py::test_ads_two_429_then_success -q
pytest tests/test_ads.py::test_ads_full_gzip_report_flow -q
pytest tests/test_ads.py::test_ads_fatal_and_timeout_are_explicit -q
python -m examples.05_amazon_ads_client --demo
```

### 13.5 小实验

分别构造高曝光已闭合窗口、低库存、近期改价的数据，比较三个 `EvidenceScore`。确认 suggested action 仍然只是待审批建议，而不是 bid/budget 写操作。

完成标准：能在不看代码的情况下写出五个指标公式，并解释归因窗口为何会让“今天的 ACOS”不稳定。

## 14. 单元 11：MCP 的工具面与认证上下文

### 14.1 先看不存在的能力

`amazon_ai_platform/mcp_server.py` 只暴露四个工具：

- `get_sales_metrics`；
- `get_inventory_risk`；
- `search_policy`；
- `draft_listing`。

没有 publish listing、change price、change bid/budget 或 create purchase order。工具不存在比在 Prompt 中写“请不要调用”更可靠。

### 14.2 为什么 seller 不在工具参数中

`AuthContext` 由可信 transport/auth 层注入：

```text
seller_id + marketplace_id + scopes + trace_id
```

模型只能填写 SKU、日期、问题或 ProductBrief，不能通过参数选择另一个 seller。`MCPToolService` 在调用 backend 前注入认证上下文。

运行：

```bash
pytest tests/test_mcp_server.py::test_tool_arguments_cannot_select_another_seller -q
pytest tests/test_mcp_server.py::test_missing_scope_is_explicitly_denied_and_audited -q
```

### 14.3 草稿工具的双重边界

1. scope 必须包含 `listing:draft`；
2. backend 返回的 `ListingDraft.requires_human_review` 必须为 True。

如果 backend 违反第二条，service 主动报错，不把错误状态暴露给 MCP 调用方。

```bash
pytest tests/test_mcp_server.py::test_listing_tool_can_only_return_human_review_draft -q
pytest tests/test_mcp_server.py::test_policy_tool_refuses_without_evidence -q
```

### 14.4 SDK 与业务逻辑分离

`build_mcp_server` 只负责把已经可测试的 service 包装成官方 FastMCP 工具。业务逻辑测试不需要启动 stdio/SSE transport。`main` 故意要求 composition root 注入真实 backend，不提供默认凭据或越权 fallback。

完成标准：能解释为什么 MCP 是协议层而不是安全边界，并能为一个新只读工具设计 input model、scope 和 audit 记录。

## 15. 单元 12：Worker、观测、Docker 和优雅退出

### 15.1 Worker 的最小职责

`GracefulWorker` 从 Redis 队列读取 JSON，只允许：

- `sync_sales`；
- `refresh_policy_index`。

未知 job kind 明确拒绝。收到 SIGTERM/SIGINT 时设置 stopping event，不再领取新任务，并等待当前任务结束。

```bash
pytest tests/test_worker.py::test_worker_finishes_current_job_before_graceful_exit -q
```

### 15.2 安全日志与 trace

`observability.safe_event` 使用字段 allowlist，而不是尝试维护永远不完整的敏感字段 denylist。prompt、Authorization、buyer email/address 等未在 allowlist 中，因此被丢弃。

```bash
pytest tests/test_observability.py -q
pytest tests/test_telemetry.py -q
```

Gateway 的 `/metrics` 输出请求、失败、fallback、token、估算成本和 latency；Listing Agent 记录节点 latency 和人工拒绝率。指标用于定位系统行为，不能把 prompt 全文当 metric label。

### 15.3 看懂 Compose 依赖

```text
gateway → HTTP 8000
postgres → 事实表与审计表
redis → job queue
worker → Redis 消费者
```

容器内部访问数据库使用 `postgres:5432`，访问 Redis 使用 `redis:6379`。容器里的 localhost 只指向容器自身。

### 15.4 Docker 运行验收

Colima 已启动时：

```bash
colima status
docker info
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/metrics
```

观察：

- gateway/postgres/redis 健康，worker 运行；
- gateway 和 worker 使用 UID/GID 65532，而不是 root；
- 无 Provider Key 时业务请求安全返回 503；
- SIGTERM 后当前 job 完成，进程 exit code 为 0。

验收后安全关闭：

```bash
docker compose down
```

普通 `down` 保留命名卷。不要在学习验收中使用 `docker compose down -v`，除非明确希望删除数据库与 Redis 数据。更详细的 Docker 原理见 [DOCKER_BEGINNER_GUIDE.md](DOCKER_BEGINNER_GUIDE.md)，本机实测证据见 [docker-acceptance-2026-07-16.md](docker-acceptance-2026-07-16.md)。

完成标准：能解释 healthcheck、depends_on、命名卷、非 root 和 graceful shutdown 各自解决的风险。

## 16. 单元 13：串起三条 Golden Path

完成单模块学习后再读 `tests/test_golden_paths.py`。它展示的不是新的底层能力，而是模块组合方式。

### 16.1 销售异常链路

```text
synthetic sales rows
→ DataPipeline 事务入库
→ 生成 SalesAlert
→ FeishuBusinessHub.sales_alert_card
→ 卡片保留人工边界
```

```bash
pytest tests/test_golden_paths.py::test_sales_pipeline_to_human_alert_golden_path -q
```

### 16.2 Listing 链路

```text
带来源的 competitor evidence
→ ListingOptimizationAgent
→ 三版五点 + deterministic compliance
→ HumanReviewRecord
→ 永不发布
```

```bash
pytest tests/test_golden_paths.py::test_evidence_to_listing_human_review_golden_path -q
```

### 16.3 广告链路

```text
Ads report facts
→ AdvertisingMetrics
→ evidence-scored hypotheses
→ Feishu 待审批卡片
→ 不执行 bid/budget 修改
```

```bash
pytest tests/test_golden_paths.py::test_ads_report_to_human_card_golden_path -q
```

### 16.4 最终讲解练习

为每条链路准备 90 秒说明，固定回答六个问题：

1. 解决哪个运营痛点？
2. 数据从哪里来？
3. 哪些值由确定性代码计算？
4. 外部系统失败时怎样处理？
5. 哪个键保证幂等？
6. 人工在哪一步接管？

完成标准：不看 README，也能从测试输入开始，把对象和函数调用一直讲到最终人工输出。

## 17. 调试决策树

### 17.1 Pydantic ValidationError

```text
先看错误字段路径
→ 判断这是 Raw、Standard 还是输出层
→ 检查 alias/日期/Decimal/长度/业务关系
→ 在最靠近契约的测试增加失败样例
```

不要直接把字段改成 `Any` 或删除约束。

### 17.2 async 测试卡住

```text
是否误用了 time.sleep？
是否给 poll/timeout 注入了 0 或很小的测试值？
MockTransport 是否遗漏某个 URL 分支？
锁内是否又等待需要同一把锁的操作？
```

### 17.3 429/5xx 没有按预期 fallback 或 retry

```text
先确认错误属于哪一层：Amazon request、Ads request、Provider adapter 还是 Gateway router
→ 检查状态码分类
→ 检查 max_attempts 和 Retry-After
→ 检查认证/配额错误是否应升级人工
→ 确认最终异常不泄露响应正文中的敏感信息
```

### 17.4 重跑产生重复数据

```text
稳定业务键是否真的稳定？
数据库是否有 UNIQUE/PRIMARY KEY？
写入是否使用 ON CONFLICT/upsert？
通知去重状态是否与记录幂等分开？
事务失败后 cursor 是否错误前进？
```

### 17.5 Docker 服务不健康

```bash
docker compose ps -a
docker compose logs --tail=100 gateway
docker compose logs --tail=100 postgres
docker compose config
```

先看状态和日志，不先删除卷或做全局 prune。

## 18. 如何安全地扩展一个功能

以“新增库存风险只读查询”为例，顺序应是：

1. 在 `models.py` 定义输入/输出合同；
2. 写分母、日期和负数等边界测试；
3. 在业务模块实现纯计算；
4. 为外部数据源定义窄 Protocol/adapter；
5. 为数据库写入选择稳定幂等键和事务；
6. 如果暴露给 MCP，增加最小 scope，seller 从 AuthContext 注入；
7. 如果展示到飞书，加入时间范围、来源、限制和人工按钮；
8. 增加成功、timeout、429/5xx、非法 JSON/数据、重复事件测试；
9. 运行 Ruff、模块测试、全量测试和离线 demo；
10. 只在真实账号证据存在后更新“已联调/已上线”表述。

高风险功能即使技术上可以执行，也只能实现为 dry-run、建议、草稿或待审批操作。不要增加自动发布 Listing、自动改价、修改广告预算或创建采购单的入口。

## 19. 每个学习单元的笔记模板

复制下面内容到你自己的学习笔记，不要把真实密钥或业务数据写进去：

````markdown
## 单元名称

### 我预测的输入/输出
- 输入：
- 输出：
- 可能异常：

### 核心调用链
`入口` → `函数/类` → `数据模型` → `输出`

### 我运行的命令
```bash
# command
```

### 我观察到的结果
- 成功路径：
- 失败路径：
- 幂等/重试/权限行为：

### 我做的小实验
- 唯一变量：
- 预期：
- 实际：
- 原因：

### 我能解释的工程取舍
- 为什么这样设计：
- 被拒绝的替代方案：
- 安全与人工边界：

### 仍不理解的问题
- （写下问题）
````

## 20. 全部学习完成后的验收

### 20.1 自动化验收

```bash
source .venv/bin/activate
pytest
ruff check amazon_ai_platform tests examples
python -m examples.01_spapi_client
python -m examples.02_feishu_bot
python -m examples.04_listing_agent
python -m examples.05_amazon_ads_client --demo
python -m examples.06_rag_knowledge_base --demo
alembic upgrade head --sql > /tmp/amazon-ai-migration.sql
docker compose config --quiet
```

### 20.2 理解验收

不看代码，尝试回答：

1. Raw、Standard、Metric 三层分别保护什么？

   **参考答案：** Raw 层忠实保存外部原值，保护可追溯性；Standard 层完成类型、币种、日期和非负约束，保护统一口径；Metric 层从可信标准数据计算 ACOS、CVR 等派生指标，保护计算定义。分层后，来源错误、清洗错误和公式错误可以分别定位。

2. 双检锁为什么能避免并发 token 刷新？

   **参考答案：** 第一次检查让有效 token 直接返回；过期时只有一个协程取得锁并刷新。其他协程排队取得锁后进行第二次检查，会发现前一个协程已写入新 token，因此直接复用，不再重复调用 LWA。锁内必须再次检查，否则等待者仍会依次刷新。

3. 429、403、timeout 和非法 JSON 分别怎样处理？

   **参考答案：** 429 按限流策略和抖动退避进行有上限重试；403 视为权限/授权问题，停止重试并升级人工；timeout 对明确可恢复的读操作有限重试，达到上限后抛出带 operation context 的异常；非法 JSON 不能进入业务层，在 Multi-LLM Gateway 中会让当前 Provider 失败并尝试 fallback，全部失败则返回安全的 503。所有错误信息都不能包含密钥或 PII。

4. 为什么 `(metric_date, sku)` 比 UUID 更适合作为报表幂等键？

   **参考答案：** 日期与 SKU 描述的是同一条业务事实，重复导入时值保持不变；随机 UUID 每次运行都会变化，只能标识一次写入，不能识别重复事实。稳定业务键配合数据库唯一约束和 upsert，才能让重跑覆盖同一记录。

5. 为什么 transaction 必须同时包含 raw、upsert 和 cursor？

   **参考答案：** 三者描述同一次同步的证据、结果和进度。如果指标写到一半但 cursor 已前移，重跑会跳过缺失数据；如果指标成功但 raw 丢失，无法审计；如果 raw 成功而指标失败，会留下误导性的半完成状态。放在同一事务中可以全部提交或全部回滚。

6. Structured Output 为什么仍需本地 Pydantic 验证？

   **参考答案：** Provider 接受 JSON Schema 只是请求约束，不是可信保证；模型、adapter 或网络响应仍可能返回非法 JSON、漏字段或超限内容。本地 Pydantic 是进入业务逻辑前的信任边界。当前 `ListingVariant` 会再次检查 Title 最多 75 字符、Item Highlight 最多 125 字符、恰好五条且互不重复的 bullets。

7. RAG 为什么在相似度计算前做时间和权限过滤？

   **参考答案：** 高相似度不代表规则当前有效或调用者有权查看。先过滤 effective date、marketplace、category 和 scope，可防止过期政策或私有 SOP 成为候选内容，也降低通过分数、排序甚至拒答差异泄漏文档存在性的风险。过滤后再做相似度排序，答案才是“相关且允许使用”的证据。

8. Listing Agent 为什么 approve 后仍不发布？

   **参考答案：** `approve` 表示人认可草稿，不等于系统获得 Amazon 写权限。当前 Agent 的职责边界是生成、检查和记录审核；`HumanReviewRecord.publishes_listing` 被固定为 `False`，MCP 也只暴露 `listing:draft`。真实发布还需要独立权限、二次确认、幂等键、审计和回滚机制，本项目没有假装已实现这些条件。

9. 飞书“记录幂等”和“通知去重”有什么区别？

   **参考答案：** 记录幂等保证同一业务事实只对应一条 Bitable 记录，例如用 `AmazonOrderId` 或 `source_key` 查找后 update/create；通知去重保证同一告警状态不会反复向群里发卡片。记录可以被更新但仍保持一条，只有严重级别或处理状态变化时才可能再次通知。两者解决的是数据重复和消息噪声两个不同问题。

10. 广告归因窗口未闭合时为什么不能立即关词？

    **参考答案：** 广告点击后的订单可能延迟归因，窗口未闭合时 attributed sales 偏低，ACOS 会被暂时高估。立即关词可能误杀之后会产生订单的流量。当前代码在报表结束不足 14 天时明确标注归因延迟，只生成继续观察的待审批建议，`executable=False`，不自动修改 bid 或 budget。

11. MCP 为什么不能让模型传 seller ID？

    **参考答案：** 模型参数是不可信输入，可能被 prompt injection 改成另一个 seller，从而造成越权读取。seller、marketplace 和 scopes 必须来自经过认证的 `AuthContext`，工具参数只描述 SKU、日期等业务查询。服务端先检查最小 scope，再把可信 tenant context 传给 backend，并只在结果和审计中记录 seller hash。

12. SIGTERM 到达 worker 后，当前 job 和新 job 分别怎样处理？

    **参考答案：** 当前实现收到 SIGTERM 后设置 `stopping`，不会取消正在执行的 `current_job`，而是等待它完成，再退出循环；退出后不再从 Redis 获取下一批任务，未取出的任务继续留在队列。需要注意一个实现细节：如果信号恰好发生在已经发出的 `BRPOP(timeout=1)` 等待期间，而该调用随后返回任务，当前代码仍可能再处理这一条任务；更严格的生产实现应在 `BRPOP` 返回后再次检查 `stopping`，必要时把任务可靠地放回队列或采用带 lease/ack 的队列协议。

如果其中某题只能背结论，回到对应单元，重新做一次“小实验”。能根据代码、测试和失败现象解释原因，才算完成这一单元。

## 21. 学习进度清单

- [ ] 单元 0：环境与测试方法
- [ ] 单元 1：Pydantic 数据契约
- [ ] 单元 2：数据质量、幂等与对账
- [ ] 单元 3：Async SP-API
- [ ] 单元 4：事务数据管道
- [ ] 单元 5：Multi-LLM Gateway
- [ ] 单元 6：Prompt 评测
- [ ] 单元 7：RAG
- [ ] 单元 8：LangGraph Listing Agent
- [ ] 单元 9：飞书控制面
- [ ] 单元 10：广告解释
- [ ] 单元 11：MCP 安全
- [ ] 单元 12：Worker、观测与 Docker
- [ ] 单元 13：三条 Golden Path
- [ ] 全量 pytest、Ruff、示例与 Compose 配置验收

完成后再阅读 [system-design-qa.md](system-design-qa.md) 做面试追问练习；需要讲项目时使用 [demo-script.md](demo-script.md)，不要把演示稿当作代码学习资料。
