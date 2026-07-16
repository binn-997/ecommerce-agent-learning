# 容量与成本估算

以下为容量规划假设，不是生产实测或报价承诺。模型单价通过部署配置输入，仓库不硬编码易过时价格。

| 档位 | 单 seller | 100 sellers |
|---|---:|---:|
| 日报窗口 | 每日 1 次 + 失败重放 | 每日 100 次，按 operation 限流排队 |
| Ads campaign 日行数假设 | 2,000 | 200,000 |
| Listing 草稿峰值 | 2 concurrent | 50 concurrent（Gateway semaphore） |
| 原始 JSON 假设 | 5 MB/日 | 500 MB/日；30 天热存约 15 GB |
| PostgreSQL | 单实例，本地卷仅演示 | 托管 HA、分区/归档、备份恢复演练 |
| Redis/worker | 1 worker | 按队列延迟水平扩展，tenant 公平调度 |

模型成本公式：`input_tokens × input_unit_price + output_tokens × output_unit_price`。告警预算应按 seller、provider、模型别名设置；Gateway 记录 token/fallback，不保存 prompt 全文。100 sellers 必须增加 tenant 级并发配额、队列背压、报表事件优先于轮询，以及数据库连接池上限。
