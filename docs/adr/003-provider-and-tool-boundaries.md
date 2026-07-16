# ADR-003：Provider Adapter 与最小 MCP 工具面

- 状态：Accepted
- 日期：2026-07-16

## 决策

模型供应商协议封装在 Gateway adapter，业务只依赖统一请求和已注册 Schema。MCP 只暴露销售指标、库存风险、政策搜索、Listing 草稿四个工具；seller/marketplace 由可信认证上下文注入。

## 原因与后果

Provider 差异不应泄漏到业务模型；MCP 协议本身不是授权边界。最小工具面使 Prompt injection 找不到改价、广告预算、发布或采购入口。认证/配额错误停止 fallback 并升级人工，临时 5xx、超时和非法结构化输出才降级。
