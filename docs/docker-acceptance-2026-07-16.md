# Docker 运行验收记录（2026-07-16）

环境：macOS Colima（Virtualization.Framework、aarch64）、Docker Engine 29.5.2。

## 已验证

- `docker compose config --quiet` 通过。
- `docker compose up -d --build` 成功构建 gateway/worker，并启动 PostgreSQL 16、Redis 7.4、gateway、worker。
- gateway、PostgreSQL、Redis healthcheck 为 healthy；worker 保持运行。
- `GET /health`、`GET /metrics` 返回 HTTP 200。
- 无 Provider Key 时结构化请求返回安全 HTTP 503 和 request ID，不泄露堆栈或密钥。
- PostgreSQL 初始化九张业务表；事务内写入 synthetic 行后 `ROLLBACK`，回滚后行数为 0。
- Redis `PING` 返回 `PONG`；synthetic `sync_sales` job 被 worker 消费，队列长度回到 0。
- gateway/worker 容器均以 UID/GID 65532 非 root 运行。
- gateway/worker 收到 SIGTERM 后均 `exit=0`、`OOMKilled=false`；gateway 完成 Uvicorn shutdown lifecycle。
- 验收后执行普通 `docker compose down`；容器与网络已删除，`postgres_data`、`redis_data` 命名卷保留。

运行验收发现并修复一处缺陷：已注册 alias 但 Provider 列表为空时原返回 400，现按“服务暂不可用”返回 503，并增加回归测试。

## 环境提示

- 主机未安装 Docker Buildx plugin，Compose 回退 classic builder，使 gateway/worker 首次构建重复下载相同依赖；不影响运行正确性，但建议安装 Buildx 或复用单一应用镜像以缩短构建时间。
- Redis 在 Colima 中提示 `vm.overcommit_memory` 未开启；本次 AOF、队列和健康检查正常，压力/生产环境应按 Redis 建议调整 VM sysctl。
- PostgreSQL Alpine 初始化提示系统 locale 不可用；数据库以 UTF-8 正常创建并通过健康检查，若业务依赖德语 locale 排序需显式安装/配置 ICU locale。
