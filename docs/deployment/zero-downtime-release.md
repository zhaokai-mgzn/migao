# 零停机发布与集群无感（设计 ADR）

> 裁定出处：用户 2026-11-23 20:39 逐字「**另外要考虑未来做集群部署时如何不影响用户，让用户无感**」；
> 同日 20:43 追加「**磁盘先不用管，未来要考虑做集群的磁盘告警，可以依赖阿里云的能力**」。
> 关联 issue #9084。判据 = `tests/unit_ci_workflows/test_zero_downtime_release_adr.py`（MC-346）。
>
> **本页的增量只有两块**：① **零停机的切换模型**（M1：怎么切、按什么顺序、失败怎么退）；
> ② **单机 → 集群的迁移路径**（M2：每一步的前置与回退点）。
> 代码级取证（P0/P1 清单、进程内状态逐条证据）**不在这里重复** —— 见
> [`cluster-readiness-audit.md`](cluster-readiness-audit.md)；上传存储的落地细节见
> [`upload-storage-and-multi-instance.md`](upload-storage-and-multi-instance.md)。
>
> 时间口径：本页所有读数均为 **Asia/Shanghai（UTC+8）**；引用 CI/云侧时间戳时已注明换算。

---

## 30 秒结论

1. **「无感」不是切换技术问题，是三个问题**：切换窗口（现在有秒级 502 窗口）＋ 在途请求（SSE 最长 180s）
   ＋ 一致性（2026-11-23 发成半截、两天没人发现）。三者缺一，用户就会感知到。
2. **单机（M1）**：把切换动作从「**重建正式容器**」改成「**nginx upstream 摘挂 + reload**」，
   旧容器**先摘流量、等在途请求 drain 完再停**；配套 `graceful shutdown`、`readiness/liveness` 分离、
   SSE `Last-Event-ID` 重连、迁移 expand/contract、发布后**三服务同源自检**。
3. **集群（M2）**：先还技术债（uploads→OSS、redis 外置、定时腿单例锁），再上 SLB + 灰度 + 连接排空，
   路径是「单机 → 双机影子 → 双机灰度 → 下线旧机」，每一跳都有**秒级回退点**。
4. **现在不做**：K8s / 服务网格 / 多机房 / 自建资源监控（资源面交给阿里云云监控）。重启条件逐条写在第 5 节。

---

## 1. 现状（2026-11-23 实测，直接采信）

### 1.1 生产拓扑

| 项 | 现状 | 证据 |
|---|---|---|
| 机器 | 单台 SWAS 轻量 `c0080f77…`（`8.136.134.44`，4C8G，Ubuntu） | 生产实测 |
| 编排 | `/opt/migao-deploy` 下 `docker compose`，项目名 `migao-deploy` | 生产实测 |
| 容器（5） | `admin-api` / `admin-web` / `ai-agent` / `nginx` / `redis` | 生产实测 |
| 仓库定义的 compose 服务（4） | `admin-api` / `ai-agent` / `admin-web` / `nginx` —— **`redis` 不在仓库 compose 里** | `deploy/swas/docker-compose.yml`（服务键只有这 4 个） |
| 数据面 | RDS PostgreSQL（外置） | 生产实测 |
| **redis** | **生产是本机容器**，但**仓库 compose 未定义 redis** ⇒ 它的启动参数、卷、重启策略、版本**没有任何仓库承载**（`docker inspect` 才能回答） | 生产实测 + `deploy/swas/docker-compose.yml` 无 `redis` 服务 |

> ⚠️ 这一条与审计报告的「生产 Redis 是容器还是云实例 = 未证实」**互补**：现在证实了「是本机容器」，
> 但**承载面仍缺**（无仓库定义、无 compose 卷、无升级路径）。M2-a 因此把它列为**必外置项**，
> 并给出「外置前不许开第 2 个实例」的硬前置。

### 1.2 发布机制（`deploy/scripts/swas-deploy-ci.sh` + 主机 `/opt/migao-deploy/deploy.sh`）

**已有的（不要推翻）**：严格蓝绿预验证（issue #4785，`deploy/swas/deploy.sh` 1586-1800）——
先以 `*-green` 容器起在**第二端口**（`18080` / `18000` / `13001`）→ 用**与正式容器同一份** `wait_healthy()`
验证 → 通过才替换正式容器；失败 ⇒ 删 green + `exit 1`，**旧容器一动不动**。
另有迁移失败闸门（#5792）、nginx 上游 200 断言（#8976 ④）、`EFFECTIVE_TAG=<svc>:<tag>` 逐服务生效读数（#4852）。

**缺的（本页要解决的）**：**成功路径的切换动作**。现在写的是
`docker compose up -d --no-deps <svc>`（`deploy/swas/deploy.sh` 1767-1772）——compose 的**替换**语义 =
「停旧 → 删旧 → 建新 → 起新」⇒ 从停旧到新容器 healthy 之间**没有进程在服务**；随后才
`nginx -s reload`（`deploy/swas/deploy.sh` 1977）。健康检查（`start_period: 60s`）意味着这段窗口可以是
**秒级到一分钟级**。为什么当初不切 upstream：`deploy/swas/deploy.sh` 1596-1602 有逐条取舍 ——
「改 nginx.conf 写坏 = 全站所有域名同时挂」，所以先不碰。**本 ADR 认这个判断（它救了 2026-11-21 那次），
但把它作为 M1 要跨过去的一步，并用 `nginx -t` + 单文件 include + 秒级回滚把风险降下来。**

**nginx 现状（事实）**：`deploy/swas/nginx.conf` 里 `proxy_pass http://admin-api:8080`（172/491/516/541/574 行
等多处）、`proxy_pass http://ai-agent:8000`（210/554 行）—— **走 compose DNS 服务名、nginx.conf 没有 upstream 块**
（全文件 `upstream` 出现 0 次）。启动/reload 时解析并缓存 IP ⇒ **重建容器 = 换 IP = 不 reload 就 502**
（实测窗口 90s，`deploy/swas/deploy.sh` 1661-1663 记录了这件事）。

**域名事实（校正一处转述）**：仓库里的 `deploy/swas/nginx.conf` 的 `server_name` 是**测试域**
`*.migaozn.com`；生产域 `cytda.com` 是部署时 `deploy/swas/deploy.sh` 802-845 用
`MIGAO_PUBLIC_DOMAIN`（`.env.site`，缺省 `migaozn.com`）对 `nginx.conf.canonical` 做 `sed` 渲染出来的，
且渲染后**断言 `server_name` 里必须出现站点域**（#8966）。⇒ 读本页时不要以为「仓库 nginx.conf = 生产 nginx.conf」，
判断生产域名要看**渲染产物**（服务器 `nginx/nginx.conf`）。

### 1.3 资源基线（2026-11-23 20:38 实测）

| 读数 | 值 | 与发布的关系 |
|---|---|---|
| 根分区 | 69G / 用 9.8G（15%） | 不紧张；**告警面按 20:43 裁定交给阿里云云监控**（见 M2-d），本页不设计自建磁盘探针 |
| Docker 镜像 | 6.55GB（其中 3.80GB 可回收） | **清理必须与回滚点保留一起设计**：复用 `deploy.sh` 的既有保留策略（当前在用 + `.last-good-tag` 回滚点 + 最近 `KEEP_RECENT_TAGS` 个，`deploy/swas/deploy.sh` 309-322 / 505-537；深度清理只发 `docker builder prune`，结构上碰不到镜像与回滚点），**不要另起一套清理器** |
| 内存 | 7.1Gi 总 / 用 1.5Gi | 蓝绿并存需要 `max(1536) + 512 = 2048MB` 余量（`deploy/swas/deploy.sh` 1612-1613）⇒ 当前够；**但 Swap = 0** ⇒ 峰值内存没有缓冲，green 起不来时是 OOM 而不是变慢 |
| **Swap** | **0** | 发布期同时跑两份容器是内存峰值时刻；M2 扩实例前必须先有内存告警（云监控） |
| 负载 | 0.16 | 空闲；当前单机余量足够做「双容器并存」 |

### 1.4 2026-11-23 的事故形态（本页存在的直接理由）

11:32–11:39 有人**手工**在主机上跑 `deploy.sh`：结果只更新了 `admin-api`（`sha-26ff9f7`），
`admin-web` 仍是 11-21 的 `sha-caf01e4` ⇒ **发成半截**，两天没人发现。
⇒ **结论：切换做得再平滑，没有「发完必须三服务同源」的自检，用户照样会看到一个新旧混合的系统**
（前端调新后端 / 新后端配旧前端）。M1-f 是**优先级最高、依赖最少**的一项 —— 它今天就能上，不需要等 M1-a。

### 1.5 已有积累（复用，不重造）

| 积累 | 用在哪 |
|---|---|
| 严格蓝绿预验证（#4785） | M1-a 的「新容器先起 + 同一份健康判据」直接沿用，只换**切换动作** |
| `served-version-verify.sh`（`/api/version` 三态 0/1/3） | M1-f 的单服务身份判据 |
| `EFFECTIVE_TAG=<svc>:<tag>`（#4852） | M1-f 的「逐服务实际生效 tag」读数来源 |
| JWT 同源密钥（#8976 / PR #9055、`public.pem` 物化） | M2-a「会话无状态」已成立的那一半 |
| 回滚点保留（#4808）、`report_rollback_point` | M1-a 的回退点、M2-e 的每一跳回退点 |
| 集群就绪度审计（`cluster-readiness-audit.md`） | M2-a 的 P0 清单与修法（本页只排**顺序与前置**） |
| 上传存储文档（`upload-storage-and-multi-instance.md`） | M2-a 的 uploads 外置（`MIGAO_REPLICAS` fail-close + OSS 切换 + 迁移脚本） |

---

## 2. 缺口清单（按「阻断什么」排，不按代码位置排）

| # | 缺口 | 现在会发生什么 | 归属 |
|---|---|---|---|
| G1 | 切换动作 = 重建正式容器 | 成功路径仍有「无进程服务」窗口（秒级～分钟级）；SSE 必断 | M1-a |
| G2 | 应用没有 graceful shutdown，compose 也没有 `stop_grace_period` | `SIGTERM` 后默认 10s 就被 SIGKILL；Spring 在途请求 / uvicorn 在途 SSE 被硬切 | M1-b |
| G3 | 健康判据只有聚合面（admin-api `/actuator/health`；ai-agent `/ready`），**没有 readiness/liveness 分离** | 「进程活着但依赖不通」与「进程该重启」混在一个信号里；LB 只能整机摘或整机不摘 | M1-c |
| G4 | SSE 断流后客户端**没有断点续传语义**（仓内没有 `Last-Event-ID` 实现） | 切换/重启时用户看到「回答说到一半没了」，且历史里可能只剩用户那句 | M1-d |
| G5 | 迁移与发版**同一批**：`MigrationRunner` 是启动期 `CommandLineRunner` | 破坏性 DDL 与新代码同批上线 ⇒ 回滚窗口被 schema 卡死；单条失败只跳过、不参与健康判定（#5792 只兜住「ERROR 形态」） | M1-e |
| G6 | 发布后**没有三服务同源自检**（今天的事故） | 半截发布可以全绿两天 | M1-f |
| G7 | uploads 落宿主本地盘（`/opt/migao-deploy/uploads:/app/uploads`）；redis 是本机容器且无仓库承载 | 第 2 个实例 = 图片 404 / 验证码验不过 / 登出不生效 | M2-a |
| G8 | 无 SLB、无灰度权重、无连接排空；定时腿多实例重复（审计 P0-2 已修，其余靠原子语句） | 扩机器只能靠 DNS 切，切换瞬间两机房/两台同时在服务但没有权重控制 | M2-b / M2-c |
| G9 | 「无感」没有判据面（没有 5xx / 502 / 版本一致性 / 每实例成功率读数） | 掉了请求也没人知道，只能等用户报 | M2-d |

---

## 3. M1 · 单机零停机（目标：发版期间**零失败请求**）

**「零失败请求」的定义（可判、不是口号）**：
① 发布窗口内，入口 `5xx` 计数 = **0**（按 nginx access log 的 `status` 统计，排除压测/主动 4xx）；
② SSE 断流后**没有丢失已生成内容**（客户端重连能续上，或历史里有明确中断标记）；
③ 发布窗口内**没有**「容器已停、上游未切」的空窗（用 nginx 上游断言 + 逐秒探活证明）；
④ 发布结束后三服务 `EFFECTIVE_TAG` 与入口自报 sha **同源一致**。

落地顺序（依赖关系即安全顺序）：**M1-f → M1-a → M1-b/M1-c → M1-d → M1-e**。
M1-f 今天就能做（不需要动 nginx）；M1-b/c 只有在 M1-a 落地后才有意义（否则「优雅退出」退的是马上要消失的容器）。

### M1-a 切换模型：nginx **upstream 摘挂**，而不是「重建正式容器」

**现状前提（事实，详见 §1.2）**：`deploy/swas/nginx.conf` 里 `proxy_pass http://admin-api:8080` 走 compose DNS
服务名、**nginx.conf 没有 upstream 块**（全文件 0 次）⇒ 重建容器换 IP 就必须 reload 才不 502（实测 90s）。
本项要做的正是**新建** upstream 成员文件（不是改造已有 upstream）。

**目标形态**（要点，不是完整 patch；实际落地是独立包，需评审）：

1. `deploy/swas/nginx.conf` 里把 `proxy_pass http://admin-api:8080` / `http://ai-agent:8000` 改成
   **upstream 名**（如 `proxy_pass http://admin_api;`），upstream 定义抽到**单独一个 include 文件**
   （例如 `conf.d/upstream.migao.conf`），**其余 server/location 一字不动**——这是把「改 nginx.conf 可能全站挂」
   的爆炸半径压到「一个只有 3 行成员的文件」。
2. 成员写成**容器名:容器内端口**：`admin-api-blue:8080` / `admin-api-green:8080` /
   `ai-agent-blue:8000`；**不要写宿主第二端口**（`18080` / `18000` / `13001` 只是宿主侧探针端口，
   nginx 容器与它们在同一个 compose 网络里，直接走容器内 8080/8000）。
3. 切流量 = **改 include 文件 + `nginx -t` + `nginx -s reload`**；reload 是优雅的：旧 worker 继续把
   **在途请求**做完再退（配合 M1-b 的 `worker_shutdown_timeout`，见下）。
4. 新容器 healthy 之前**不进 upstream**；进入后先用 `proxy_next_upstream` 兜住极短的竞态（可选）。
5. 回退 = 把 include 文件换回上一份 + reload（**秒级**，不重建任何容器）—— 比现在的「重建旧镜像」快一个量级。

**顺序（顺序即安全顺序，逐步可停）**：

| # | 动作 | 失败时的样子 / 处置 |
|---|---|---|
| 1 | 备份当前 include（`.bak-<时间>`）并 `nginx -t` 基线自检 | 基线不通过 ⇒ **停**（说明当前入口配置本身有问题） |
| 2 | 起 `*-green`（同镜像/env/卷，第二端口 `18080` / `18000` / `13001`），`wait_healthy` + 迁移闸门 | 失败 ⇒ 删 green、**upstream 未动**、旧容器继续服务（现有 #4785 语义） |
| 3 | 写新 include（成员切到 green）→ `nginx -t` | `-t` 失败 ⇒ 恢复 `.bak`、**不 reload**、删 green（entry 未受影响） |
| 4 | `nginx -s reload`（**摘旧**：新连接只进 green；旧 worker 继续手里的请求） | reload 失败 ⇒ 恢复 `.bak` 再 reload；仍失败 ⇒ 保留旧 worker（不 restart） |
| 5 | 逐秒探活 `https://<站点域>/api/version` **并核对 sha**（不是只看 200） | 读数不是新 sha ⇒ 回退 include + reload（旧容器还在） |
| 6 | **等 drain**：等到「旧容器的在途请求」结束（>= SSE 最长流时长，见 M1-d；用 `worker_shutdown_timeout` 兜底） | 提前停 = 断流；宁可多等 |
| 7 | `docker compose stop`（不是 `up -d`）旧容器 → `rm` → 下一轮角色互换 | 停旧后才发现问题 ⇒ 回退 include 到 green（此时 green 已是唯一健康面），再起旧镜像 |
| 8 | 三服务同源自检（M1-f）+ 一致性读数入日志 | 不一致 ⇒ 判定「半截发布」，**当场补发或回退**，不许绿 |

**代价**：① 改的是流量入口（历史上最危险的改动面）⇒ 用「单文件 include + `nginx -t` + 备份 + 秒级回退」四道锁，
且**先在一台测试机演练一次**再上生产；② 发布期同时存在两份容器（内存峰值 +1 份，当前余量够，Swap=0 需注意）；
③ `nginx:alpine` 需支持 `worker_shutdown_timeout`（1.11.11+；落地前用 `docker exec nginx nginx -V` 自证版本）。

**判据**：① 灰度发布窗口内 `5xx = 0`；② 切换前后 `/api/version` 的 sha 从旧变新且**无 000/502 读数**；
③ 回退演练：把 include 换回上一份 ⇒ 30 秒内入口恢复旧 sha（记录耗时）；④ `nginx -t` 失败注入 ⇒ 不改入口。
**谁来做**：**包**（改 compose/nginx.conf/upstream include + `deploy.sh` 切换段 + 判据），评审后**人**在测试机演练一次。

### M1-b 应用优雅退出（Spring Boot / uvicorn）

| 侧 | 目标配置 | 当前是否已配置 |
|---|---|---|
| admin-api（Spring Boot **3.5.16**） | `server.shutdown=graceful` + `spring.lifecycle.timeout-per-shutdown-phase=30s` | **未配置**（`backend/admin-api/src/main/resources/application.yml` 全文没有 `shutdown` / `lifecycle` 键；Boot 3.5 原生支持，只差这两行） |
| ai-agent（uvicorn **0.54.0**） | `--timeout-graceful-shutdown 200`（>= SSE 最长流时长） | **未配置**（`backend/ai-agent-service/Dockerfile:76` 的 CMD 只有 `--workers 1 --timeout-keep-alive 65`） |
| compose（两侧） | `stop_grace_period`（>= 应用的优雅退出预算；**docker 默认只有 10s**） | **未配置**（`deploy/swas/docker-compose.yml` 与 `docker-compose.bluegreen.yml` 里 `stop_grace_period` 出现 0 次） |

⚠️ **「配置了」≠「生效了」**：`docker compose stop` 默认 10s 后 `SIGKILL` ⇒ 应用配 30s 也只会被砍在 10s。
三处必须**同时**配（应用 + compose + 编排脚本用 `stop` 而非 `kill`），且发布期用一个**长请求**实测：
发一个 ≥60s 的 SSE，在流未结束时切换 ⇒ 流必须自然收尾（不是断流），日志里出现 graceful 字样。

**代价**：低（配置面）；风险是「退出变慢」⇒ 部署总时长增加（可接受，用并发/超时兜底）。
**判据**：① 配置存在且 CI 判据钉住（未配置即红——本页的判据文件已经把「**当前未配置**」这个事实钉住，
配置一改就必须同步改文档，否则判红）；② 长请求实测：切换期 SSE 完整收尾；③ 超过 `stop_grace_period` 仍不退
⇒ 记 ERROR（这是「优雅退出没生效」，不是正常路径）。
**谁来做**：**包**（配置 + compose + 判据 + 演练脚本）；**人**只做一次「真发一版看长请求」。

### M1-c 就绪 / 存活分离（readiness vs liveness）

| 服务 | 现在探什么 | 目标 |
|---|---|---|
| admin-api | compose healthcheck 与 `wait_healthy` 都探**聚合** `/actuator/health`（`deploy/swas/docker-compose.yml:74`） | 开 `management.endpoint.health.probes.enabled=true` ⇒ `/actuator/health/readiness`（依赖：DB/Redis/存储自检）+ `/actuator/health/liveness`（只判进程该不该重启）；**nginx/SLB 只按 readiness 摘挂** |
| ai-agent | `/ready`（DB + Redis，`backend/ai-agent-service/app/main.py:218`）与 `/health` | 保持 `/ready` 作为 readiness；把 `/health` 明确为 liveness（只判进程），**不要把供应商健康塞进 readiness**（`backend/ai-agent-service/app/main.py:235-236` 已记录这条口径） |
| nginx | `/healthz`（自身进程） | 不变：nginx 不参与上游健康判断（它是入口，不是 LB） |

**注意**：readiness **不通过**时应当「摘流量但不重启」，liveness 不通过才「重启」；当前没有 autoheal，
所以 liveness 目前只是**读数**（别写成「会自动重启」）。
**代价**：低（admin-api 一行配置 + 探针路径切换）；**判据**：① 停掉 DB 连接（或注入 readiness 探针失败）⇒
readiness 变 DOWN、liveness 仍 UP，且**入口摘掉该实例**（M1 单机就是摘到另一色）；② 反向：liveness 注入失败 ⇒
readiness 不受影响（防止两条线互相污染）。
**谁来做**：**包**。

### M1-d SSE / 流式（AI 对话）

现状事实：SSE 单条请求绑定一个实例（`backend/ai-agent-service/app/api/chat.py:314-315`：`stream_timeout=180`、
`heartbeat_interval=15`）；生产代码（`backend/`、`frontend/`）里**没有** `Last-Event-ID` 实现（检索 0 命中）⇒ 断流后只能整轮重发，
而重发的幂等键目前**不是确定性键**（审计 P0-4）⇒ 重发可能重复下单。

**设计（两层，先做第一层）**：

1. **发布期 drain（M1-a 的第 6 步）**：旧 worker 必须活到最长流时长（180s）+ 心跳余量；
   nginx 配 `worker_shutdown_timeout 200s;`（超时兜底），uvicorn `--timeout-graceful-shutdown 200`。
   这一层不依赖客户端改造，**先把「切换」这个诱因消掉**。
2. **客户端断点续传（后续包）**：服务端给每个 `event:` 带 `id:`（递增序号），断线后浏览器 `EventSource`
   自动带 `Last-Event-ID` 重连；服务端按 id 从「已生成内容缓冲」续发，续不上则发一条明确的
   「（本次回复中断）」事件并落库（审计 P1-2 的修法）。⚠️ 这一层依赖「回复增量落库」，属另一个包，
   本页只定**语义**：**断流要么续上，要么在历史里可归因，不许静默消失**。
**代价**：第一层=配置（低）；第二层=改 chat.py + 前端 EventSource 接线 + 幂等键（中，且与审计 P0-4 同批）。
**判据**：第一层 = 切换期长流自然收尾（M1-b 的实测同款）；第二层 = 流中断后 `Last-Event-ID` 重连能续上，
或历史里出现「中断」标记（`GET` 历史可验证）。**谁来做**：第一层**包**；第二层**包**（需单独立项，见第 7 节）。

### M1-e DB 迁移：**expand / contract**，且**不得与发版同批**

现状事实（审计 P1-1 + 代码）：迁移是启动期 `CommandLineRunner`（`MigrationRunner`）自动跑，
「查台账 → 执行 → 记录」三步读改写、无分布式锁；单条失败**只记 ERROR、不阻断启动**（#5792 的闸门只认
`❌ 迁移失败` 形态）。⇒ **今天「发版」与「改 schema」在物理上是同一批**，回滚镜像时 schema 已经变了。

**规则（四条，按顺序）**：

1. **expand 先上**（只加列/加表/加索引，全部可空或带默认；`CREATE INDEX CONCURRENTLY` 走非事务腿）；
2. **双写/回填**（新老代码都能读旧列；回填用一次性脚本，幂等、可中断、按批次）；
3. **切读**（代码只读新列/新表；旧列保留一个观察期 —— 建议 >= 7 天，且**不早于**下一次发布）；
4. **contract 延后**（删旧列/改约束单独一次发布，且必须是「确认无读方」之后；`DROP` 永不与功能同批）。

**发布顺序与「不同批」的机械定义**：一次 `cut-release` 里**只允许**出现 expand 类迁移；
出现 `DROP` / `ALTER TYPE` / `SET NOT NULL` / 重命名 的迁移必须**单独一次发布**，且该次发布**只含迁移**（可用
`cut-release` 的提交清单 + 迁移文件 diff 做静态判据）。⚠️ 落地形态需要把迁移从「启动期自动跑」拆成
**显式迁移阶段**（发布前置 job：`deploy.sh --migrate-only` 或独立一步），否则「不同批」在物理上做不到。
**代价**：中高（改发布腿 + 迁移器语义 + 每次发布多一个阶段）；**判据**：① 任意一次发布的迁移集里
`DROP|ALTER.*TYPE|SET NOT NULL` 计数 = 0（否则判红）；② 回滚演练：回滚镜像后，**旧代码在 expand 后的 schema 上能跑**
（这是 expand 的全部意义）；③ `schema_migrations` 台账无重复、迁移失败读数（`/api/version/migrations`）= 0。
**谁来做**：**包**（拆迁移阶段 + 静态判据）；**人**只裁「哪些 DDL 算破坏性」（口径题）。

### M1-f 一致性自检：发布后**三服务必须同源同 sha**

**这是本页的第一优先级**（今天的事故就是它）。判据面（三段，互补）：

1. **逐服务在跑镜像 tag**（权威 = 容器，不是日志）：
   ```bash
   cd /opt/migao-deploy
   for s in admin-api ai-agent admin-web; do
     cid=$(docker compose ps -q "$s")
     printf '%-10s %s\n' "$s" "$(docker inspect --format '{{.Config.Image}}' "$cid")"
   done
   ```
2. **部署日志的生效行**（#4852 的契约，`deploy/scripts/swas-deploy-ci.sh` 解析后落 step summary）：
   ```bash
   grep -o 'EFFECTIVE_TAG=[^ ]*' <本次部署日志>
   # 期望三行且 tag 全等：admin-api:sha-<7> ai-agent:sha-<7> admin-web:sha-<7>
   ```
3. **入口自报身份**（**同源**的线上侧证据）：
   ```bash
   curl -s https://api.<站点域>/api/version    | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["app"],d["sha"])'
   curl -s https://ai-api.<站点域>/api/version | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["app"],d["sha"])'
   ```
   生产域是 `cytda.com`（渲染后，见 1.2）；期望两处 sha == `git rev-parse origin/release` 前 7 位。
   admin-web **没有**构建身份端点 ⇒ 它的身份只由第 1/2 段承担（**如实登记，不假装覆盖**）。

**机械判据（一条命令，三元退出）**：三服务 tag 两两相等且 == 期望 tag ⇒ `0`；不等 ⇒ `1` 并**点名哪两个服务不一致 +
给出上面三条复算命令**；探不到（容器没起 / 日志无 `EFFECTIVE_TAG` / 端点非 200）⇒ `3`（fail-closed，不许当 0）。
**落地位置**：`deploy.sh` 末尾（部署成功前）+ CI 的 deploy 腿（`Post-Deploy` 段），两处**共用同一份实现**
（不要在后端与 CI 各写一套 —— 那是第二把尺子）。
**代价**：低（只读）；**判据**：本判据自己的注入式红证 = 把某个服务的 tag 改一个字符 ⇒ 退 1 且点名；
删掉 `EFFECTIVE_TAG` 输出 ⇒ 退 3（不是 0）。**谁来做**：**包**。

---

## 4. M2 · 集群无感（目标：加机器 / 滚动升级不掉请求）

前置原则：**M2 的每一项都是「开第 2 个实例」的前置，不是「扩容之后再说」的事**。顺序 = 债务 → 入口 → 数据面 → 观测 → 迁移。

### M2-a 无状态化清单（逐项：现状 / 目标 / 判据）

| 面 | 现状（证据） | 目标 | 判据 |
|---|---|---|---|
| **uploads** | 宿主本地目录 `/opt/migao-deploy/uploads` 挂到 `/app/uploads`（`deploy/swas/docker-compose.yml:60-62`）；`LocalFileStorageService` 写 `uploads/`，`WebConfig` 以 `file:uploads/` 暴露 | 切 `OssService`（三项凭据齐备即 `@Primary`，不改代码）；本地静态面降级为**遗留文件只读** | 两实例各传一张 → 互相 `GET` 均 200；杀 A 后 B 仍能取到 A 上传的图。落地细节见 `upload-storage-and-multi-instance.md`（含迁移脚本与 `MIGAO_REPLICAS` fail-close） |
| **redis** | **本机容器**（生产实测），且**仓库 compose 未定义 redis**（`deploy/swas/docker-compose.yml` 只有 4 个服务） | 外置**共享实例**（Tair/云 Redis），**全实例单写主**；黑名单/验证码/OTP 必须读主（审计 P1-3） | A 发验证码、B 校验通过；A 登出后 B 立刻 401；`docker compose ps` 里不再有 redis |
| **会话** | 已无状态：JWT 同源密钥（宿主 `public.pem` 物化，compose 两侧同卷；#8976）＋ `session_states` 在 PG（`context_manager` / `session_state_store`） | 保持；**不要**为了 SSE 加 sticky（单条流本就绑实例，切换靠 drain） | 同一 token 打两台实例均 200；跨实例连续两轮会话上下文不丢 |
| **定时 / 异步任务** | 审计 P0-2 已修（原子 claim / `dedupeKey`）；其余四条靠原子 UPDATE 裁行；`MigrationRunner` 无锁（P1-1） | 每条腿**单例锁**：DB 原子语句优先（`UPDATE … RETURNING`），跨实例长任务用 `pg_advisory_lock`（仓内已有先例）或 Redis 租约（`AgentBatchLeaseService` 先例） | 两实例同时跑一轮扫描：副作用行数 == 到期数（不是 2 倍）；`schema_migrations` 无重复 |

**⚠️ 硬门槛**：uploads 未切 OSS 或 redis 未外置 ⇒ **不许开第 2 个实例**（`StorageDeploymentSelfCheck` 对
`MIGAO_REPLICAS > 1` + 缺 OSS 已经 fail-close，但 Redis 没有同类护栏 ⇒ 建议同批补一条启动自检，
否则「忘了外置 redis」没有任何东西会红）。

### M2-b 前置：SLB / 健康检查 / 灰度权重 / 连接排空

- **SLB/ALB**：入口从「单机 nginx」换成「ALB → 后端实例（或每实例 nginx）」；健康检查路径 =
  **readiness**（M1-c），不是 `/`，也不是聚合 health。
- **灰度权重**：先按**实例**灰度（5% → 50% → 100%），不是按用户；权重切换是秒级动作，回退 = 权重归零。
- **连接排空（connection-drain）**：摘实例前先 `connection-drain`（等待在途请求；SSE 必须 >= 180s），
  再 deregister。⚠️ 阿里云 SLB/ALB 的具体开关名与超时上限**以控制台/文档为准（待核对）**，本页只定语义：
  **「先摘新连接 → 等在途结束 → 再下线」**，顺序不许反。
- **同机蓝绿 vs 跨机灰度**：同机第二端口那套（`18080` / `18000` / `13001`）只用于**单机内**预验证；
  跨机切换走 SLB 权重。两者不混用。

**代价**：中（云资源 + 控制台配置 + 一次演练）；**判据**：灰度 5% 期间，旧实例 5xx = 0、新实例成功率 == 旧实例
（±1%），回退演练 < 30s。**谁来做**：**人**（云侧开通与权重操作）+ **包**（实例侧 readiness/drain 接线）。

### M2-c 数据面：连接池算式模板（**上第 2 个实例前必须算**）

现状（代码事实）：admin-api Hikari `maximum-pool-size: 20`（`backend/admin-api/src/main/resources/application.yml:52-57`）；
ai-agent asyncpg `pool_size=20` + `max_overflow=10`（`backend/ai-agent-service/app/utils/database.py:39-40`）。

**算式模板**（把读数填进去，不要背数字）：

```
预算上限 = RDS max_connections × 0.8            # 留 20% 给迁移/运维/临时连接
已用     = Σ_服务 (pool_max × 实例数) + 预留
  admin-api：20 × N_admin
  ai-agent ：(20 + 10) × N_agent
要求     = 已用 + 预留(≈20) ≤ 预算上限
```

**当前未证实项**：RDS 的 `max_connections` 实际值（仓内无读数）⇒ 上集群前必须先 `SELECT setting FROM pg_settings
WHERE name='max_connections';`。若算式不成立：① 降 `pool_max`（首选，单实例并发不需要 20）；② 上 PgBouncer
（transaction 模式，注意 prepared statement 兼容）；③ 升 RDS 规格。**判据**：压测时 `pg_stat_activity` 的连接数
峰值 ≤ 预算上限、且无 `too many connections`。**代价**：低（配置）到中（PgBouncer）；**谁来做**：**包**（算 + 配置）+
**人**（RDS 规格/参数组，需云侧权限）。

### M2-d 观测：把「无感」变成读数（资源面 = 阿里云云监控，业务面 = 自建）

**业务面（自建，本仓已有承载体）**：每实例 `/api/version`（admin-api）/`/api/version`（ai-agent）逐实例身份；
请求成功率 / p99 延迟 / **502 率**（nginx access log 或云监控入口指标）；发布窗口内 `5xx = 0` 是「无感」的
**判据来源**，不是「发完看一眼」。判据落点：发布脚本末尾打印「窗口内 5xx 计数 + 三服务同源结论」，
非 0 即判红。

**资源面（按 20:43 裁定：交给阿里云云监控，不自建采集）**：

| 项 | 口径 |
|---|---|
| 采集 | 阿里云云监控（CloudMonitor）对 SWAS/ECS 的**开箱指标**：磁盘使用率、内存使用率、TCP 连接数等；**不自建采集**（集群后每台都要采 ⇒ 自建 = 又一套要维护的 piping，而云平台已经在采同一批数据） |
| **指标名** | **待核对**：以云监控控制台「主机监控 → 指标列表」（OS 级别监控）为准；核对结果回填本表后才算交付。**本页不编指标名**（写错指标名 = 告警永远不触发，比没有告警更糟） |
| 阈值 / 通知渠道 | **配置项，不是代码**：阈值、连续 N 个周期、通知联系人/钉钉/邮件都在云监控侧配置；仓库只登记「用了哪几条规则」的清单（后续包） |
| 磁盘（含镜像） | 本页**先不做**（20:43 裁定）；但**镜像清理策略必须与回滚点保留一起设计**：复用 `deploy.sh` 的既有保留策略（当前在用 + `.last-good-tag` 回滚点 + 最近 `KEEP_RECENT_TAGS` 个；深度清理只发 `docker builder prune`），**不另起一套清理器**；未来告警走云监控的磁盘使用率一类指标（**指标名待核对**，见下） |
| 重启条件 | 当云监控覆盖不到我们需要判据的**业务面**（如「三服务版本同源」「发布窗口 5xx=0」「重复下单」）⇒ 业务面自建、资源面继续用云监控 —— **两条线不混**，也不互相替代 |

**代价**：资源面 = 云侧配置（低，**人**）；业务面 = 发布脚本 + 少量只读端点（**包**，低）。
**判据**：发布演练时人为注入一个 502（停一个上游）⇒ 业务面判据**当场红**；云监控侧注入一次阈值（临时把 CPU 阈值
调到当前值以下）⇒ 通知**真的收到**（否则「配了但没通」= 假绿）。

### M2-e 迁移路径：单机 → 双机影子 → 双机灰度 → 下线旧机（每步有回退点）

| 阶段 | 做什么 | 准入（前置全部满足才进） | **回退点** |
|---|---|---|---|
| **S0 单机**（现在） | M1 全部 + M2-a 债务清完 | M1-f 判据上线、graceful/readiness 生效、三服务同源自检绿 | `cut-release` 回上一 tag（现有回滚点 #4808） |
| **S1 双机影子** | 第 2 台起同一 tag，**权重 0**（不进流量）；只跑只读/健康探测 | uploads→OSS、redis 外置、`MIGAO_REPLICAS=2`、连接池算式成立、单例锁逐腿核过 | 直接把第 2 台权重保持 0 并销毁（对用户零影响；此时它本来就没接流量） |
| **S2 双机灰度** | SLB 权重 5% → 50% → 100%；每档观察 >= 30min（含一次发布窗口） | S1 影子观察 24h：`client_request_keys` 无同内容双行、`orders` 无同手机号同 SKU 重复、两实例版本同源 | **权重归零**（秒级）；旧机仍在服务 |
| **S3 下线旧机** | 先 `connection-drain`（>= 180s）→ 摘 SLB → 停容器 → 保留镜像/tag 作回退点 | S2 在 100% 权重下稳定 >= 24h，且发布演练一次（滚动升级不掉请求） | 旧机重新注册回 SLB（镜像还在；DNS/TTL 未变） |

**⚠️ 数据面不能跟着扩**：RDS 仍是**单写主**（多机房/多主不在本期）。集群 = 应用层多实例，**不是**数据库多活。

---

## 5. 取舍与「现在不做」（含重启条件）

| 不做 | 为什么现在不做 | 重启条件 |
|---|---|---|
| **K8s / 容器编排平台** | 2 个实例、4 个服务、单机房 —— 现在上没有收益，只有「又一套要懂的东西」；`deploy.sh` 的蓝绿/回滚/迁移闸门已解决「部署失败」的主风险 | 服务数 × 实例数 > 6，或需要自动扩缩容 / 自愈 / 多环境隔离 |
| **服务网格（Istio 等）** | 没有 mTLS / 细粒度流量治理 / 多语言 sidecar 的需求；nginx + SLB 权重够用 | 需要按请求级灰度（按用户/租户分流）、或服务间强身份认证 |
| **多机房 / 异地多活** | 跨机房写同一 RDS 会放大锁持有时间（审计「多机房特有」节），收益（延迟）当前用户感知不到 | 客户分布跨区且延迟成为投诉项；或需要机房级容灾（RTO/RPO 有明确口径） |
| **自建资源监控 / 自建磁盘告警** | 20:43 裁定：依赖阿里云云监控；自建 = 重复采集 + 又一套维护面 | 云监控覆盖不到的**业务面**判据（版本同源、5xx 窗口、重复下单）—— 这类**自建**，资源面继续用云 |
| **nginx 动态服务发现（`resolver` + 变量 `proxy_pass`）** | 静态 upstream + reload 已能秒级切换；变量形态会牺牲 keepalive 且更难验证 | 实例数 > 3 且频繁扩缩容（每次扩缩都要改 include 才划算） |
| **同机多副本（`deploy.replicas`）** | 单机 4C8G 内存余量只够「蓝绿并存」；同机多副本没有容灾意义（机器挂了全挂） | 机器规格升级到能容 N+1，且只是为「发布不中断」而非容灾 |
| **SSE sticky session** | 单条流本就绑实例；切换靠 drain（M1-d 第一层），不需要 sticky | 若未来做「每轮对话跨实例续流」再评估（成本高） |

---

## 6. 动作台账（代价 / 判据 / 谁来做）

| 项 | 动作 | 代价 | 判据（会红） | 谁来做 |
|---|---|---|---|---|
| M1-f | 三服务同源自检（`EFFECTIVE_TAG` + 容器 tag + `/api/version`） | 低（只读） | 注入 tag 漂移 ⇒ 退 1 点名；无读数 ⇒ 退 3 | 包 |
| M1-a | nginx upstream 摘挂 + include 切换 + 顺序（摘旧→drain→停旧） | 中高（改入口；四道锁） | `nginx -t` 失败不改入口；切换窗口 5xx=0；回退 < 30s | 包（人演练一次） |
| M1-b | `server.shutdown=graceful` / `--timeout-graceful-shutdown` / `stop_grace_period` | 低 | 配置缺失即红；长流实测完整收尾 | 包（人发一版长请求） |
| M1-c | readiness/liveness 分离，入口只按 readiness 摘挂 | 低 | readiness 注入失败 ⇒ 摘流量不重启；liveness 不污染 readiness | 包 |
| M1-d | drain + `Last-Event-ID` 续流语义 | 低（第一层）/中（第二层） | 切换期长流自然收尾；断流可续或可归因 | 包 |
| M1-e | 迁移 expand/contract + 不得与发版同批 | 中高（改发布腿） | 破坏性 DDL 与功能同批 ⇒ 红；回滚后旧代码可在新 schema 跑 | 包（人口径裁定） |
| M2-a | uploads→OSS / redis 外置 / 单例锁 | 中（云资源 + 代码） | 两实例互读图 200；跨实例验证码/登出正确 | 人（开销）+ 包（接线） |
| M2-b | SLB + 健康检查 + 灰度 + connection-drain | 中（云资源 + 演练） | 灰度 5%：旧实例 5xx=0；回退 < 30s | 人（云侧）+ 包 |
| M2-c | 连接池算式 + RDS 上限核对 | 低（算） | 压测 `pg_stat_activity` 峰值 ≤ 预算 | 包（算）+ 人（云参数） |
| M2-d | 业务面读数 + 云监控资源告警 | 低 | 注入 502 ⇒ 业务判据红；云监控通知真到达 | 人（云规则）+ 包（业务面） |
| M2-e | 单机→影子→灰度→下线 | 中（机器 + 演练时间） | 每步回退点可执行且 < 30s | 人 + 包 |

---

## 7. 未固化 / 未证实（照实登记，不粉饰）

| 项 | 现状 | 核实方式 / 出口 |
|---|---|---|
| 生产 admin-api **是否已优雅退出** | 仓内**未配置**（`application.yml` 无 `server.shutdown`）；生产 `.env.admin-api` 是否会注入 `SERVER_SHUTDOWN` 等覆盖 = **未证实** | `docker compose exec -T admin-api printenv | grep -iE 'SHUTDOWN|LIFECYCLE'` |
| ai-agent graceful 退出参数 | 仓内 CMD **未配置** `--timeout-graceful-shutdown`；uvicorn 0.54.0 支持该参数 | `docker inspect <cid> --format '{{.Config.Cmd}}'` |
| compose `stop_grace_period` | **未配置**（默认 10s ⇒ 会砍在应用优雅退出之前） | `docker inspect` 的 `StopTimeout` / compose 文件 |
| 生产 redis 的启动参数 / 版本 / 卷 | **无仓库承载**（compose 未定义）；只知是**本机容器** | `docker inspect $(docker compose ps -q redis 2>/dev/null || docker ps -q -f name=redis)`；确认有无持久化卷 |
| 生产是否已启用 OSS | **未证实**（凭据在 `.env.admin-api`） | 见 `upload-storage-and-multi-instance.md` §2/§4：`GET /api/version/storage`，或 `printenv | grep '^OSS_'`（只看键） |
| RDS `max_connections` | **未证实**（仓内无读数） | `SELECT setting FROM pg_settings WHERE name='max_connections';` |
| 阿里云云监控**指标名** | **待核对**（本页不编指标名） | 云监控控制台「主机监控 → 指标列表」逐项核对后回填 M2-d；或云监控 API 文档 |
| SLB/ALB 连接排空的**开关名与上限** | **待核对** | 控制台「监听 → 连接优雅中断」/ 文档；本页只定语义顺序 |
| SSE `Last-Event-ID` 续流 | **未实现**（生产代码 `backend/`、`frontend/` 检索 0 命中） | 需单独立项（依赖增量落库 + 幂等键，见审计 P0-4）；本页只定语义 |
| admin-web 构建身份 | **无端点** ⇒ 同源自检对 admin-web 只到「镜像 tag」层 | 若要补：加一个静态 `version.json` 烘进镜像（后续包） |
| nginx `worker_shutdown_timeout` 可用性 | `nginx:alpine` 版本未登记 | `docker exec <nginx> nginx -V`（>= 1.11.11 即支持）；旧版本回退 = 停旧前**睡满** 200s |
| M1 的真实演练 | 本页是**设计**，未在生产演练 | 落地包必须在测试机演练一次「切换 + 回退」，记录耗时与 5xx 读数 |

---

## 附：本页的判据（防「文档空话」）

- 判据文件：`tests/unit_ci_workflows/test_zero_downtime_release_adr.py`（`# case_ids: MC-346`）。
- 它锁三件事：① M1 六项 / M2 五项关键字必须在**各自小节**里（删任一项 ⇒ 判红并点名）；
  ② 本页的**事实性断言**必须与仓内真实配置一致（`18080` / `18000` / `13001`、
  `proxy_pass http://admin-api:8080`、`/opt/migao-deploy/uploads`、redis 本机容器且 compose 未定义、
  graceful「未配置」）⇒ 配置一改，文档不同步就红；
  ③ 注入式红证：删 M1 任一项 ⇒ 红；把 `18080` 改成 `18081` ⇒ 红。
- 用例登记：`.github/cases/misc.yml` 的 `MC-346`（QA Growth Gate 的 G5 追溯要求声明号存在于用例库）。
