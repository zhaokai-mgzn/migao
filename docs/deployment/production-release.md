# 生产发布（与 GitHub 解耦）：部署机上的唯一入口

> 定于 **2026-11-23**（用户逐字裁定：「为什么部署生产环境还要依赖 github 的 ci？不可以直接走部署机吗？
> **生产环境需要和 github 的能力解耦**」）。适用于生产 `cytda.com` 的一切发布。
> 命令只跑在**部署机**（`ssh migao-deploy`，Apple Silicon 那台）上；GitHub 不参与。

## 一句话

**发布 = 部署机上的一次显式动作**：`bash scripts/prod-inspect.sh`（看现场）→ `bash scripts/prod-release.sh`（dry-run 看计划）
→ `bash scripts/prod-release.sh --apply`（真发 + 自检 + 台账）。远端执行体仍是盘上**既有**的
`/opt/migao-deploy/deploy.sh`（严格蓝绿，issue #4785）—— 本仓不重写部署逻辑。

## 为什么与 GitHub 解耦（三条现场事实，不是偏好）

| 事实 | 读数 | 后果 |
|---|---|---|
| 生产 **22 端口只对办公出口开放** | 部署机 `ssh` 生产实例 **不通** | GitHub runner 不在那个出口 ⇒ 任何「runner 直接 ssh 上线」的方案先天不可达 |
| 部署机到生产 **443 通** | `curl -sS -o /dev/null -w '%{http_code}' https://api.cytda.com/api/version` ⇒ `200` | 应用层读数随时可取（**不需要**云 API） |
| 凭证在**部署机本地** | `~/.aliyun/config.json` 的 `prod` profile（AK 模式，`cn-hangzhou`） | 不用 GitHub secret、也不会被 runner 侧的策略卡住 |

运维通道因此是 **OpenAPI 云助手**（`aliyun swas-open run-command` / `describe-invocation-result`），
唯一实现在 `scripts/lib/prod-swas-run.sh`（两个脚本共用）。两个踩过的坑写在那个文件头部：
`--command-content` 是**明文**（给 base64 会被当成一个超长文件名 ⇒ 远端 `exit 127`）、回读的 `Output` 是 **base64**、
返回结构有 `InvocationResult` / `InvocationResults.InvocationResult` **两种形态**。

## 今天为什么必须改（半截发布的现场）

2026-11-23 **11:32–11:39** 有一次**只更新 admin-api 的手工发布**：

| 服务 | 身份 | 容器起于 |
|---|---|---|
| `admin-api` | `sha-26ff9f7` | 2026-11-23 11:39 |
| `admin-web` | `sha-caf01e4` | 2026-11-21 22:52 |
| `ai-agent` | `sha-0dced39` | 2026-11-22 18:25 |

⇒ 三服务**身份不自洽**（前后端契约错配），而**当时没有任何东西会报**。本命令把「同源」变成发布动作的**必经自检**。

## 怎么跑（三条命令）

```bash
# ① 看现场（只读；GitHub 无关）
bash scripts/prod-inspect.sh
#   …分段读数（host / disk / containers / env_site / nginx / cron / timers）…
#   READONLY-INSPECT=OK            # 或 INCOMPLETE failed=[…] missing=[…]

# ② 看计划（dry-run 是**缺省档**；零写面：一次 run-command 都不发）
bash scripts/prod-release.sh
#   == 计划（dry-run；未写任何东西）==
#   目标版本 = 26ff9f7（完整 …）· 发布线 = origin/release @ 26ff9f7
#   远端命令（--apply 时才执行）：bash /opt/migao-deploy/deploy.sh <版本参数> <目标 sha>
#   线上三服务身份（443 应用层读数）：api = … · web = … · ai = …
#   DRY-RUN=OK（零写面：本次没有发出任何 run-command）

# ③ 真发（显式给 --apply 才动生产）
bash scripts/prod-release.sh --apply
#   SWITCH-BLINDSPOT failures=0 max_gap_ms=…
#   PROD-RELEASE rc=0 version=26ff9f7 api=26ff9f7 web=26ff9f7 ai=26ff9f7 at=2026-11-23T00:00:00Z operator=you@example.com
```

其它开关：`--version <sha|tag>`（缺省 `HEAD`）、`--drain-seconds N`（默认 10，上限 60）、`--probe-seconds N`（默认 120）、
`--host-assert`（只判「本机是不是部署机」，零副作用）。

## 闸门与自检的含义

| 闸门 | 判什么 | 不满足 |
|---|---|---|
| ① 机器闸门 | 本机身份 == `ssh -G migao-deploy` 解析出的 `HostName`（**不写死 IP**） | 退 **1**（具名 + 三个出口）；读数拿不到 ⇒ 退 **3** |
| ② 发布线闸门 | 目标版本**必须是 `origin/release` 的祖先**；`release` 上有 `main` 没有的提交**允许**（记账）；`main` 领先 `release` 的部分**报数**（本次不发） | 退 **1**（具名 + `release..target` 的提交）；远端取不到 ⇒ 退 **3** |
| ③ `--apply` 闸门 | 不给 `--apply` 就是 dry-run：**一次 `run-command` 都不发** | —— |
| ④ 真发 | `bash /opt/migao-deploy/deploy.sh <版本参数> <目标 sha>`，版本参数**先读 `--help` 现判** | 退回 **1**；`--help` 读不到 ⇒ 退 **3**（**不猜**参数名） |
| ⑤ 发后自检 | 三服务**同源同一 sha == 目标版本**：`docker ps` 镜像 tag + 应用层 `/api/version`、`/version.json`、`/version` | 退 **1**，**点名**哪个服务、差多少 |
| ⑥ 台账 | 成功才追加一行 JSONL 到 `/opt/migao-deploy/release-ledger.jsonl`（**只追加**） | 追加失败 ⇒ 退 **1**（发布成功但台账缺行 = 缺口，不许静默） |

三态退出码：`0` 成功 / `1` 判红（具名）/ `2` 用法错误 / `3` **判不了**（CLI 缺、凭证缺、实例拿不到、`deploy.sh --help` 读不到）。
**`3` 不得当 `0` 读** —— 不知道 ≠ 没问题。

## 失败怎么读

| 读数 | 含义 | 先做什么 |
|---|---|---|
| `非部署机 ⇒ 拒绝发布`（退 1） | 你在别处跑了 | `ssh migao-deploy` 之后在部署机上重跑（这是**唯一**正确路径） |
| `不可判定（3）：读不到 SSH 别名…` | 本机身份读不出来 | 检查 `~/.ssh/config` 的 `Host migao-deploy` 段，或给 `MIGAO_PROD_SSH_CONFIG=<文件>` |
| `目标版本不在发布线上`（退 1） | 你要发的 sha 不在 `origin/release` 上 | 先 `./scripts/cut-release.sh`（显式动作）再看它从哪来 |
| `不可判定（3）：取不到 origin` | 网络 / 远端不可达 | 恢复访问后重跑（**不许**当「发布线没问题」） |
| `读不到 … deploy.sh 接受的版本参数`（退 3） | 盘上 `deploy.sh --help` 的形态变了 | 看它打印的 `--help` 片段，把参数形态告知本仓（**不要**猜着发） |
| `三服务身份不同源 …`（退 1） | 发成半截（2026-11-23 11:39 的现场） | 看点名的是哪个服务 / 差多少提交；重跑 `--apply` 或按 `docs/deployment/rollback.md` 回滚 |
| `SWITCH-BLINDSPOT failures>0` + `::warning::` | 切换窗口里有失败请求（**不是**发布失败） | 记下来；把窗口归零要靠改造 `deploy.sh` / nginx（**下一个包**） |
| `SSE-PROBE=SKIPPED` | 没配置流式探针端点 | 给 `MIGAO_PROD_SSE_PROBE_URL`（**缺口**，见下节） |
| `READONLY-INSPECT=INCOMPLETE failed=[…]` | 盘点里有段没跑通 | 那一段就是**没看到的现场**，别写成「没问题」 |

## 无感发布的现状与缺口（集群部署的前置条件）

**现状**：盘上 `deploy.sh` 已是**严格蓝绿**（issue #4785）——先起 `admin-api-green` / `ai-agent-green` / `admin-web-green`
到第二端口（`BG_ADMIN_API_PORT=18080` / `BG_AI_AGENT_PORT=18000` / `BG_ADMIN_WEB_PORT=13001`），
用**与正式容器同一份健康判据**，通过后才替换正式容器（不通过 ⇒ 删 green + `exit 1`）；旧容器在 green 健康前**完全不动**。
它**有意不走 nginx upstream 切换**（`deploy.sh` 的取舍说明），所以切换 = **重建正式容器 + `nginx -s reload`**。

**⇒ 单机蓝绿 ≠ 集群无感。** 逐条缺口（本包**只度量、只标注**，不改造）：

1. **nginx 是服务名解析**：`proxy_pass http://admin-api:8080` 这类写法在容器重建后 IP 变、必须 `nginx -s reload`
   ⇒ **窗口内会 502**。窗口有多大 = `SWITCH-BLINDSPOT failures` / `max_gap_ms` 的读数（每次 `--apply` 都量）。
2. **应用层优雅退出未验证**：Spring `server.shutdown=graceful` / uvicorn `--timeout-graceful-shutdown`
   在当前配置里**未验证**（本包不改、也不假装已配）—— 在途请求在容器被替换时会不会被切断，没有读数。
   `DRAIN` 只等 `ai-agent` 的活跃流（`ss -tn state established '( sport = :8000 )'`），**不是**优雅退出的替代。
3. **DB 迁移必须 expand/contract**：旧版本代码要能跑新表结构（先加列 / 后删列，两段式），
   否则「绿容器健康、旧容器还在服务」的那几十秒里会撞上新表结构。
4. **集群还需要**：共享 `uploads`（现在是 `/opt/migao-deploy/uploads` **本地目录**）、共享 Redis
   （现在是本机 `migao-redis` 容器）、定时任务单例（cron / `systemd` timer 在多机下会重复跑）、
   SLB 健康检查（上线摘流 / 下线接流）、灰度权重（按比例导流，而不是整机切换）。

**资源面告警（磁盘 / 内存 / 连接数）未来走阿里云云监控**，不自建阈值判据（用户 2026-11-23 裁定
「磁盘先不用管，未来要考虑做集群的磁盘告警，可以依赖阿里云的能力」）。`prod-inspect.sh` 里的
`df` / `free` / `docker system df` / `uptime` **只作信息打印**，**不参与退出码**；
内存预检已在盘上 `deploy.sh`（green 与旧容器并存需要 `mem_limit(1536m)+512m`，不够它自己 fail-closed 中止）——
本仓**复用它，不复制**。

## GitHub 那条腿现在是什么地位

`.github/workflows/deploy-prod.yml` **降级为备用**，不是主路径（**本包不改它**）：

- 它拿不到现场（22 只开办公出口 / 凭证在部署机），出问题时的可诊断性远低于「在部署机上跑一条命令」；
- 但它仍是「有人在 GitHub 上按一下」的合法备用入口 —— 前提是**发完必须复算本仓的三条判据**
  （`prod-inspect.sh` 的 `READONLY-INSPECT` + 应用层三服务同源 + `PROD-RELEASE` 记录行）；
- 建议（写在这里、不在本包实施）：① 把 `deploy-prod.yml` 的注释与 workflow 名标注「备用」；
  ② 它跑完后调用 `prod-inspect.sh` 做只读复探；③ 长期把生产发布从 workflow 面移走，只在仓库侧留**判据**。

## 判据

```bash
python3 -m pytest tests/unit_ci_workflows/test_prod_release_decoupled.py -q
```

覆盖：只读白名单、发布脚本无写面（点名行号）、`--apply` 闸门（静态 + 行为桩：dry-run 0 次 `run-command`）、
机器闸门三态、版本闸门三态（本地 bare 仓，不真连网）、发后同源自检（不同源 ⇒ 点名 + 台账 0 次）、
切换盲区读数、`deploy.sh --help` 现读、盘点三态、文档接线。

## 边界（照实登记）

- **本仓没有执行过真实 `--apply`**：判据全打在桩上；真发由人在部署机上跑一次（首个 `PROD-RELEASE` 记录行即验收读数）；
- 判不了盘上 `deploy.sh` 的真实参数面（`--help` 的真实输出不在研发机）：脚本**现读**，读不到就退 **3**；
- 判不了真实切换窗口的失败数（要看真发布）；`SWITCH-BLINDSPOT` 是**度量**，不是承诺；
- `SSE-PROBE` 需要显式给端点（`MIGAO_PROD_SSE_PROBE_URL`）才有读数；不给就打印 `SKIPPED`（**缺口**，
  重启条件 = 有一个可只读建立的 `/api/chat/*` 流式端点或 service token）。
