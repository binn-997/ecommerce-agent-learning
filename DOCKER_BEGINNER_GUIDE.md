# Docker 与 Docker Compose 零基础学习手册

> 适用环境：macOS + Colima + Docker CLI + Docker Compose  
> 配套项目：`ecommerce-agent-learning-plan`  
> 目标：能看懂配置，并独立完成构建、部署、验证、排错和关闭。

## 1. Docker 解决什么问题

不用 Docker 时，项目换一台电脑可能因为 Python 版本、依赖、操作系统、数据库版本或环境变量不同而无法运行。Docker 把应用及其运行环境一起交付，让面试官拿到 GitHub 项目后能用接近统一的方式启动：

```bash
docker compose up -d --build
```

本项目的关系如下：

```text
浏览器 / curl
      │ http://localhost:8000
      ▼
Mac 宿主机端口 8000
      │ 端口映射 8000:8000
      ▼
gateway 容器（FastAPI + Uvicorn）
      │ Compose 内部地址 postgres:5432
      ▼
postgres 容器（PostgreSQL 16）
      │
      ▼
postgres_data 数据卷（保存数据库数据）
```

“宿主机”就是你的 Mac；“容器内部”是隔离出的 Linux 运行环境。

## 2. 六个核心概念

### 2.1 镜像 Image：只读模板

镜像相当于“安装包 + 运行环境模板”，可以包含操作系统文件、Python、依赖、项目代码和默认启动命令。

本项目中：

- gateway 镜像根据项目的 `Dockerfile` 构建；
- postgres 使用公开镜像 `postgres:16-alpine`。

镜像不是正在运行的程序。查看镜像：

```bash
docker images
```

### 2.2 容器 Container：镜像的运行实例

```text
镜像（模板） ──启动──> 容器（运行实例）
```

同一个镜像可以启动多个容器，类似一个 Python 类能创建多个对象。容器拥有自己的进程、文件系统、网络和环境变量，但它不是一台完整虚拟机。

查看容器：

```bash
docker ps       # 只看运行中的容器
docker ps -a    # 包括已经停止的容器
```

macOS 不能直接运行 Linux 容器，所以 Colima 提供轻量 Linux 虚拟机：

```text
macOS
└── Colima Linux 虚拟机
    └── Docker Engine
        ├── gateway 容器
        └── postgres 容器
```

### 2.3 Docker Engine 与 Docker CLI

- Docker Engine：管理镜像、容器、网络和数据卷的后台服务；
- Docker CLI：终端中的 `docker` 命令，用来向 Engine 发请求；
- Colima：在 Mac 上承载 Docker Engine 的 Linux 环境。

```text
你输入 docker 命令 → Docker CLI → Colima 中的 Docker Engine → 容器
```

### 2.4 Dockerfile：制作镜像的配方

本项目 `Dockerfile` 的关键内容：

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY amazon_ai_platform ./amazon_ai_platform
USER 65532:65532
EXPOSE 8000
CMD ["uvicorn", "amazon_ai_platform.llm_gateway:app", "--host", "0.0.0.0", "--port", "8000"]
```

| 指令 | 含义 |
|---|---|
| `FROM` | 以 Python 3.12 精简镜像为基础 |
| `WORKDIR` | 设置容器内工作目录 |
| `COPY` | 把宿主机文件复制进镜像 |
| `RUN` | 构建镜像时执行命令 |
| `USER` | 使用非 root 用户运行，降低安全风险 |
| `EXPOSE` | 声明应用使用 8000 端口；不等于对宿主机开放 |
| `CMD` | 容器启动时默认执行的命令 |

执行 `docker compose build` 时会读取 Dockerfile 并生成镜像。

### 2.5 Docker Compose：多容器编排说明书

真实项目通常同时需要 API、数据库、缓存等服务。Compose 用一个 YAML 文件集中描述服务、端口、网络、环境变量、数据卷和健康检查，避免手写多条复杂的 `docker run`。

本项目的 `docker-compose.yml` 定义：

- `gateway`：FastAPI API 服务；
- `postgres`：PostgreSQL 数据库；
- `postgres_data`：持久化数据库数据的命名卷。

Compose 默认创建项目网络，容器之间通过服务名通信。gateway 访问数据库应使用 `postgres:5432`，不能使用 `localhost:5432`。容器中的 `localhost` 只代表这个容器自己。

### 2.6 Gateway：统一 API 入口

`gateway` 不是 Docker 专用术语，而是本项目给一个服务起的名字。Gateway 通常译作“网关”，位于调用方和多个后端能力之间，负责：

- 接收 HTTP 请求；
- 验证请求和身份；
- 调用 Claude、DeepSeek、OpenAI 等上游模型；
- 模型失败时自动降级；
- 并发限制、统一错误、日志和监控；
- 返回统一格式的响应。

本项目 gateway 是 `amazon_ai_platform.llm_gateway:app` 这个 FastAPI 对象，由 Uvicorn 运行。容器内监听 8000，Compose 把 Mac 的 8000 端口映射给它，所以本机可以访问：

```bash
curl http://127.0.0.1:8000/health
```

注意区分：

| 名称 | 含义 |
|---|---|
| gateway 服务 | Compose 中的服务定义 |
| gateway 镜像 | Dockerfile 构建的只读模板 |
| gateway 容器 | 镜像启动后的运行实例 |

## 3. `docker compose pull` 是什么

`pull` 是从镜像仓库下载已有镜像到本机，默认公共仓库通常是 Docker Hub：

```bash
docker compose pull
```

对本项目来说：

- `postgres` 配置了 `image: postgres:16-alpine`，可以从仓库拉取；
- `gateway` 配置的是 `build: .`，主要根据本地 Dockerfile 构建，而非拉取本项目的成品镜像。

因此 gateway 代码更新后通常执行：

```bash
docker compose build gateway
```

命令区别：

| 命令 | 动作 | 启动容器吗 |
|---|---|---:|
| `docker compose pull` | 下载远程已有镜像 | 否 |
| `docker compose build` | 根据 Dockerfile 在本地制作镜像 | 否 |
| `docker compose up` | 创建并启动服务，必要时拉取或构建 | 是 |
| `docker compose up -d --build` | 先构建，再后台启动 | 是 |

`docker compose pull` 不会更新 Git 代码，也不会启动服务。`git pull` 和 `docker compose pull` 是两件不同的事。

## 4. 端口与网络

Compose 中：

```yaml
ports:
  - "8000:8000"
```

格式是 `宿主机端口:容器端口`，表示 Mac 的 8000 转发到容器的 8000。

| 请求位置 | gateway 地址 | postgres 地址 |
|---|---|---|
| Mac 宿主机 | `127.0.0.1:8000` | `127.0.0.1:5432` |
| Compose 中其他容器 | `gateway:8000` | `postgres:5432` |
| gateway 容器自身 | `127.0.0.1:8000` | `postgres:5432` |

生产环境通常不应直接把数据库端口暴露到公网。

## 5. 数据卷 Volume

容器可随时删除重建，重要数据不应只放在容器的可写层。本项目：

```yaml
volumes:
  - postgres_data:/var/lib/postgresql/data
```

将数据库目录连接到 Docker 管理的命名卷。这样容器删除后，数据卷默认仍保留。

```bash
docker volume ls
docker compose down       # 保留命名卷
docker compose down -v    # 删除命名卷，数据库数据会丢失
```

不确定时不要使用 `-v`。

本项目还有绑定挂载：

```yaml
- ./sql/init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
```

它把 Mac 上的文件挂载到容器，`:ro` 表示只读。

## 6. 环境变量与密钥

gateway 会尝试读取 `.env`。项目提交 `.env.example` 作为模板，真实 `.env` 不应进入 Git：

```bash
cp .env.example .env
```

不要把 API Key 写入 Dockerfile、Compose、Python 源码、Git commit 或公开日志。

下面的语法表示优先使用外部变量，否则使用默认值：

```yaml
POSTGRES_DB: ${POSTGRES_DB:-ecommerce_ai}
```

## 7. 健康检查 Healthcheck

容器进程存在不代表业务真的可用。本项目 gateway 定期访问 `/health`，状态可能是：

- `starting`：仍在启动；
- `healthy`：检查成功；
- `unhealthy`：连续检查失败。

```bash
docker compose ps
curl http://127.0.0.1:8000/health
```

刚执行 `up` 就立刻访问可能失败，因为 Uvicorn 尚未启动完成。

## 8. 从零部署本项目

### 8.1 进入正确目录

```bash
cd /Users/cpt/project/aiyy/ecommerce-agent-learning-plan
```

Compose 默认在当前目录寻找 Compose 文件。目录错误是最常见的新手问题之一。

### 8.2 启动 Docker Engine

```bash
colima status
colima start
docker context use colima
docker info
```

Colima 已运行时无需重复启动。

### 8.3 验证配置

```bash
docker compose config --quiet
docker compose config
```

第一条没有输出且退出状态为 0，通常表示配置合法。第二条显示变量替换后的最终配置，可能含敏感变量，不要公开粘贴。

### 8.4 构建并后台启动

```bash
docker compose up -d --build
```

- `up`：创建并启动服务；
- `-d`：后台运行；
- `--build`：启动前构建本地镜像。

只启动 gateway：

```bash
docker compose up -d --build gateway
```

### 8.5 验证部署

```bash
docker compose ps
docker compose logs --tail=100 gateway
curl http://127.0.0.1:8000/health
```

持续查看日志：

```bash
docker compose logs -f gateway
```

按 `Ctrl+C` 只结束日志跟随，不会停止后台容器。

### 8.6 安全关闭

```bash
docker compose down
```

这会停止并删除本项目的容器和默认网络，默认保留镜像与数据卷。如果当天不再使用任何 Docker 项目：

```bash
colima stop
```

## 9. stop、down、kill 与 Colima stop

| 命令 | 容器进程 | 容器记录 | 网络 | 数据卷 | 场景 |
|---|---:|---:|---:|---:|---|
| `docker compose stop` | 停止 | 保留 | 保留 | 保留 | 暂停，之后 `start` |
| `docker compose down` | 停止 | 删除 | 删除 | 默认保留 | 正常结束部署 |
| `docker compose down -v` | 停止 | 删除 | 删除 | 删除 | 明确要重置数据库 |
| `docker compose kill` | 强制终止 | 保留 | 保留 | 保留 | 无法正常停止时 |
| `colima stop` | 所有项目停止 | 状态一般保留 | 停止 | 一般保留 | 不再使用任何 Docker 项目 |

日常推荐：

```bash
docker compose down
colima stop  # 当天不再使用其他 Docker 项目时
```

## 10. 常用命令速查

### 查看资源

```bash
docker compose ps       # 当前 Compose 项目状态
docker ps               # 所有运行容器
docker ps -a            # 所有容器
docker images           # 镜像
docker volume ls        # 数据卷
docker network ls       # 网络
docker compose top      # 容器内进程
docker compose stats    # CPU、内存和网络占用
docker system df        # Docker 磁盘占用
```

### 构建和启动

```bash
docker compose build
docker compose build gateway
docker compose build --no-cache gateway
docker compose up                  # 前台启动
docker compose up -d               # 后台启动
docker compose up -d --build       # 重建并后台启动
```

### 日志

```bash
docker compose logs
docker compose logs gateway
docker compose logs -f gateway
docker compose logs --tail=100 gateway
docker compose logs -f --since=10m
```

### 在容器中执行命令

```bash
docker compose exec gateway sh
docker compose exec gateway python --version
docker compose exec postgres psql -U ecommerce -d ecommerce_ai
docker compose run --rm gateway pytest
```

`exec` 要求容器已经运行；`run --rm` 创建一次性容器，命令结束后删除。

### 更新与重启

```bash
docker compose pull
docker compose restart gateway
docker compose up -d --build gateway
```

`restart` 只重启现有容器，不重新复制最新代码。当前项目的代码通过 Dockerfile `COPY` 进入镜像，修改代码后需要重新 build。

## 11. 更新代码后的可靠流程

```bash
cd /Users/cpt/project/aiyy/ecommerce-agent-learning-plan

git pull                         # 更新 Git 代码
docker compose pull              # 更新第三方远程镜像
docker compose up -d --build     # 重建业务镜像并更新容器
docker compose ps
docker compose logs --tail=100 gateway
curl http://127.0.0.1:8000/health
```

生产环境还要考虑版本化镜像、数据库迁移、回滚、密钥管理、监控和零停机发布。

## 12. 常见问题和排错顺序

### 12.1 无法连接 Docker daemon

```bash
colima status
colima start
docker context use colima
docker info
```

### 12.2 `port is already allocated`

表示宿主机端口已被占用：

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
docker ps --format 'table {{.Names}}\t{{.Ports}}'
```

停止占用者，或把映射改成 `8001:8000`，再访问 `localhost:8001`。

### 12.3 `no configuration file provided`

当前目录找不到 Compose 文件：

```bash
pwd
ls
cd /Users/cpt/project/aiyy/ecommerce-agent-learning-plan
docker compose config
```

### 12.4 容器不断退出

```bash
docker compose ps -a
docker compose logs --tail=200 gateway
```

常见原因：启动命令错误、模块导入失败、变量缺失、依赖缺失或端口冲突。

### 12.5 修改代码后没有变化

```bash
docker compose up -d --build gateway
```

如果怀疑构建缓存：

```bash
docker compose build --no-cache gateway
docker compose up -d gateway
```

### 12.6 gateway 连接不上 postgres

容器内数据库主机应为服务名 `postgres`，不是 `localhost`：

```bash
docker compose ps
docker compose logs postgres
docker compose exec gateway getent hosts postgres
```

### 12.7 拉取镜像超时或 DNS 失败

```bash
docker pull hello-world
docker compose pull
```

Colima 内的代理或 DNS 可能影响访问镜像仓库。先检查网络，不要为了网络问题删除镜像或数据卷。

### 12.8 磁盘空间不足

```bash
docker system df
```

`prune` 可能删除未使用的镜像、容器、网络或卷。零基础阶段不要直接复制执行 `docker system prune -a --volumes`，应先确认每类资源是否有价值。

### 推荐排错顺序

```bash
pwd
docker info
docker compose config --quiet
docker compose ps -a
docker compose logs --tail=200 <服务名>
```

先收集证据，再修改配置或删除资源。

## 13. `docker run` 与 `docker compose up`

临时运行一个容器：

```bash
docker run --rm hello-world
```

直接启动单个后台服务：

```bash
docker run -d --name demo-api -p 8000:8000 some-api-image
```

当服务涉及数据库、环境变量、数据卷、网络和健康检查时，命令会很长。Compose 把这些配置保存在可版本控制的 YAML 中。

- 临时验证单个镜像：`docker run`；
- 启动本项目这种多服务应用：`docker compose`。

## 14. 容器生命周期

```text
Dockerfile
    │ docker compose build
    ▼
镜像
    │ docker compose up
    ▼
运行中的容器
    │ docker compose stop
    ▼
停止但保留的容器 ──docker compose start──> 再次运行

运行中的容器
    │ docker compose down
    ▼
容器被删除；镜像和命名卷默认保留
```

容器、镜像、数据卷是三类独立资源。删除容器不等于删除镜像，更不等于删除数据卷。

## 15. 开发环境与生产环境

当前配置适合本地学习和演示。生产环境还应：

- 使用固定版本标签的镜像；
- 由 CI 构建并推送镜像仓库；
- 使用密钥管理服务；
- 不把数据库直接暴露公网；
- 配置 HTTPS、域名和反向代理；
- 收集日志、指标和链路追踪；
- 限制 CPU 和内存；
- 使用非 root 用户；
- 做数据库备份和恢复演练；
- 准备滚动发布及回滚；
- 扫描镜像漏洞。

本项目 Dockerfile 已采用非 root 用户，这是可以向面试官说明的安全实践。

## 16. 动手练习

### 练习 1：观察生命周期

```bash
docker compose up -d --build gateway
docker compose ps
docker compose logs --tail=30 gateway
curl http://127.0.0.1:8000/health
docker compose down
docker compose ps
```

解释镜像何时产生、容器何时产生、为什么最后 `ps` 为空。

### 练习 2：前台与后台

```bash
docker compose up gateway
```

观察后按 `Ctrl+C`，再尝试：

```bash
docker compose up -d gateway
docker compose logs -f gateway
```

理解两个场景下 `Ctrl+C` 的区别。

### 练习 3：进入容器

```bash
docker compose up -d gateway
docker compose exec gateway sh
```

容器内执行：

```sh
pwd
ls
python --version
id
exit
```

观察目录、Python 版本和非 root 用户。

### 练习 4：验证持久化

在 PostgreSQL 写入测试数据，执行普通 `docker compose down`，重新启动并验证数据仍存在。不要使用 `down -v`。

### 练习 5：理解端口映射

把宿主机端口临时改成 `8001:8000`，预测并验证下面哪个地址成功，之后恢复配置：

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8001/health
```

## 17. 新手安全规则

1. 执行前先确认 `pwd`，避免操作错项目。
2. `down` 默认保留卷；`down -v` 会删除数据。
3. 不理解后果时不要使用带 `-a`、`--volumes` 的 prune。
4. 不提交 `.env` 和 API Key。
5. 容器之间使用服务名通信，不套用宿主机的 localhost 思维。
6. 改代码后先判断是否需要重建镜像。
7. 故障时先看 `ps`、`logs` 和 `config`，不要直接清空资源。
8. 数据库破坏性操作前先备份。
9. 容器在运行不代表业务健康，要检查接口。
10. 生产环境不能原样照搬本地配置。

## 18. 面试表达

可以这样介绍：

> Amazon AI Platform 使用 Docker Compose 交付。FastAPI LLM Gateway 通过 Dockerfile 构建，采用 Python 3.12 slim 基础镜像并使用非 root 用户；PostgreSQL 使用固定大版本 Alpine 镜像，通过命名卷持久化。Compose 负责服务发现、端口映射、环境变量和健康检查。客户端经 8000 端口访问统一网关，容器内部通过 Compose DNS 服务名访问数据库。部署后以 `/health` 验证可用性。

有深度的追问点：

- 镜像和容器为什么要分开理解；
- 数据库为什么必须使用卷；
- 容器之间为什么不能使用 localhost；
- 运行状态和健康状态有什么区别；
- 为什么服务应使用非 root 用户；
- 如何用版本化镜像、健康检查和回滚提高可靠性。

## 19. 一页速记

```text
Dockerfile          = 制作镜像的配方
镜像 Image          = 不运行的只读模板
容器 Container      = 镜像的运行实例
Docker Engine       = 管理容器等资源的后台服务
Docker CLI          = 终端中的 docker 客户端
Colima              = Mac 上承载 Engine 的 Linux 虚拟机
Docker Compose      = 用 YAML 编排多个服务
Gateway             = 本项目统一的 FastAPI/LLM API 入口
8000:8000           = Mac 8000 → 容器 8000
Volume              = 独立于容器生命周期保存数据
Healthcheck         = 判断服务是否真正可用

pull  = 下载远程镜像，不启动
build = 根据 Dockerfile 制作镜像，不启动
up    = 创建并启动服务
stop  = 停止但保留容器
start = 启动保留的容器
down  = 停止并删除容器和网络，默认保留卷
logs  = 查看日志
exec  = 在运行中的容器执行命令
ps    = 查看状态
```

部署：

```bash
cd /Users/cpt/project/aiyy/ecommerce-agent-learning-plan
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 gateway
curl http://127.0.0.1:8000/health
```

结束：

```bash
docker compose down
```

当天完全不再使用 Docker：

```bash
colima stop
```
