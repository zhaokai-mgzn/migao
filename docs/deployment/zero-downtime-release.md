# 零停机发布与集群无感（设计 ADR）

> 裁定出处：用户 2026-11-23 20:39 逐字「**另外要考虑未来做集群部署时如何不影响用户，让用户无感**」；
> 同日 20:43 追加「**磁盘先不用管，未来要考虑做集群的磁盘告警，可以依赖阿里云的能力**」。
> 关联 issue #9084。判据 = `tests/unit_ci_workflows/test_zero_downtime_release_adr.py`（MC-348）。
>
> **本页的增量只有两块**：① **零停机的切换模型**（M1：怎么切、按什么顺序、失败怎么退）；
> ② **单机 → 集群的迁移路径**（M2：每一步的前置与回退点）。
> 代码级取证（P0/P1 清单、进程内状态逐条证据）**不在这里重复** —— 见
> [`cluster-readiness-audit.md`](cluster-readiness-audit.md)；上传存储的落地细节见
> [`upload-storage-and-multi-instance.md`](upload-storage-and-multi-instance.md)。
>
> 时间口径：本页所有读数均为 **Asia/Shanghai（UTC+8）**；引用 CI/云侧时间戳时已注明换算。
>
> 🔴 **落地状态（2026-11-24，issue #9098）**：**M1-a（upstream 摘挂）与 M1-b（应用优雅退出）已实施**，
> 代码位置 / 实现约束 / 怎么验证见各小节；每小节的「真机读数」表是**占位**——本 PR 合并前
> **未在真机实测**（需要测试环境发布通道），空着 = 未验证，不许读成已验证。

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

**nginx 现状（2026-11-24 更新，M1-a 落地后）**：`deploy/swas/nginx.conf` 顶部有三个 `upstream`
（`migao_admin_api` / `migao_ai_agent` / `migao_admin_web`），`proxy_pass` 一律指 upstream 名
（`proxy_pass http://migao_admin_api;` 等 8 处）—— 发布期由 `deploy.sh` 只改成员行 + `nginx -t` + reload。
**改动前**是 `proxy_pass http://admin-api:8080`（172/491/516/541/574 行等多处）、
`proxy_pass http://ai-agent:8000`（210/554 行）—— **走 compose DNS 服务名、nginx.conf 没有 upstream 块**
（全文件 `upstream` 出现 0 次）；启动/reload 时解析并缓存 IP ⇒ **重建容器 = 换 IP = 不 reload 就 502**
（实测窗口 90s）。两段的实现约束与验证方式见 M1-a 小节。

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

### M1-a 切换模型：nginx **upstream 摘挂**，而不是「重建正式容器」（已实施，issue #9098）

> **落地状态：已实施。** 实现位置（两处，加起来 ≈ 120 行）：
> - `deploy/swas/nginx.conf` 顶部的三个 upstream —— `upstream migao_admin_api` / `upstream migao_ai_agent` /
>   `upstream migao_admin_web`，成员带标记块（`# >>> migao-upstream-members` / `# <<< …`）；
>   `proxy_pass` 已全部改成 `proxy_pass http://migao_admin_api;` 这类 **upstream 名**；
>   另加 `worker_shutdown_timeout 200s;`（reload 时旧 worker 的兜底上限 = SSE 180s + 余量）。
> - `deploy/swas/deploy.sh` 的 `upstream_name_of()` / `upstream_members_for()` /
>   `rewrite_upstream_members()` / `nginx_upstream_switch()` / `upstream_drain_wait()` + 2.5 段的切换循环。
> - 判据 = `tests/unit_ci_workflows/test_zero_downtime_m1_cutover.py`（MC-351）。**红证**：把切换改回
>   「`docker compose up -d` 重建 + reload」⇒ 判据红（`test_injection_revert_cutover_to_recreate_plus_reload_goes_red`）。
>
> **三条实现约束（踩过就是全站挂 / 静默失效，别改）**：
> 1. **稳态只写现行实例一条成员**。nginx 在**解析配置时**就对 upstream 里的服务名做 DNS 解析，green
>    容器没在跑时写它的名字 ⇒ `[emerg] host not found in upstream` ⇒ **nginx 起不来 ⇒ 全站挂**。
>    所以 green 成员只在发布期由 `deploy.sh` 写入（写完**立刻** `nginx -t`），成功/失败都会恢复成稳态那一条。
>    「切换后每个 upstream 恰有两个后端」因此由**行为判据**证明（真跑改写器），而不是静态数 `server` 行。
> 2. 成员一律写 **容器名:容器内端口**（`admin-api-green:8080`），**不写宿主第二端口**
>    （`18080`/`18000`/`13001` 只在宿主侧可达，nginx 在容器里连不上）。
> 3. **配置只能原地写（不许 `mv` / `rename`）**。compose 把 `./nginx/nginx.conf` **单文件**挂进容器
>    （`…:/etc/nginx/conf.d/default.conf:ro`），docker 按 **inode** 挂载 ⇒ 换掉宿主侧 inode 之后，
>    容器里看到的还是**旧文件**：`nginx -t` / `nginx -s reload` 全在加载旧配置，而宿主侧的
>    `grep server_name` / sha256 打印看的是新文件 ⇒ **假绿**。改前 1.2.2 的**生产域**分支正是 `mv -f`
>    （测试域分支是 `cp -f`，所以只有生产会中）—— 这是本单顺手修掉的一个**既有静默 bug**。现在：
>    渲染与成员改写一律原地写；1.2.2b 核对「盘上 sha == 容器内 sha」（不一致 ⇒ 出声
>    `NGINX_CONF_MOUNT=STALE` + 重启一次 nginx 重新挂载，一次性自愈）；切换函数写完后同样核对，
>    不一致 ⇒ **不 reload**、恢复备份、回落重建路径（`return 3`）。
>    判据：`test_config_is_written_in_place_so_the_bind_mount_sees_it`（静态 + **真跑改写器断言 inode 不变**）、
>    **类级** `test_every_single_file_bind_mount_is_written_in_place`（从 compose 的 `volumes` **现取**单文件挂载集合，
>    与 deploy.sh 的挂载清单比对：新增单文件挂载不登记即红；命令行走 `mv` / `os.replace` 即红并点名行号），
>    外加注入式红证（删清单登记 / 用 `mv` 落地 / 改写器加 `os.replace`）。
>
> ⚠️ **自愈那一次是用户可见的中断，所以「第一次发布」不是零停机**：`docker compose restart nginx` 只重启
> **nginx 这一个容器**（业务容器一律不动，in-flight 请求会被断开，实测数百 ms 级）——只在「改前用 `mv` 渲染过」
> 的机器上发生**一次**，之后原地写不再触发。⇒ 合并后第一次生产发布按「有一次 nginx 重启」预期，
> **从第二次起的发布才具备零停机形态**。别把第一次当成结论。
>
> **怎么验证**（真机 = nginx 跑在**容器** `migao-deploy-nginx-1` 里；宿主**没有** nginx 二进制、没有 `/etc/nginx`）：
> ```bash
> # ① 稳态成员（应只有一条，且是现行实例容器名）
> docker exec migao-deploy-nginx-1 nginx -T
> docker exec migao-deploy-nginx-1 nginx -t          # ② 配置合法性（改之前必须先过这关）
> # ③ 入口自证：走真实 nginx 解析、钉回本机、不出网
> curl -sk -o /dev/null -w '%{http_code}\n' --resolve api.<站点域>:443:127.0.0.1 https://api.<站点域>/api/version
> ```
>
> **真机读数 —— 测试环境 `api.migaozn.com`，2026-11-24 02:40:46Z（10:40 +08），run 45313680373**
> （`gh workflow run deploy-admin-api.yml --ref main -f image_tag=sha-628ae70`，强制重部署同一 commit 以走完整切换链）。
> 填法 = 把发布日志原样粘进「值」列；**不写「已通过」**：
>
> | 读数 | 命令 | 值 |
> |---|---|---|
> | 配置挂载一致性 | 发布日志 `NGINX_CONF_MOUNT=` | `NGINX_CONF_MOUNT=OK（盘上与容器内一致）` |
> | 稳态 upstream 成员 | 发布日志 `UPSTREAM_MEMBERS=`（切换完成后） | `UPSTREAM_MEMBERS=migao_admin_api:1` |
> | 切换中 upstream 成员（应两条） | 发布日志 `UPSTREAM_MEMBERS=`（切换中） | `UPSTREAM_MEMBERS=migao_admin_api:2` |
> | `nginx -t` 结果 | 发布日志（容器内 `nginx -t`） | `nginx: configuration file /etc/nginx/nginx.conf test is successful` |
> | drain 读数 | 发布日志 `DRAIN=` | `✅ DRAIN=OK（旧 worker 已退出，在途请求已收尾；等待 1s）` |
> | 生效版本 | 发布日志 `EFFECTIVE_TAG=` | `admin-api:sha-628ae70`（同批 `admin-web:sha-628ae70`；ai-agent 本腿未发 `sha-b702bfe`） |
> | 环境闸门 | 发布日志 `RELEASE-LINE=` | `⏭️ RELEASE-LINE=SKIPPED reason=non-prod（MIGAO_PUBLIC_DOMAIN=migaozn.com）` |
> | 切换期入口 5xx 计数（发布前后差值） | `docker exec migao-deploy-nginx-1 tail -n 100000 /var/log/nginx/access.log` | **待填**（测试机 access.log 需在主机内取；外网探针在发布后 3 个面均 `200/200/307`，但**不是**窗口内读数） |
> | 回退演练耗时（成员切回旧实例） | 改回 `server <svc>:<port> …;` → `nginx -t` → `nginx -s reload` | **待填** |
>
> ### 生产读数（2026-11-24 11:17–13:01 +08，`a2c3386`，三服务逐服务 C′ 构建）
>
> | 读数 | 值（原文） |
> |---|---|
> | 三服务同源 | `✓ api/web/ai 同源 a2c3386`；`PROD-RELEASE rc=0 version=a2c3386 api=a2c3386 web=a2c3386 ai=a2c3386` |
> | 切换期入口失败 | `SWITCH-BLINDSPOT failures=0 max_gap_ms=351`（窗口 `109918ms` / `333` 采样）⇒ 工具自身判「**切换窗口内 0 次失败请求 ⇒ 这次切换对用户无感**」 |
> | 另两次窗口 | `failures=0 max_gap_ms=357` / `failures=0 max_gap_ms=364`（admin-api、ai-agent 重试窗口） |
> | `nginx -t` | `nginx: configuration file /etc/nginx/nginx.conf test is successful` |
> | 盘上 vs 容器内 | `md5 9782a0ed6e3c71e90cc8bc294157b582` **两侧相同**（≠ `STALE`） |
> | 稳态 upstream | 每服务**一条**成员（`server admin-web:3001 …` 形态） |
> | SSE 探针端点 | 线上可用：`data: 1` / `event: ping` / `data: 2`（`/internal/stream-probe?seconds=3`） |
> | 已知非零成本 | ai-agent 首两次构建被 `timeout 2400` 杀掉（默认 apt 源 >40 分钟）⇒ 换 `mirrors.aliyun.com` 后 ~9 分钟完成；已固化进发布入口 |
>
> ### SSE 长流跨切换（**已实测**，2026-11-24 16:52–16:56 +08，`3482e76`）
>
> 探针经 **nginx 用户路径**（`https://127.0.0.1/internal/stream-probe` + `Host: ai-api.<域名>`，
> 也就是真实用户走的那条：nginx → upstream → ai-agent），部署期间连续不停地开 200s 流：
>
> | 读数 | 值 |
> |---|---|
> | 跨切换的那条流 | `seq=1697`：`08:52:55` 建立（**容器启动前 2 秒**，容器 `StartedAt=08:52:57`）→ `08:56:14` 正常结束 |
> | 事件数 / 事件间最大间隔 | **400 个事件**（200 `event: ping` + 200 `data:`）；**max gap = 1s**（= 正常心跳间隔，**无中断**） |
> | 该窗口错误 | **0**（`ERR` 计数 0；前一段 403 是 nginx 尚未重载新 `allow` 列表时的自伤，重载后即 200） |
> | 同窗口入口盲测 | `SWITCH-BLINDSPOT failures=0 max_gap_ms=353`（窗口 110812ms / 338 采样） |
> | `nginx -t` | `test is successful` |
> | 三服务身份 | `ai 同源 3482e76`（本轮只发 ai-agent；api/web 仍是 `a2c3386`，发布入口因此判 `PROD-RELEASE rc=1` —— 见下） |
>
> **读法**：`max gap = 1s` 说明这条流在容器被替换的那一瞬间**没有断开**，而是照常按心跳节奏继续 ——
> 这正是 M1-a（upstream 摘挂）+ M1-b（uvicorn/Spring 优雅退出）一起生效的结果。
>
> **收口发布（2026-11-24 18:27–18:32 +08）**：`PROD-RELEASE rc=0 version=3482e76 api=3482e76 web=3482e76 ai=3482e76`，
> `SWITCH-BLINDSPOT failures=0 max_gap_ms=766`（窗口 113226ms / 339 采样）⇒ **三服务同源**，不再是部分发布状态。
>
> **仍未取**：**回退演练耗时**（= 把某个服务降级回旧 tag 并计时；`deploy.sh` 需要 `ALLOW_DOWNGRADE=1`，
> 属于**降级发布**，今天已在生产上连发 6 次，故留到下一次约定的维护窗口再演练，不在本轮硬做）。
>
> ### 本次发布暴露的入口缺陷（已修，PR #9125 待合）
>
> - `PROD-RELEASE rc=1` 不是发布失败，而是**入口的同一性检查按「全量三服务」判**，而本次用了 `PROD_SERVICES=ai-agent`
>   只发一个服务 ⇒ api/web 仍是旧 sha ⇒ 它如实判「不一致」。**该口径需要按 `PROD_SERVICES` 收窄**（否则「部分发布」永远红）。
> **仍未取**：**SSE 长流跨切换**（本次发布的旧容器还没有探针端点，端点是本次才上线的）⇒ 需要**下一次发布**在切换期间挂一条 200s 流来量；
> 以及「回退演练耗时」。
>
> ⚠️ **口径**：上表是**测试环境**读数 ⇒ 它证明「形态在真机成立」（2 成员切换 / drain / nginx -t / 挂载一致）；
> **生产读数仍未取**（第一次发布会有一次 nginx 重启做 inode 自愈，那次**不是**零停机），取数时同样只填原文。


**改动前的现状（历史事实，详见 §1.2）**：`deploy/swas/nginx.conf` 里 `proxy_pass http://admin-api:8080` 走 compose DNS
服务名、**nginx.conf 没有 upstream 块**（全文件 0 次）⇒ 重建容器换 IP 就必须 reload 才不 502（实测 90s）。
本项做的就是**新建** upstream（不是改造已有 upstream）。

**落地形态**（已落地；下面逐条给「实现位置 + 为什么这么写」，与最初的设想有两处**有意的偏离**）：

1. `proxy_pass` 改成 **upstream 名**：`proxy_pass http://migao_admin_api;` / `http://migao_ai_agent;` /
   `http://migao_admin_web;`（8 处，含 `/s/` `/i/` `/o/` `/api/` `/api/chat/` 等面）。
   🔻 **偏离设想 1**：upstream 定义**留在 `nginx.conf` 顶部**，没有抽成单独 include 文件 ——
   单独 include 会多一条「服务器上文件缺失 ⇒ nginx 起不来」的失效路径，而标记块方案把改动半径
   压到**同样几行**（成员块），却不引入新文件/新挂载/新同步面。其余 server/location **一字不动**
   （改动 diff 只有：顶部新增 upstream 段、8 行 `proxy_pass`、1 行 `worker_shutdown_timeout`）。
2. 成员写成**容器名:容器内端口**：`admin-api:8080` / `admin-api-green:8080` / `ai-agent:8000` /
   `ai-agent-green:8000` / `admin-web:3001` / `admin-web-green:3001`；**不写宿主第二端口**
   （`18080` / `18000` / `13001` 只是宿主侧探针端口，nginx 容器与它们在同一个 compose 网络里，
   直接走容器内 8080/8000/3001）。
3. 切流量 = **改成员块 + `nginx -t` + `nginx -s reload`**（`deploy.sh::nginx_upstream_switch()`）；
   reload 是优雅的：旧 worker 继续把**在途请求**做完再退（`worker_shutdown_timeout 200s` 兜底）。
   reload 之后**再等 drain**（`upstream_drain_wait()` 读 nginx worker 标题
   `worker process is shutting down`，不是盲睡固定秒数）。
4. 新容器 healthy 之前**不进 upstream**；进入时写成 **green 主 + 正式容器 backup**
   （`server admin-api-green:8080 max_fails=2 fail_timeout=10s;` + `server admin-api:8080 backup;`）
   ⇒ 新镜像即使刚起就崩，nginx 的默认 `proxy_next_upstream error timeout` 也会回落到**旧容器**，
   用户看不到 5xx —— 这就是「加进 upstream」与「摘出旧实例」之间的安全垫。
5. 回退 = 把备份拷回 + reload（**秒级**，不重建任何容器）；`nginx -t` 失败时**根本不 reload**
   （入口一字未变），reload 失败时同样回退并重试一次。备份在成功后即删（不留垃圾）。
6. 🔻 **偏离设想 2（新增约束）**：稳态**只写一条成员**（原因见上方「三条实现约束」）；
   green 成员只在发布期存在，写它之前先 `nginx -t`、写完立刻校验。

**顺序（顺序即安全顺序，逐步可停；下表 = `deploy.sh` 2.5 段的真实顺序，行号由判据打印）**：

| # | 动作 | 失败时的样子 / 处置 |
|---|---|---|
| 1 | 备份当前 `nginx.conf`（`.bak-<时间>`）并 `nginx -t` 基线自检（`nginx_upstream_switch` 内） | 基线不通过 ⇒ **停**（说明当前入口配置本身有问题） |
| 2 | 起 `*-green`（同镜像/env/卷，第二端口 `18080` / `18000` / `13001`），`wait_healthy` + 迁移闸门 | 失败 ⇒ 删 green、**upstream 未动**、旧容器继续服务（现有 #4785 语义） |
| 3 | 改写成员块（`rewrite_upstream_members`：green 主 + 正式 backup）→ `nginx -t` | `-t` 失败 ⇒ 恢复 `.bak`、**不 reload**、删 green（entry 未受影响） |
| 4 | `nginx -s reload`（**摘旧**：新连接只进 green；旧 worker 继续手里的请求）→ 入口 200 断言 | reload 失败 ⇒ 恢复 `.bak` 再 reload；仍失败 ⇒ 保留旧 worker（不 restart） |
| 5 | 逐秒探活 `https://<站点域>/api/version` **并核对 sha**（不是只看 200） | 读数不是新 sha ⇒ 回退 include + reload（旧容器还在） |
| 6 | **等 drain**：`upstream_drain_wait` 等到旧 nginx worker 收尾（上限 `worker_shutdown_timeout` 200s，见 M1-d） | 提前停 = 断流；宁可多等 |
| 7 | 现在才 `docker compose up -d --no-deps <svc>` 重建正式容器（流量已在 green）→ 成员切回正式容器 | 停旧后才发现问题 ⇒ 回退 include 到 green（此时 green 已是唯一健康面），再起旧镜像 |
| 8 | 三服务同源自检（M1-f）+ 一致性读数入日志 | 不一致 ⇒ 判定「半截发布」，**当场补发或回退**，不许绿 |

**代价**：① 改的是流量入口（历史上最危险的改动面）⇒ 用「单文件 include + `nginx -t` + 备份 + 秒级回退」四道锁，
且**先在一台测试机演练一次**再上生产；② 发布期同时存在两份容器（内存峰值 +1 份，当前余量够，Swap=0 需注意）；
③ `nginx:alpine` 需支持 `worker_shutdown_timeout`（1.11.11+；落地前用 `docker exec nginx nginx -V` 自证版本）。

**判据**：① 灰度发布窗口内 `5xx = 0`；② 切换前后 `/api/version` 的 sha 从旧变新且**无 000/502 读数**；
③ 回退演练：把 include 换回上一份 ⇒ 30 秒内入口恢复旧 sha（记录耗时）；④ `nginx -t` 失败注入 ⇒ 不改入口。
**谁来做**：**包**（改 compose/nginx.conf/upstream include + `deploy.sh` 切换段 + 判据），评审后**人**在测试机演练一次。

### M1-b 应用优雅退出（Spring Boot / uvicorn）（已实施，issue #9098）

| 侧 | 目标配置 | 当前是否已配置 |
|---|---|---|
| admin-api（Spring Boot **3.5.16**） | `server.shutdown=graceful` + `spring.lifecycle.timeout-per-shutdown-phase=30s` | **已实施**：`application.yml` 的 `server.shutdown: graceful` + `spring.lifecycle.timeout-per-shutdown-phase: 30s`（30s 的理由写在该键上方：常规请求长尾数秒级 → ~10× 余量；SSE 不在这里，由 ai-agent 承载；且必须 < compose 的 45s） |
| ai-agent（uvicorn **0.54.0**） | `--timeout-graceful-shutdown 200`（>= SSE 最长流时长） | **已实施**：`backend/ai-agent-service/Dockerfile` 的 CMD 追加 `--timeout-graceful-shutdown 200`（200 = SSE 最长流 180s + 20s 余量）；compose **没有** `command:` 覆盖它（覆盖了就是死配置，判据钉住） |
| compose（两侧） | `stop_grace_period`（>= 应用的优雅退出预算；**docker 默认只有 10s**） | **已实施**：`docker-compose.yml` 与 `docker-compose.bluegreen.yml` 里 admin-api `stop_grace_period: 45s`（> 30s 应用预算 + 15s 收尾余量）、ai-agent `stop_grace_period: 210s`（> 200s uvicorn 预算） |

**怎么验证**（真机；宿主没有 nginx 无关 —— 这一项要的是「SIGTERM 下的行为」）：
```bash
  # ① 配置真的在容器里生效（不是只在仓库里）
docker inspect $(docker compose ps -q admin-api) --format '{{.Config.Cmd}} {{.Config.Env}}'   # 看 StopTimeout
docker compose exec -T admin-api printenv | grep -iE 'SHUTDOWN|LIFECYCLE' || echo '（无 env 覆盖 ⇒ 用 application.yml 的值）'
docker inspect $(docker compose ps -q ai-agent) --format '{{.Config.Cmd}}'                    # 应含 --timeout-graceful-shutdown 200
  # ② SIGTERM 行为：停容器，读日志里有没有 graceful 收尾
docker compose stop -t 45 admin-api && docker compose logs --tail 40 admin-api
```
**真机读数（本次发布）** —— 占位；未填 = 未验证：
| 读数 | 命令 | 值 |
|---|---|---|
| admin-api 生效配置 | `docker compose exec -T admin-api printenv`（找 override）/ `docker inspect` 的 StopTimeout | **待填** |
| ai-agent 生效 CMD | `docker inspect $(docker compose ps -q ai-agent) --format '{{.Config.Cmd}}'` | **待填** |
| admin-api 在途请求收尾 | 发一个慢请求（>10s）同时 `docker compose stop`，看它是否 200 收尾 | **待填** |
| ai-agent SSE 长流收尾 | `curl -N -H "X-Service-Token: <内部 token>" `https://ai-api.<站点域>/internal/stream-probe?seconds=200``（**发布前发出、切换期观察是否被切断**） | **待填** |
| compose `stop_grace_period` 生效 | `docker inspect` 的 `StopTimeout`（45 / 210） | **待填** |

**SSE 那一格现在可判定了：只读流式探针 `GET /internal/stream-probe?seconds=N`（issue #9098）**
—— 加它之前，这一格**不可判定**：真正会写库的 `/api/chat/send` 要鉴权 + 落库 + 调 LLM，不能当探针反复打；
而「应该不断流」不是判据。**为什么它只读安全**（三条硬约束，判据逐条钉住）：
① 只发 `event: ping`（每秒一条），**不碰 DB / 不调 LLM / 不建会话 / 不落历史**；
② 鉴权沿用内部服务 token（头名 `X-Service-Token` —— **来自既有内部鉴权实现** `app/utils/auth.py::verify_service_token`，
不是为这条探针新造的头名；值与 `/internal/tools/execute` 同一把 `SERVICE_TOKEN`）——
缺 / 错 ⇒ **401**，不许匿名可达；
③ 时长夹在 `[1, 200]`（= nginx `worker_shutdown_timeout 200s` / uvicorn `--timeout-graceful-shutdown 200`
同一个预算），被夹时先发一条 `event: notice` 自报（不静默）。

怎么用（测试/生产都行；token 在服务器 `.env.ai-agent` 的 `SERVICE_TOKEN`）：
```bash
TOKEN=$(docker compose exec -T ai-agent printenv SERVICE_TOKEN)   # 只在本机读，别贴日志
curl -N -H "X-Service-Token: $TOKEN" "https://ai-api.<站点域>/internal/stream-probe?seconds=200"
# 发布窗口内保持这条流：① 不断流 ⇒ M1-b 的优雅退出 + drain 生效；② 断了 ⇒ 记下断在第几秒（归因到哪一步）
```
判据：`backend/ai-agent-service/tests/test_stream_probe.py`（行为：401 / 夹取 + notice / ≥1 个 ping / 断开即结束）
+ `tests/unit_ci_workflows/test_zero_downtime_m1_cutover.py::test_stream_probe_is_readonly_gated_and_declared`
（静态：handler 内不许出现写库 / LLM 符号并**点名行号**，必须挂鉴权与夹取，且登记到 `APP_LEVEL_PROBES`）。
⚠️ 本 PR **未实测**这条流，且**测试环境缺 token 通道**：测试实例属于旧账号、集成侧手上的 AK 只能看到生产实例
⇒ 拿不到测试机的 `.env.ai-agent` / `SERVICE_TOKEN`。**⇒ SSE 这一格记在「下一次生产发布」验收**（在云主机内部执行，
token 从环境变量读、**不回显**；命令形状见上）；不写成「已通过」，也不写成「不可判定」。

⚠️ **「配置了」≠「生效了」**：`docker compose stop` 默认 10s 后 `SIGKILL` ⇒ 应用配 30s 也只会被砍在 10s。
三处必须**同时**配（应用 + compose + 编排脚本用 `stop` 而非 `kill`），且发布期用一个**长请求**实测：
发一个 ≥60s 的 SSE，在流未结束时切换 ⇒ 流必须自然收尾（不是断流），日志里出现 graceful 字样。

**代价**：低（配置面）；风险是「退出变慢」⇒ 部署总时长增加（可接受：drain 与优雅退出都**有上限**，
且只在上限内等待）。
**判据**：① 配置存在且 CI 判据钉住（`tests/unit_ci_workflows/test_zero_downtime_m1_cutover.py`：三处缺任一处即红；
`test_zero_downtime_release_adr.py` 再钉「本页口径与仓内配置同进」——任一侧先动都判红）；
② 长流实测（用只读探针 `GET /internal/stream-probe?seconds=200`）：切换期 SSE 完整收尾（**本 PR 未实测**，见上方「真机读数」表）；
③ 超过 `stop_grace_period` 仍不退 ⇒ 记 ERROR（这是「优雅退出没生效」，不是正常路径）。
**谁来做**：**包**已落地（配置 + compose + 判据）；**人**只做一次「真发一版看长请求」（测试环境）。

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

## 6.2 已知失效模式：**main 上下文**指令写进 `conf.d`（**已修**，2026-11-24 真机踩中）

`worker_shutdown_timeout` 属于 `ngx_core_module`，上下文是 **`main`**；而 `conf.d/*.conf` 被 `include` 在 `http {}` 里
⇒ 写在 `deploy/swas/nginx.conf` 里**任何位置都非法**。实测（测试腿 run 45307260452）：

```
[emerg] "worker_shutdown_timeout" directive is not allowed here in /etc/nginx/conf.d/default.conf（运行时路径，行号随渲染变化）
❌ nginx -t 不通过 ⇒ 已恢复备份、**未 reload**（入口一字未变）
##[error]部署失败（tag=sha-a98ffc8）—— 已自动回滚到 sha-b702bfe
```

- **失败模式是可接受的**：`nginx -t` 在 reload 之前拦住 ⇒ 入口未变、站点仍服务、自动回滚；
- **但盘上那份坏配置会让「下一次 nginx 重启」失败** ⇒ 必须当缺陷修，不能靠回滚兜；
- **修法**：该指令只允许出现在 `-g`（compose 的 nginx `command:`），且覆盖 `command` 时必须自带 `daemon off;`；
- **判据**：`test_zero_downtime_m1_cutover.py` 现在是「**conf.d 里出现即红**」+「compose 的 `-g` 缺失即红」（方向相反、互为反证）。

## 6.3 已知失效模式：护栏**缺环境作用域**（**已修**，2026-11-24 真机踩中）

发布线自检（#9086）首次上线时对**每一次**部署都要求「目标提交是 `origin/release` 的祖先」，
而**测试环境发的是 `main` 线上的分支提交** ⇒ 测试腿被自己的闸门拒（`RELEASE-LINE=UNVERIFIED ⇒ 拒绝部署`，run 45302667932 两次）。

- **类级教训**：任何「fail-closed 的护栏」都必须同时回答「**非生产怎么走通**」，否则护栏会把开发流程锁死；
- **修法**：`MIGAO_RELEASE_LINE=auto|enforce|off`（auto 按站点域判定；非生产 = `off` 且**出声** `RELEASE-LINE=SKIPPED`）；
- **判据**：测试域跳过 / 生产域照判 / 测试域 + `enforce` 也判 / 显式 `off` 出声（4 条，红证都实跑）。

## 6.1 已知失效模式：切换窗口内宿主重启（**接受**，不是忽略）

M1-a 把「稳态只写一条成员」当硬约束，代价是**切换窗口内**磁盘上的 `nginx.conf` 会临时引用
`<svc>-green` 成员（green 容器 `restart: "no"`）。如果宿主恰好在窗口内重启（整机重启 / 宿主机故障）：

- **后果**：nginx 起不来（`[emerg] host not found in upstream "admin-api-green"`）⇒ **全站不可用**，
  直到有人处理。这比改前的 502 窗口（秒级、自动恢复）**更坏**，所以必须写清楚而不是塞进脚注。
- **触发条件**（双重故障）：① 正处于某个服务的切换窗口（②切 upstream → ⑥切回 之间）；
  ② 此时宿主重启。三个服务串行 ⇒ 窗口不重叠，任一时刻最多一个 upstream 处于双成员形态。
- **窗口长度**：**上界 486 秒/服务**（= ②切换 <2s + ③入口探测 `12×(5s curl + 2s 间隔)`=84s +
  ④drain 上限 200s（`UPSTREAM_DRAIN_TIMEOUT`）+ ⑤重建后健康检查 `10×(10s curl + 10s 间隔)`=200s；
  常量见 deploy.sh 的 `NGINX_PROBE_TRIES/NGINX_PROBE_INTERVAL/UPSTREAM_DRAIN_TIMEOUT/HC_RETRIES`），
  三个服务串行 ⇒ 全量最坏 ~24 分钟；**典型 ≈ 5–15 秒/服务**（drain 通常 1–3s 就退、探测首次即 200、
  镜像已在本地）——典型值**待真机读数**（见 M1-a 读数表）。
- **修复（一条命令，分钟级）**：
  ```bash
  cd /opt/migao-deploy && bash ./deploy.sh <tag>     # 1.1/1.2.2 会按 canonical 重渲染（**原地写**）并 reload/重启入口
  # 或只救入口（不部署）：
  cat nginx/nginx.conf.canonical > nginx/nginx.conf && docker compose restart nginx
  ```
  （`nginx.conf.canonical` 每次发布都会从仓库整份落盘 ⇒ 它永远是「无 green 成员」的形态。）
- **为什么接受它**：窗口短（秒级~分钟级）+ 需要双重故障（窗口内恰好整机重启），而彻底消除要靠
  **常驻占位容器**（green 名字永远可解析）或 M2 的 SLB —— 前者给每次发布加一个常驻容器成本、
  后者是下一里程碑。**不在 M1 里做**。
- **评估过但决定不做的「保险」**：把 nginx 启动命令改成
  `sh -c 'nginx -t || cp default.conf.safe default.conf; exec nginx -g "daemon off;"'`。
  **不做**，理由：① 它把「配置坏了起不来」（响亮的、可行动的失败）换成「静默用旧配置起来」
  —— 正是本单在 inode 那条里刚堵掉的**同类假绿**（`-t` 失败也照跑，部署侧打印全绿而入口在用旧配置）；
  ② `default.conf.safe` 本身又是单文件挂载（同一个 inode 问题）+ 多一份要与 canonical 同步的副本；
  ③ 真出事时的恢复成本已经是「一条命令」（上面那条），保险带来的收益远小于它引入的新失效模式。

## 7. 未固化 / 未证实（照实登记，不粉饰）

| 项 | 现状 | 核实方式 / 出口 |
|---|---|---|
| 生产 admin-api **是否已优雅退出** | 仓内**已配置**（`server.shutdown: graceful` + `spring.lifecycle.timeout-per-shutdown-phase: 30s`）；生产运行时**未实测**（`.env.admin-api` 是否注入 `SERVER_SHUTDOWN` 覆盖 = 未证实） | `docker compose exec -T admin-api printenv | grep -iE 'SHUTDOWN|LIFECYCLE'` |
| ai-agent graceful 退出参数 | 仓内 CMD **已配置** `--timeout-graceful-shutdown 200`（uvicorn 0.54.0 支持）；运行时**未实测** | `docker inspect <cid> --format '{{.Config.Cmd}}'` |
| compose `stop_grace_period` | **已配置**（admin-api 45s / ai-agent 210s，两侧 compose 同值）；运行时 `StopTimeout` **未实测** | `docker inspect` 的 `StopTimeout` / compose 文件 |
| 生产 redis 的启动参数 / 版本 / 卷 | **无仓库承载**（compose 未定义）；只知是**本机容器** | `docker inspect $(docker compose ps -q redis 2>/dev/null || docker ps -q -f name=redis)`；确认有无持久化卷 |
| 生产是否已启用 OSS | **未证实**（凭据在 `.env.admin-api`） | 见 `upload-storage-and-multi-instance.md` §2/§4：`GET /api/version/storage`，或 `printenv | grep '^OSS_'`（只看键） |
| RDS `max_connections` | **未证实**（仓内无读数） | `SELECT setting FROM pg_settings WHERE name='max_connections';` |
| 阿里云云监控**指标名** | **待核对**（本页不编指标名） | 云监控控制台「主机监控 → 指标列表」逐项核对后回填 M2-d；或云监控 API 文档 |
| SLB/ALB 连接排空的**开关名与上限** | **待核对** | 控制台「监听 → 连接优雅中断」/ 文档；本页只定语义顺序 |
| SSE `Last-Event-ID` 续流 | **未实现**（生产代码 `backend/`、`frontend/` 检索 0 命中） | 需单独立项（依赖增量落库 + 幂等键，见审计 P0-4）；本页只定语义 |
| admin-web 构建身份 | **无端点** ⇒ 同源自检对 admin-web 只到「镜像 tag」层 | 若要补：加一个静态 `version.json` 烘进镜像（后续包） |
| nginx `worker_shutdown_timeout` 可用性 | `nginx:alpine` 版本未登记 | `docker exec <nginx> nginx -V`（>= 1.11.11 即支持）；旧版本回退 = 停旧前**睡满** 200s |
| M1 的真实演练 | M1-a / M1-b **已实施**，但**未在真机演练**（缺测试环境发布通道） | 测试机 `api.migaozn.com` 演练一次「切换 + 回退」，把耗时与 5xx 读数填进 M1-a/M1-b 的「真机读数」表 |

---

## 附：本页的判据（防「文档空话」）

- 判据文件：`tests/unit_ci_workflows/test_zero_downtime_release_adr.py`（`# case_ids: MC-348`）。
- 它锁三件事：① M1 六项 / M2 五项关键字必须在**各自小节**里（删任一项 ⇒ 判红并点名）；
  ② 本页的**事实性断言**必须与仓内真实配置一致（`18080` / `18000` / `13001`、
  **upstream 已落地**（`proxy_pass http://migao_admin_api` + 三个 `upstream` 块）、
  `/opt/migao-deploy/uploads`、redis 本机容器且 compose 未定义、
  **graceful「已实施」**（`server.shutdown` / `--timeout-graceful-shutdown`））⇒ 配置一改，文档不同步就红；
  ③ 注入式红证：删 M1 任一项 ⇒ 红；把 `18080` 改成 `18081` ⇒ 红。
- 用例登记：`.github/cases/misc.yml` 的 `MC-348`（QA Growth Gate 的 G5 追溯要求声明号存在于用例库）。