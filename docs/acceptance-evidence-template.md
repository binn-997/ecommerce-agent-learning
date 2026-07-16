# 外部验收证据模板

此文件只提供记录格式，不预填或编造结果。

- 全新 clone 开始/结束时间、机器、Python/Docker 版本：待记录
- SP-API sandbox/最小真实调用：日期、operation、脱敏 request ID、角色：待记录
- Ads profile 最小调用：日期、脱敏 report ID、marketplace：待记录
- 飞书测试租户：权限 smoke test、同一 source_key 两次记录数、脱敏截图：待记录
- Provider 故障演示：503、非法 JSON、fallback provider、trace：待记录
- before/after：报表人工耗时、重复告警数、Listing 审核时长；样本区间与口径：待记录
- 2–3 分钟视频链接：待记录
- Release tag 与 CI run：待记录

不得把既有 GMV 归因于未上线平台，也不得用 synthetic 测试结果替代真实业务 before/after。
