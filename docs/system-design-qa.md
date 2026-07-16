# 系统设计答辩 20 问

1. 为什么先做数据契约？——Agent 不能修复未识别的口径漂移，先阻断错误输入。
2. GMV 与广告归因销售为何不同？——归因窗口和自然销售口径不同，不能直接相减或替换。
3. 如何接近 exactly-once？——至少一次交付 + 业务唯一键 + 单事务 + 可回放 raw。
4. 为什么 operation 级限流？——Amazon usage plan 按 operation 与 seller/application pair 变化。
5. 为什么全抖动？——避免多个 worker 同步退避后再次同时冲击上游。
6. 403 为什么不重试？——权限/角色/RDT 问题不会被延迟解决，应携 request ID 升级人工。
7. Structured Output 有哪三层？——已注册 Schema、Provider schema 请求、本地 Pydantic 二次验证。
8. 认证错误为何不 fallback？——可能是配置或配额事故，盲目切换会扩大成本与权限问题。
9. 熔断与 semaphore 分别解决什么？——前者隔离持续故障，后者提供背压与资源上限。
10. 为什么硬规则不用 LLM？——必须确定、可定位、能证明零漏检。
11. LangGraph 的实际价值？——显式状态、节点 trace、中断、checkpoint 和有限重试。
12. RAG 为什么按 effective date 过滤？——流畅引用过期规则仍是错误答案。
13. 订单为什么不进向量库？——它是实时结构化受权数据，应走只读工具。
14. MCP 是安全边界吗？——不是；认证上下文、scope、最小工具面和审计才是。
15. Prompt injection 如何防写操作？——服务器根本不注册发布、改价、广告或采购工具。
16. 飞书如何去重？——source_key 幂等 upsert；只有状态/严重度变化再通知。
17. ACOS 为何可能为空？——归因销售为零时除法无定义，返回 `None` 避免假零。
18. 如何处理归因延迟？——输出 14 天观察窗口，不形成武断结论，不自动调 bid/budget。
19. SIGTERM 如何不丢当前 job？——停止领取新任务，等待 current task，Compose 给 30 秒窗口。
20. 100 sellers 首先扩什么？——tenant 公平队列、连接池、worker、存储分区和预算，不先扩大模型上下文。
