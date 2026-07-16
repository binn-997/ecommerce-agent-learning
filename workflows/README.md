# 低代码工作流边界

`n8n/sales_alert_workflow.json` 只负责 schedule、调用核心 API、错误升级和等待人工审批。导入 n8n 后配置 `CORE_API_URL` 与凭据变量；不得在 Code Node 复制指标、合规或权限逻辑。

Dify/Coze 演示仅把本项目 Gateway/MCP 工具作为后端。删除低代码平台不会影响 `amazon_ai_platform/`、离线测试或四个 MCP 工具；生产凭据不得写入导出的 workflow JSON。
