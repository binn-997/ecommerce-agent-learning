# Python 项目学习笔记

## 1. Python 环境

```bash
cd /Users/cpt/project/aiyy/ecommerce-agent-learning-plan
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

- `python3 -m venv .venv`：使用 `python3` 创建名为 `.venv` 的项目虚拟环境。
- `source .venv/bin/activate`：激活虚拟环境，让当前终端优先使用项目自己的 Python、`pip` 和工具。
- `python -m pip install -r requirements-dev.txt`：用当前 Python 调用 `pip`，安装开发和测试依赖。
- `python` 不能使用而 `python3` 可以，通常是系统只安装了 Python 3，或没有创建名为 `python` 的命令别名。进入虚拟环境后，项目中的 `python` 一般可直接使用。

`.venv` 会占用本地磁盘空间，但通常已加入 `.gitignore`，不会提交到 Git，也不会让仓库本身变得臃肿。其他人可以根据依赖文件重新创建它。

## 2. 依赖文件

- `requirements.txt`：项目运行所需的依赖。
- `requirements-dev.txt`：开发、测试和代码检查所需的额外依赖，通常会通过 `-r requirements.txt` 同时安装运行依赖。

## 3. pytest 和 Ruff

`pytest` 用来验证代码功能是否正确；`ruff` 用来进行静态检查，发现代码风格、潜在错误和不符合规范的写法。Ruff 不会运行业务测试。

```bash
# 运行一个测试文件
pytest tests/test_data_quality.py -q

# 只运行指定测试函数
pytest tests/test_data_quality.py::test_advertising_denominator_zero_is_none -q

# 显示 print、日志和更完整的失败上下文
pytest tests/test_data_quality.py -q -s

# 检查指定目录中的 Python 代码
ruff check amazon_ai_platform tests examples
```

测试应当离线、稳定、可重复，因此 CI 不应依赖真实 Amazon、飞书或 LLM：网络、限流、密钥、费用、真实数据和模型随机输出都会让测试不稳定，也可能造成误操作。外部系统应使用 Mock、Fixture、Fake Provider 和合成数据；真实 API 联调应单独进行。

## 4. Python REPL

REPL 是 Python 的交互式命令行环境，含义是 Read、Eval、Print、Loop。启动：

```bash
python3
```

看到 `>>>` 后可以直接试运行表达式、查看类型和验证函数结果。输入 `exit()` 或按 `Ctrl+D` 退出。REPL 中的代码通常不会自动保存到项目文件。

## 5. Pydantic 模型校验

`StandardAdvertisingRow` 用 Pydantic 描述一行标准化广告数据，并自动检查字段类型、格式和业务规则。

字段约束示例：

- `currency: str = Field(pattern=r"^[A-Z]{3}$")`：必须是 3 位大写货币代码，例如 `USD`。
- `impressions: int = Field(ge=0)`：曝光数不能小于 0。
- `campaign_id` 和 `sku` 的长度必须在 1 到 128 之间。
- `spend` 和 `attributed_sales` 必须是非负金额，最多 2 位小数。

```python
@model_validator(mode="after")
def counts_are_consistent(self) -> "StandardAdvertisingRow":
    if self.clicks > self.impressions:
        raise ValueError("clicks cannot exceed impressions")
    if self.purchases > self.clicks:
        raise ValueError("purchases cannot exceed clicks")
    return self
```

这是模型级校验器：Pydantic 先完成字段转换和单字段校验，再执行它检查字段之间的关系。`self` 是当前模型对象；`raise ValueError` 表示数据不合法；`return self` 表示校验通过并返回模型对象。

## 6. 完成标准：追溯数据和约束

“能从任意一个输出模型向前追溯它依赖的 Standard/Raw 数据”表示：看到一个最终指标或 Agent 输出时，能说明它来自哪个数据模型、经过了哪些转换、依赖哪些原始字段以及计算逻辑。

例如：

```text
RawAdvertisingRow
    -> 清洗、转换
StandardAdvertisingRow
    -> 计算 attributed_sales / spend
AdvertisingMetrics 或最终报表输出
```

同时，至少能解释三条 Pydantic 业务约束，例如：点击数不能超过曝光数、购买数不能超过点击数、货币必须是三位大写代码。也就是说，需要理解数据血缘，以及数据为什么被认为合法。

## 7. 数据质量小实验

目标是一次只改变一个数据质量条件，观察质量门禁命中了哪条规则。相关规则位于 `amazon_ai_platform/data_quality.py` 的 `audit_sales_rows()` 中。

先运行原始测试，确认基线：

```bash
pytest tests/test_data_quality.py::test_quality_gate_reports_multiple_bad_fields -q
```

然后在测试数据中每次只改一项，再运行测试并记录 `issue.rule_id`：

| 修改 | 预期规则 |
|---|---|
| `EUR` 改为 `eur` | `DQ08_CURRENCY_FORMAT` |
| `units` 改为负数，例如 `-2` | `DQ11_UNITS_NON_NEGATIVE` |
| `parent_asin` 与 `child_asin` 改成相同的合法 ASIN | `DQ18_PARENT_CHILD_DIFFERENT` |
| 复制同一天、同 SKU 的一行 | `DQ07_IDEMPOTENT_KEY_UNIQUE` |

实验结束后必须把测试夹具恢复，否则后续正常路径测试会失败。可以用 `git diff -- tests/test_data_quality.py` 检查是否还有临时修改。

### 当前代码中的注意事项

实验说明中的“synthetic CSV”和命令与当前代码并不完全匹配：`test_quality_gate_reports_multiple_bad_fields()` 没有使用顶部的 `CSV` 常量，而是直接创建了一个坏的 `RawSalesTrafficRow`。因此，单独修改 `CSV` 后运行这个测试，测试结果不会改变。

若要观察 CSV 的变化，应让测试调用 `parse_sales_csv(CSV)` 和 `audit_sales_rows(...)`，或者在 Python REPL 中临时构造数据并打印：

```python
rows = parse_sales_csv(CSV)
issues = audit_sales_rows(
    rows,
    known_skus={"SYNTHETIC-1"},
    start=date(2026, 7, 1),
    end=date(2026, 7, 31),
    today=date(2026, 7, 31),
)
print([issue.rule_id for issue in issues])
```

## 8. 本轮学习问题速记

- `normalize_sales_rows(rows: Iterable[RawSalesTrafficRow]) -> list[StandardSalesTrafficRow]` 是带类型标注的函数定义：输入是可迭代的 Raw 行，输出是 Standard 行列表。
- 输入行的排列顺序可以变化，函数会按输入顺序处理和返回，不会自动排序；`row_number` 只是遍历时的行号，默认从 2 开始以跳过 CSV 表头。
- 字段在字典中的排列顺序通常不影响 Pydantic 按字段名校验，但输入元素必须是 `RawSalesTrafficRow`，因为代码调用了 `row.model_dump()`。
- 标准化函数会收集所有校验错误，最后统一抛出 `DataQualityError`，而不是遇到第一条错误就停止。

之后的学习问题会继续追加到本文件，使用精炼问答形式记录。

## 9. `data_quality.py` 文件结构

这个文件是一条离线数据质量流水线：

```text
CSV 文本
  -> parse_sales_csv()
RawSalesTrafficRow
  -> audit_sales_rows()
DataQualityIssue 列表
  -> normalize_sales_rows()
StandardSalesTrafficRow
  -> IdempotentMetricStore / reconcile_revenue()
存储或对账结果
```

各部分职责如下：

- 文件头导入 `csv`、`io`、`date`、`Decimal` 等标准库，用于 CSV 解析、日期校验和金额计算；`models.py` 中的 Pydantic 模型负责数据契约。
- `QUALITY_RULES` 集中列出 20 条规则，方便测试规则数量、保持规则编号稳定，也便于文档和代码对照。
- `REQUIRED_COLUMNS` 定义 CSV 必须拥有的列。缺列属于文件级错误，由 `parse_sales_csv()` 直接抛出 `DataQualityError`。
- `DataQualityError` 把多条 `DataQualityIssue` 集中放进一个异常，调用方可以一次看到所有问题，而不是修一条、重新运行一次。
- `parse_sales_csv()` 只负责把 CSV 变成 `RawSalesTrafficRow`。Raw 层保留字符串，便于审计原始值；它不负责完整的业务判断。
- `_is_asin()` 是一个私有辅助函数，集中处理 ASIN 的 10 位、大写、字母数字格式，避免主审计函数重复代码。
- `audit_sales_rows()` 是质量门禁核心。它逐行检查日期、SKU、重复键、货币、数量、金额和 ASIN，并收集全部问题后返回。`seen` 用来检测同一天同 SKU 的重复数据。
- `normalize_sales_rows()` 把 Raw 模型转换成 Standard 模型，让 Pydantic 负责字符串到日期、整数和 Decimal 的转换及标准层约束；转换失败会收集为 `SCHEMA_STANDARD_LAYER`。
- `IdempotentMetricStore` 是离线的内存 Fake Store。字典键使用 `(metric_date, sku)`，重复写入同一业务键会覆盖而不是新增，模拟数据库 upsert 的幂等行为。
- `reconcile_revenue()` 将标准化数据的收入总和与 Seller Central 总额比较，计算差额和差异比例，并根据容忍度判断是否通过。
- `_issue()`、`_parse_int()`、`_parse_decimal()` 是私有辅助函数，分别统一构造问题、解析整数和解析金额，让主流程更容易阅读。

这样分层的原因是把“原始数据保留”“质量审计”“类型标准化”“写入幂等”“金额对账”分开。每层只有一个主要职责，测试可以分别验证，也不会把外部 CSV 格式、业务规则和数据库行为混在一个大函数里。

需要注意：`audit_sales_rows()` 的 `DQ19_UNITS_WITH_REVENUE` 严重级别是 `warning`，但仍会出现在返回的问题列表中；`DataQualityError` 的错误数量描述偏通用。`reconcile_revenue()` 使用 Decimal 计算金额，避免用二进制浮点数直接累加货币。

## 10. 输入顺序是否有影响

需要区分三种顺序：

1. **CSV 列的顺序**：通常没有影响。`csv.DictReader` 按表头名称生成字典，后续通过 `row.metric_date`、`row.sku` 等字段名读取数据，所以只要表头名称正确，列可以重新排列。缺少必要表头才会触发 `DQ01_REQUIRED_COLUMNS`。
2. **质量规则的检查顺序**：没有业务影响。代码先检查日期、再检查 SKU、货币等，只是执行顺序，不要求 CSV 必须按照这个顺序提供字段。某个字段错误时，其他检查仍会继续执行。
3. **数据行的顺序**：日期可以乱序，重复行也不要求相邻。`seen` 是集合，因此只要同一天同 SKU 曾经出现过，后面再次出现就会命中 `DQ07_IDEMPOTENT_KEY_UNIQUE`。顺序只会影响哪一行被标记为重复，以及错误中的 `row_number`。

例如下面两种 CSV 列顺序都可以被正确读取：

```text
metric_date,sku,parent_asin,child_asin,currency,units,sessions,revenue
```

```text
revenue,sku,units,metric_date,currency,child_asin,sessions,parent_asin
```

但表头必须存在且拼写一致；把 `metric_date` 改名为 `date`，不会被当作同一个字段，而会触发缺少必要列的错误。

## 11. 幂等键

幂等键是用来唯一识别一条业务记录的键。对同一条记录重复执行写入操作，最终结果应该和执行一次相同，不应该产生重复数据。

本项目中的幂等键是：

```python
(metric_date, sku)
```

例如：

```text
(2026-07-01, SYNTHETIC-1)
```

`IdempotentMetricStore` 用这个键保存数据。相同文件导入两次时，第二次会覆盖相同键的记录，而不是新增第二条记录。

`audit_sales_rows()` 会在导入前检查相同日期和 SKU 是否重复，并报告 `DQ07_IDEMPOTENT_KEY_UNIQUE`。因此，“重复写入”可以安全地被覆盖，而“同一个业务键对应了不同数据”会先被质量检查发现。

## 12. 一天同一 SKU 的多笔订单

本模块处理的是按天汇总的 Sales & Traffic 数据，不是逐笔订单数据。一个 SKU 在一天内可以有很多订单，但导入前应已被汇总为一行：

```text
2026-07-01, SKU-A, units=8, revenue=399.20
```

这里的 `units=8` 代表当天多笔订单中该 SKU 的总销量。因此 `(metric_date, sku)` 作为幂等键是合理的：同一店铺、同一站点、同一天、同一 SKU 应只有一条日报汇总。

若输入是订单明细，一天同一 SKU 出现多行是正常业务，不应使用这个键。订单数据通常使用 `order_id`、`order_item_id` 等订单级键；若日报还需要区分店铺、站点、广告活动或仓库，幂等键也应扩展为包含这些维度，例如 `(marketplace_id, metric_date, sku)`。幂等键必须与数据粒度一致。

## 13. 完成标准：20 条数据质量规则与新业务键

下面每条的“业务原因”可以直接用于面试或复述。达到标准时，至少能脱离笔记解释其中 10 条。

| 规则 | 业务原因 |
|---|---|
| `DQ01_REQUIRED_COLUMNS` | 缺少列就无法知道数据含义；不能把未知字段位置猜成日期、SKU 或金额。 |
| `DQ02_DATE_FORMAT` | 无法解析的日期不能用于按天汇总、去重和趋势分析。 |
| `DQ03_DATE_WINDOW` | 只允许本次导入的业务时间范围，防止误把历史文件或错误周期的数据混入报表。 |
| `DQ04_NOT_FUTURE` | 未来日期通常表示时区、导出参数或文件内容异常，会污染当前经营指标。 |
| `DQ05_SKU_PRESENT` | 没有 SKU 就无法归属商品，也无法建立业务键。 |
| `DQ06_SKU_KNOWN` | 未知 SKU 可能是拼写错误、已下架商品或跨店铺数据，需要先人工确认归属。 |
| `DQ07_IDEMPOTENT_KEY_UNIQUE` | 同一数据粒度内重复会导致销量和收入被重复统计。 |
| `DQ08_CURRENCY_FORMAT` | 货币必须是可识别的 ISO 格式，避免把 `eur`、`EURO` 等非标准值混入金额计算。 |
| `DQ09_CURRENCY_EXPECTED` | 即使格式正确，`USD` 混入德国站 EUR 报表仍会让总收入失真。 |
| `DQ10_UNITS_INTEGER` | 销量是件数，`2.5` 或 `abc` 不能直接参与销量、转化率和库存决策。 |
| `DQ11_UNITS_NON_NEGATIVE` | 常规销售日报不应有负销量；退款应通过明确的退货/调整数据处理。 |
| `DQ12_SESSIONS_INTEGER` | 访问次数必须是整数，非整数或文本说明数据格式异常。 |
| `DQ13_SESSIONS_NON_NEGATIVE` | 访问次数不能为负；负数会产生无意义的 CVR。 |
| `DQ14_REVENUE_DECIMAL` | 金额必须能精确转换为 Decimal，不能让 `N/A` 等文本进入加总。 |
| `DQ15_REVENUE_NON_NEGATIVE` | 常规销售收入不应为负，负数往往说明退款、币种或导出逻辑需要单独处理。 |
| `DQ16_PARENT_ASIN_FORMAT` | 非法父 ASIN 无法可靠关联变体族和竞品信息。 |
| `DQ17_CHILD_ASIN_FORMAT` | 非法子 ASIN 无法定位具体可售变体，影响 Listing 和库存分析。 |
| `DQ18_PARENT_CHILD_DIFFERENT` | 父体表示变体集合，子体表示具体商品；两者相同通常说明映射错误。 |
| `DQ19_UNITS_WITH_REVENUE` | 有销量但收入为 0 值得关注，可能是促销、赠品或漏数；因此是 warning，仍可人工判断。 |
| `DQ20_PARENT_CHILD_PRESENT` | 缺少任一 ASIN 会削弱变体归因和后续 Listing 分析，需要补全。 |

### 新的稳定业务键设计

当前键 `(metric_date, sku)` 隐含前提是：只有一个店铺、一个站点、一个日报数据源。真实的多店铺、多站点系统可使用：

```python
sales_daily_key = (
    "amazon_sales_traffic_daily",
    seller_id,
    marketplace_id,
    metric_date,
    sku,
)
```

设计理由：

- `amazon_sales_traffic_daily`：区分数据来源和日报粒度，防止与订单明细、广告数据混用。
- `seller_id`：同一 SKU 可能在不同卖家账号中存在。
- `marketplace_id`：同一卖家可同时经营德国站、法国站等，站点指标不能合并为一条。
- `metric_date`：这是日报的时间粒度。
- `sku`：这是商品粒度。

不要把 `import_batch_id`、CSV 行号、导入时间放进幂等键：它们每次导入都会变化，会让同一业务记录被误判为不同记录。`currency`、`revenue`、`units` 等是这条记录的属性，不是它的身份；数值修正后应更新原记录，而不是生成新记录。

可以这样自测：如果同一份文件重跑，键必须完全相同；如果店铺、站点、日期或 SKU 任一业务维度变化，键必须不同。
