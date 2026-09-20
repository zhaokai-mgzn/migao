# CI/CD 流水线

## 14 个 GitHub Actions 工作流

| 工作流 | 触发 | 说明 |
|--------|------|------|
| `pr-check` | PR → main | 多 job 门禁: 拦截 .env / admin-api 单测 / admin-web tsc+lint+vitest / E2E 质量门禁(4 个 fixture spec) / UI 回退检测 / QA Growth Gate(G1+G5+弱断言) / Case Contract 校验 / needs-changes 打标（**agent-eval-smoke 已于 #3653 移除**：B 端云冒烟评的是已部署 main、与本 PR 无因果；B 端行为信号由 agent-behavior-eval 映射用例承担） |
| `ai-agent-tests` | PR → main | ai-agent-service 单测全量（排除 integration / e2e-real / 4 个 ignore 文件）；**v1.3 起 job 内门控**：无 ai-agent 相关变更时跳过实际单测（required check 仍报告 success，防 dependabot 空跑） |
| `deploy-admin-api` | push main `backend/admin-api/**` | 单测 → Maven 构建镜像推 ACR → 云助手触发 SWAS `deploy.sh` → post-deploy 冒烟 |
| `deploy-ai-agent-service` | push main `backend/ai-agent-service/**` | 单测全量 → 构建镜像推 ACR → 云助手触发 SWAS `deploy.sh` → post-deploy 冒烟 |
| `deploy-frontend` | push main `frontend/admin-web/**` | tsc + vitest → 构建镜像推 ACR → 云助手触发 SWAS `deploy.sh` |
| `smoke-test` | workflow_call (可复用) | P0 冒烟 (pytest+httpx)，被 deploy 工作流调用 |
| `agent-eval` | workflow_dispatch（按需） | 米宝能力评测（normal tier 按需手动，真实 LLM + `cases/*.yml` 单一源；2026-08-29 起取消每日定时） |
| `agent-eval-adversarial` | schedule 每周六 03:00 | 对抗用例评测（只追踪不阻塞） |
| `e2e-real` | schedule 每日 00:00 + 手动 | backend `tests/e2e/real/` 真实 LLM 测试，失败自动建 Issue |
| `mini-app` | PR/push `frontend/mini-app/**` | tsc + 单测 + xiaobu H5 视觉回归；**v1.3 起 job 内门控**（同 ai-agent-tests） |
| `issue-contract-check` | issue opened | 校验 CONTRACT_JSON → needs-verification / needs-truths + cases 引用校验 |
| `case-draft` | issue opened/edited/labeled | 自动生成验收用例草稿 + DRAFT cases 引用提醒 |
| `case-redraft` | issue_comment (reject) | 驳回后隐藏旧 DRAFT 重新生成 |
| `verify-trigger` | PR closed (merged) | 贴 VERIFY_TRIGGER → 双验收 → 通过自动 close issue |

## CI 队列治理（v1.3，2026-09-04）

- **concurrency 取消旧 run**：`pr-check`/`ai-agent-tests`/`mini-app` 均加 `concurrency.group`（按 PR 号），同 PR 新 push 自动取消旧 run，防多 commit 并发打满 runner 队列。
- **变更门控（job 内，不整层 skip）**：`ai-agent-tests`/`mini-app` 等 required job 在 job 内用 `git diff origin/main...HEAD` 检测相关路径；无变更时实际执行 step 跳过（job 仍 success，required check 永不悬空）。**注意：不要改回 workflow 级 `paths` 过滤——required check 会卡在 "Waiting" 永不报告**（见 §3.2 技能说明）。`agent-behavior-eval.yml` 的 **workflow 级 `paths` 门**（只认 `backend/ai-agent-service/app/**`）现在只门控**零 LLM 的映射 job**（信息性 check，无 required 悬空问题，#3653/#4034）；`worker-h5-tests.yml`（只认 `frontend/worker-h5/**`，跑 Node 内置 `--test`，零 install/零构建）同属这一类（**非 required 信息性 check**，#4786）。
  · **静态落地面腿**：`worker-h5-publish.yml`（`push: main` + paths 只认 `frontend/worker-h5/**` 与发布链路自身；**刻意不加 `pull_request`** —— 它写的是**线上静态根**，PR 分流内容不该有机会落上去，故也没有「required 卡 Waiting」的形态）把 `frontend/worker-h5/` 的 `index.html` + `src/**` **逐字**发布到 `app.migaozn.com` 静态根下的 `w/`（零构建，**不引 npm build**），发布后断言线上 `/w/` 的 body 哈希 == 仓库文件且不含 C 端标识（issue #4837；nginx `root` 与 `w/` 子树的红线见 `deploy/swas/h5-publish-remote.sh` 的目标守卫）。
- **把 paths 门控的信息性 check 提升为 required 的顺序（2026-09-20 固化，#4786）**：**必须先删掉 workflow 级 `paths:`、改成 job 内 diff 门控**（`git diff --name-only origin/main...HEAD` + `GITHUB_OUTPUT`，同 `pr-check.yml` 的 `Detect admin-web changes` 步），**再改分支保护** —— **顺序不可换**：先改分支保护 ⇒ required check 在不命中 `paths` 的 PR 上**卡在 "Waiting" 永不报告** ⇒ 形态 =「**没有任何检查会变红，但 PR 合不了**」（#4231 同族）。
- **真实 LLM 成本**：**PR 层 = 0 次真实 LLM**（2026-09-17 用户裁定 2′/4′，承载 issue #4034：`agent-behavior-eval` 的评测 job 已整体删除，只留零 LLM 的**映射信号** + 派发命令）。判定走**单一入口** `post-deploy-eval`（每 3 天 normal 全量 + 手动 dispatch）；定时档（3 天 normal / 每周 adversarial ×2）**全部保留**——「收敛」不等于删定时档。LLM 红例的闭环改由**确定性下沉台账**承接（`.github/llm-finding-ledger.json` + `llm_sink_check.py`，见 `docs/testing/llm-finding-sinking.md`）。
- **观察指标**：`gh run list --status queued` 排队 >20 即需治理（先按 DEV-FLOW §7 清 dependabot 潮）。

## 部署目标（2026-08-14 起：SAE → SWAS；当前 SWAS 为**测试环境**）

| 服务 | 目标 | 技术 |
|------|------|------|
| admin-api | SWAS 单实例（拉 CI 预构建镜像） | Java 21, 容器端口 8080 |
| ai-agent-service | SWAS 单实例（同上） | Python 3.11, 容器端口 8000 |
| admin-web | SWAS 单实例（同上） | Next.js, 容器端口 3001 |
| nginx | SWAS 同机 | 80/443 TLS 终结 + 域名分流 |

数据层不在 SWAS 上：PostgreSQL 用阿里云 RDS、Redis 用 Tair 公网代理（admin-api 已强制 Lettuce RESP2）、OSS/DashVector/DashScope 不变。

**环境定位**：当前 SWAS 即测试环境（自动部署）；未来正式生产走受控发布（见 [production-deployment.md](../deployment/production-deployment.md) 与 `deploy-prod.yml`）。

## 部署链路（测试环境自动部署）

```
push main / push tag v*（路径过滤）→ CI 测试/构建镜像推 ACR（tag=sha-<7> 或 vX.Y.Z + latest）
  → aliyun swas-open RunCommand（实例 b23c69e5..., 超时 3600s）
  → 服务器执行 /opt/migao-deploy/deploy.sh <IMAGE_TAG>（先自愈式同步最新 deploy.sh）：
     1. docker login ACR（服务器需凭据拉私有镜像）
     2. docker compose pull（拉 CI 预构建镜像，不做源码构建）
     3. 严格蓝绿（#4785）：逐服务「先起 green 探针（第二端口）→ 健康检查通过 → **才**替换正式容器」
     4. nginx 优雅 reload（失败回落 restart）+ 健康检查 8080/8000/3001
  → CI 轮询 DescribeInvocationResult 至 Success
  → smoke-test.yml post-deploy 冒烟（api.migaozn.com / ai-api.migaozn.com）
```

### 镜像 tag 策略（2026-08-30 起）

| 触发 | 镜像 tag | 部署 |
|------|---------|------|
| push main（路径匹配） | `sha-<git 前7位>` + latest | 自动部署测试环境（SWAS） |
| push tag `vX.Y.Z`（release.yml 打标） | `vX.Y.Z` + `sha-<7>` + latest | 自动部署测试环境（回归） |
| workflow_dispatch（手动）空 image_tag | 构建当前代码 `sha-<7>` 并部署 | 手动部署测试环境 |
| workflow_dispatch 填 image_tag | 跳过构建，部署指定版本 | **回滚/指定版本** |

生产发布：`deploy-prod.yml`（Environment 审批 + 指定版本），详见 [production-deployment.md](../deployment/production-deployment.md)。回滚见 [rollback.md](../deployment/rollback.md)。

## 部署故障恢复手册（2026-09-21 云测试环境事故复盘后固化，issue #4767）

### 并发锁的行为（**"main 前进却无新部署"的真因**）

三个部署 job 各有一个 concurrency 组（`deploy-admin-api` / `deploy-frontend` / `deploy-ai-agent-service`，
`cancel-in-progress: false`）。**锁由 run 的终态（success / failure / cancelled）释放** ——
run 卡在 `in_progress` 时会**一直占着它**，后续 main 的部署**全被挡住**。
2026-09-21 实测：两条腿在 `ca724257e` 失败后挂住 `in_progress` 20+ 分钟（`updated` 冻在同一分钟），
之后 push 不再产生任何部署 —— 而**没有任何检查会因此变红**。

### 卡住 / 失败时的恢复步骤

```bash
# ① 找卡住的 run
gh run list --workflow=deploy-admin-api.yml --limit 5
# ② 清掉并发锁（不必等它自己结束）
gh run cancel <run-id>
# ③ 同 SHA 重跑，恢复推进
gh run rerun <run-id> --failed
# ④ 环境已不可用时，手工回滚到上一个可用镜像 tag
gh workflow run deploy-admin-api.yml -f image_tag=<上一个可用 tag>
```

### 自动化的四条兜底（#4767 落地）

| 机制 | 位置 | 行为 |
|---|---|---|
| 部署阶段**硬超时** | `deploy/scripts/swas-deploy-ci.sh`（`SWAS_DEPLOY_TIMEOUT_SECONDS`，默认 900s / 次尝试） | 超时即 `exit 1`（不再无限轮询把 run 钉在 `in_progress`）；每次 aliyun CLI 调用另有 60s 上界（`SWAS_CLI_TIMEOUT_SECONDS`） |
| **job 级**硬超时 | 三个 deploy workflow 的 `build-and-deploy`（`timeout-minutes: 45`） | 脚本整体卡死时由 GitHub 终止 run ⇒ run 进终态 ⇒ **锁一定释放** |
| 失败**不留坏状态** | `swas-deploy-ci.sh` | 失败**自动重试 1 次** → 仍失败**回滚到 `.last-good-tag`（上一个可用镜像）** → 回滚也不行 ⇒ `::error::` 显式告警 |
| 严格蓝绿（**内层**兜底） | `deploy/swas/deploy.sh`（#4785） | 新容器先起 → 健康检查通过 → **才**切流量；不通过 ⇒ **旧容器一动不动**（**失败窗口 = 0**）⇒ 坏镜像**永远碰不到**旧容器（外层回滚仍保留，见下） |
| 对账**断路器** | `deploy-reconcile.yml` | 同一 `head_sha` 的部署**已失败过** ⇒ 不再自动补部署（防止反复重试坏 commit、覆盖手工回滚）；fail-open |

### 严格蓝绿（issue #4785）：新容器先起 → 健康检查通过 → 再切流量

**改动前**的替换语义是 compose 的「**停旧 → 删旧 → 建新 → 起新**」（不是滚动、更不是蓝绿）——
新镜像起不来时**旧容器已经走了**，这就是 2026-09-21 事故把 admin-api 打成 502 的那一步。
现在 `deploy.sh` 对每个待更新服务走四步：

```
① 先起 green 探针（新容器名 + 第二端口 18080/18000/13001，**旧容器完全不动**）
② 用与第 3 步**同一份**判据健康检查 green → 失败 ⇒ 删 green、exit 1，**旧容器一动不动**（失败窗口 = 0）
③ 通过才 `docker compose up -d --no-deps <服务>`（替换正式容器）
④ 正式容器健康后删 green；最后 nginx **优雅 reload**（失败回落 restart）
```

- **为什么用「第二端口」而不是 nginx upstream 切换**：`nginx.conf` 里 `proxy_pass http://admin-api:8080`
  走 compose DNS 名，nginx 在**启动/reload 时**解析并缓存上游 IP；改 `nginx.conf` 写坏 =
  **全站所有域名同时挂**（部署链最贵的一种事故）⇒ 本单不碰它。
  **残留窗口（如实登记，不粉饰）**：**失败路径窗口 = 0**；**成功路径**仍有「替换正式容器 + 启动 + reload」的
  **秒级**窗口 —— 与改动前**同量级、未变差**，且此刻镜像已被证明能起。
- **内存前提**：green 与旧容器**并存** ⇒ 部署前预检 `MemAvailable ≥ 2048MB`（最重服务 mem_limit 1536m + 512m 余量）；
  不足 ⇒ **中止部署**（fail-closed，旧容器不动、环境不受影响）。
- **green 探针 `restart: "no"`**：探针崩了不许自愈复活（`unless-stopped` 会让它在 docker 重启后
  被拉起来、占着第二端口并让下一次部署撞名字/端口）。
- **逐服务串行** ⇒ 内存峰值只多**一个**容器（不是三个）。

#### 改坏了怎么回退（**一条命令**）

```bash
# ① 最快放行口（不改代码、不必等 CI）：跳过蓝绿预验证，回到 #4767 的「失败即回滚」路径
ssh <swas> 'touch /opt/migao-deploy/.blue-green-off'
# ② 彻底回退（本单的代码改动）：revert 合入提交，走正常 PR 重跑部署
git revert <本 PR 的 merge sha>
# ③ 环境已不可用：手工回滚到上一个可用镜像 tag（同上面「卡住 / 失败时的恢复步骤」④）
gh workflow run deploy-admin-api.yml -f image_tag=<上一个可用 tag>
```

⚠️ **放行口只跳过「预验证」，不跳过更新本身** —— 否则 `.blue-green-off` 会静默变成「本次不部署」
（最恶劣的静默失效）。守卫 `test_exec_escape_hatch_skips_blue_green` 钉住这一点；放行后输出里会明写
「本次新镜像**未被预验证**」。

#### 上真机后怎么验证（**可执行判据**）

```bash
# ① 看 green 的「出现 → 消失」顺序（在 job summary 的远端输出里；CI 日志会被截断）
#    期望：up -d --no-deps <svc>-green → <svc>-green OK (200) → up -d --no-deps <svc> → rm -sf <svc>-green
# ② 红证（推一个坏镜像）：让新镜像起不来，观察 admin-api 是否**始终在服务**
curl -s -o /dev/null -w '%{http_code}\n' https://api.migaozn.com/          # 期望：非 502（旧容器仍在服务）
ssh <swas> 'docker ps --format "{{.Names}}\t{{.Status}}" | grep admin-api'  # 期望：旧容器未被替换
```

#### ⚠️ 通用坑：bind mount 的**单文件**必须原地改写（`mv` 会换 inode）

`nginx.conf` 是以 `./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro` 的**单文件** bind mount 进容器的。
单文件挂载绑定的是**创建时的 inode**：在宿主上用 `mv`/`cp` 覆盖会**换 inode** ⇒ 容器里读到的仍是**旧文件**
（**且不报错** —— 静默失效）。要改就用**原地改写**（`sed -i` / `cat > 文件 <<'EOF'`），
改完 `docker compose exec -T nginx nginx -s reload`。
`deploy.sh` 里的 `cp src/deploy/swas/nginx.conf ./nginx/nginx.conf` 是**原地截断+写入** ⇒ 不换 inode ✓。

### 不许往回走（issue #4852）：排队的旧 run 不得把服务回退

**事故形态**（2026-09-20 生产 CI 实测）：三条部署腿共用**同一把** server 侧 `flock`
（`deploy/swas/deploy.sh`，窗口 600s）⇒ run 按**创建时刻**排队，而 `main` 在排队期间前进
⇒ **为旧 commit 创建的 run 会在更新的 run 成功之后才执行**；旧判据是「该 TAG 的镜像在不在本地」
⇒ 旧 tag 的镜像当时都在本地 ⇒ 服务被重建为旧 tag，而 **run 结论 success + 健康检查三个全 200 +
`✅ SWAS 部署成功（tag=旧tag）`** ⇒ **三重绿、零告警**，线上长期跑旧代码。

**闸门判据**（`deploy/swas/deploy.sh` 的「2.05」段，**在 flock 之内**）：

```
逐服务：target tag 是**该服务当前在跑 tag 的祖先**（提交图语义）⇒ 跳过该服务 + `::warning::`
判不出（非 sha tag / 容器没起 / API 取不到 / 分叉）                        ⇒ 放行 + `::warning::`（fail-open）
显式回滚（ALLOW_DOWNGRADE=1）                                             ⇒ 放行 + 日志写「这是显式回滚」
```

- **祖先关系 = 提交图语义**（等价于 `git merge-base --is-ancestor <target> <current>`），
  **不是**字符串比较、**不是**时间戳（tag 是 `sha-<7>`，字典序与提交序无关）。
- **实现走 GitHub compare API**（`api.github.com`，同一张提交图）而不是本地 `git`：**实测**
  服务器上 `git clone --filter=tree:0` 连 `github.com:443` **超时**，而 `api.github.com` 200/0.6s、
  `python3` 在（判据源只有一处：`DOWNGRADE_API`，可被守卫测试桩化）。
- **未认证限 60 次/小时/IP** ⇒ 一次部署内同「在跑 tag」**只查一次**（缓存）。
- **显式回滚仍能往回走**：`gh workflow run deploy-*.yml -f image_tag=<tag>`（= workflow 的 `MODE=rollback`）
  注入 `ALLOW_DOWNGRADE=1`；**#4767 的「失败即回滚」那次尝试同样带 1**（回滚本身就是往回走，
  否则新闸门会把既有护栏一起挡掉）。
- **本次实际生效 tag 逐服务一行**（`EFFECTIVE_TAG=<svc>:<tag>`，被跳过的服务也有一行，值 = 在跑的那个）
  落 `$GITHUB_STEP_SUMMARY` 并拼进部署结论行 —— 事故里那句只报**请求的** tag 的
  `✅ 部署成功（tag=…）` 正是误导源。

#### 取舍：`deploy.sh` 该不该只部署「本次变更涉及的服务」？（**本单不改**，如实登记）

现状判据 = 「该 TAG 的镜像**在不在**本地/ACR」（`docker compose pull <svc>` 成功 ⇒ 纳入 `UP_SERVICES`）。
它**其实已经是**一种「只部署本次变更涉及的服务」的弱形式：每个 deploy workflow 只构建**自己那个模块**
的镜像（`.github/workflows/deploy-admin-api.yml` 等的 `IMAGE_NAME` + paths 触发）⇒ 没改的模块在该 tag 下
**没有镜像** ⇒ pull 失败 ⇒ 被跳过。但它与「哪个模块改了」**不等价**，两类偏差：
① **同 sha 的兄弟 workflow**：一个 commit 同时改两个模块 ⇒ 两个 workflow 建出**同 tag** 的两个镜像
⇒ 后到的 run 会把两个服务都部署（同 commit、方向不会往回走 ⇒ 无害，但「谁部署了什么」变模糊）；
② **回滚 / 重放 / 手工指定 tag**：此时「镜像在不在」与「改了没改」完全无关，按模块判会**少部署**。
⇒ **结论：不加这一层。** 判据真值（「本次变更涉及哪些模块」）在**远端不可得**（远端只有 tag ⇒ 镜像），
只能由 CI 侧按 `git diff` 算完再传下去 ⇒ 新增一条跨进程契约（易漂移）、且与「失败即回滚」语义冲突；
更关键的是 **#4852 的危险方向是「往回走」，按模块判**不能**阻止往回走**（旧 run 的模块改动照样会被部署）。
本单用「不许往回走」闸门直接治危险方向，它同时覆盖回滚/重放/schedule 对账等**所有**来源。
**代价（如实登记）**：一次运行仍可能对「没改的模块」做一次**同 commit** 的重复部署（幂等、无回退风险，
只多花约一个服务的拉取时间）。

#### 上真机后怎么验证（**可执行判据**）

```bash
# ① job summary 的远端输出里看闸门结论行（CI 日志会被截断，summary 不会）
#    期望：`闸门结论：允许部署=[…] / 因「往回走」跳过=[…]` + 三条 `EFFECTIVE_TAG=<svc>:<tag>`
# ② 只读核对「线上到底是哪个 commit」（真机观测，不写任何状态）
aliyun swas-open run-command --biz-region-id cn-hangzhou --instance-id <实例> --type RunShellScript \
  --timeout 60 --name migao-ro --command-content \
  'cd /opt/migao-deploy && for s in admin-api ai-agent admin-web; do cid=$(docker compose ps -q $s); echo "$s $(docker inspect --format "{{.Config.Image}}" $cid)"; done'
# ③ 红证（自然发生，不能手工造）：连续合并造成排队 ⇒ 旧 run 排到新 run 之后
#    期望：它的 summary 出现 `DOWNGRADE_SKIPPED=<svc>:<target>:<running>` 且**没有** up -d 该服务
```

⚠️ **不要**用 `-f image_tag=<旧 tag>` 去"演练"回退 —— 那正是**显式回滚路径**（注入 `ALLOW_DOWNGRADE=1`），
必然放行，演练不出闸门。守卫测试：`tests/unit_ci_workflows/test_swas_deploy_no_downgrade.py`。

### 远端输出在哪看（**排查真因的第一步**）

`deploy.sh` 的输出在 SWAS API 里是 **base64**（`InvocationResult.Output`）。
workflow 现在**解码后**打印，并把**完整**输出写进该 job 的 **Summary**（CI 日志会被截断，summary 不会）。
⇒ **排查先看 job summary**，不要对着 base64 猜（事故里就是这么耗掉大量时间的）。

### 远端 `flock` 与"超时强杀"的关系

远端 `deploy/swas/deploy.sh` 用 `/tmp/migao-deploy.lock` + `flock` 串行化并发部署，
并有 `trap 'flock -u 9' EXIT`。**`flock(2)` 的锁挂在「打开文件描述」上**：进程以**任何方式**终止
（含 `SIGKILL`）时内核都会关闭 fd 并释放锁 ⇒ **不会留下陈旧锁**（trap 只是显式解锁的锦上添花）。
⚠️ 但要注意：**CI 侧的硬超时不会终止远端进程** —— `RunCommand --timeout 3600` 仍在跑，
锁仍被它持有（下一个部署最多等 600s 后失败退出）。这就是**超时路径不做自动回滚**的原因
（此刻回滚只会与它抢锁）；超时走"显式告警 + 本手册"。

## 验收流水线

```
Issue 创建（CONTRACT_JSON 含 business_truths + cases 引用）→ 自动生成验收草稿 (L2/L3/L4)
     → 研发 review → PR 合并
     → 自动触发双验收:
       主验收: spec + L2/L3 业务断言 + 逐用例打分（case_results）
       复核验收: DB/API 独立断言 (不看 spec, 避免合谋)
     → 双一致 + 100% → 自动 close issue
     → 不通过 → 留研发/凯总处理
```

## 关键环境变量 (GitHub Secrets)

| 变量 | 用途 |
|------|------|
| `ALIYUN_ACCESS_KEY_ID/SECRET` | 阿里云 CLI（SWAS 云助手 RunCommand + OSS） |
| `ACR_USERNAME/PASSWORD` | 容器镜像推送（CI 构建推 ACR，服务器 pull 消费） |
| `DASHSCOPE_API_KEY` | LLM API |
| `SMOKE_ADMIN_PASSWORD` | 冒烟测试登录 |
| `SMOKE_SERVICE_TOKEN` | 服务间调用 + agent-eval 评测 |

---
详见: [SWAS 迁移踩坑](../deployment/swas-migration-lessons.md) · [部署检查清单](../deployment/deployment-checklist.md)

## Danger Scan：删除 workflow 的人工确认通道（#4295）

`Danger Scan (破坏性变更检测)` 是 **required** check。它把「删除 workflow 文件」判为 BLOCK ——
但补本条之前，**没有任何记录"人工确认"的地方**（`DANGER_TRUSTED_ACTOR` 只对"新增"降级）。

⚠️ **这在本仓库会硬卡死**：分支保护开了 `enforce_admins=true`（"不允许绕过上述设置"），
它**对管理员同样生效** ⇒ 既没有 `gh pr merge --admin`，UI 也不提供 "Merge without waiting"。
实测（#4288）：`GraphQL: Required status check "Danger Scan (破坏性变更检测)" is failing.`
⇒ 在补通道前，**删除任何 workflow 在机制上都不可能合并**。

**怎么删**（owner 本人操作，两步）：

1. 在 PR 上评论一行（**必须由 owner 账号发出**；其他人的评论一律不采信）：
   ```
   /danger-ack delete-workflow .github/workflows/<要删的文件>.yml
   ```
   批量清理可用 `/danger-ack delete-workflow all`（展开为本次**全部**被删的 workflow）。
2. 重跑一次该 check（`gh run rerun <danger-scan-run-id> --failed`）。

之后该条降为 WARN，并在 `danger-scan-result.json` 的 `acks` 里留痕（谁确认的 + 确认评论链接）。

- **为什么用评论而不是 label**：`gh run rerun` **复用原始事件载荷**（标签快照是旧的），
  且 label 变更不在 `pr-check` 的 `pull_request.types` 里 ⇒ label 方案在重跑下不生效；
  评论在**运行期**读 API，故重跑能拿到最新确认。
- **fail-closed**：无删除 / 评论 API 失败 / 非 owner / 未命中 marker ⇒ ack 为空 ⇒ **仍 BLOCK**
  （无确认时的行为与补通道前**逐字相同**）。
- 判定逻辑在 `danger_scan.py` 的 `parse_delete_acks()` 纯函数里（**不在 YAML 字符串里**）——
  首版把判据写成脚本文本匹配，红证实测"不红"（空断言），故改挂到纯函数上。

## 部署后「线上一致性对账」（issue #4858）

> **本节为追加**（不改上面任何段落 —— `deploy/swas/deploy.sh` 正由 #4828 改动）。
> 腿 = `.github/workflows/post-deploy-reconcile.yml`（**独立 workflow**，定时 `17 */6 * * *` + `workflow_dispatch`）
> → `deploy/scripts/post-deploy-reconcile.sh`（判定）→ `deploy/swas/reconcile-read-remote.sh`（**只读**远端读取体）。
> 守卫 = `tests/unit_ci_workflows/test_post_deploy_reconcile.py`（删任一条判据即红）。

### 它治什么（三种「线上与 main 不一致」，两种此前**没有任何机制会发现**）

| 形态 | 实测 | 加本腿之前 | 本腿的判据 |
|---|---|---|---|
| ① 静默回退：旧 run 被 flock 排队到新 run 之后执行 ⇒ 服务回退到旧 tag | 三服务全被回退；run success + 健康检查全 200 + 脚本自称成功 = **三重绿零告警** | #4854 的「不许往回走」闸门已拦住**发生**；**事后**仍无人核对线上是哪个 commit | 容器侧「在跑 tag 是该服务最近一次改动的**祖先**」⇒ 不一致 |
| ② 静默跳过：某服务镜像拉取失败 ⇒ 远端 `⚠️ 跳过该服务`，整次部署仍报成功 | `sha-56c8c51` 那次跳过 ai-agent/admin-web（**那次合理**）；若某模块改了、镜像却没建 ⇒ 跳过 = **静默不交付** | ❌ 无 | 同上（祖先关系即「线上缺该服务最近一次改动」）+ 降级判据（镜像存在性 + 自上次成功部署以来有无改动） |
| ③ 静态副本滞后：发布腿按**路径过滤**触发 ⇒ 改动不在该路径就不跑 | 线上 `/w/src/app.mjs` 一度是旧副本，缺计件幂等修复 | ❌ 无 | 线上 `https://app.migaozn.com/w/<rel>` 的 body 哈希 vs `origin/main:frontend/worker-h5/<rel>`（**排除 `tests/**`**，与发布脚本口径一致） |

### 与 `deploy-reconcile.yml` 的**分工**（两条腿判据不同、互不替代）

- `deploy-reconcile.yml`：看 **main HEAD 的镜像在不在** + 「自上次成功部署起该服务有无改动」⇒ **补部署**（会写）。
- 本腿：看**线上实际在跑什么**（容器真身 tag + 线上静态副本逐文件哈希）⇒ **只出声，不写**（不 dispatch 任何部署）。

### 怎么读（每个判定一行依据 + 一行总结）

```
· [容器/admin-api] 一致：线上在跑 `sha-122cbac` 是该服务最近一次改动 `backend/admin-api` 的提交
  `f362d3f9c` 的**后代**（依据：提交图 `merge-base --is-ancestor f362d3f9c 122cbac` = 真）
· [静态/src/app.mjs] 一致：`https://app.migaozn.com/w/src/app.mjs` HTTP=200 · 线上哈希 `830976ae…` == `origin/main:…`
**结论**：一致=9 · 不一致=0 · 判不出=0
```

⚠️ **判据形态为什么是「提交图祖先关系」而不是「tag 字符串相等」**：部署 tag 取 `sha-${GITHUB_SHA::7}`
= **main HEAD**（各 deploy workflow 的 `Resolve image tag`），而「该有的」是**最后一个改该服务路径的提交**
⇒ HEAD 是 docs/ci 提交时两者**天然不等**（实测：admin-api 在跑 `sha-122cbac`，该服务最近一次改动是
`f362d3f9c`）。按相等判会把**常态**误报成不一致 ⇒ 判据失去判别力。

### 退出码 / fail-open 的代价（**如实登记**）

| 结果 | 行为 |
|---|---|
| 无确认的不一致（含**全部判不出**） | `exit 0`（fail-open，不阻塞）+ 判不出逐条 `::warning::` |
| 有**确认的**不一致（真的少交付了） | `exit 1`（run 红）+ `::error::` |
| 对账腿自身跑不起来（缺文件/无真值源/通道失败） | 判不出 + `::warning::`；**0 判定**时额外 `::warning::`（「没跑」不许长得像「通过」） |

**代价（已知并接受）**：判不出走 fail-open ⇒ 只读通道/公网整体不可用时，本腿**不会**阻塞任何东西，
只会出声；「判不出」与「一致」在报告里**分开计数**，但**没有任何自动机制**会在长期判不出时升级为红。

### 上真机后怎么验证（**可执行判据**）

```bash
# ① 手动对账（只读，秒级）：期望结尾 `一致=N · 不一致=0 · 判不出=0`
gh workflow run post-deploy-reconcile.yml --ref main && gh run watch
# ② 本地同一条码路（只读；需本机 aliyun CLI 已配置）
bash deploy/scripts/post-deploy-reconcile.sh
# ③ 红证：把线上 `/w/` 的某个文件改旧（或等发布腿真的没跑）⇒ 期望 exit 1 + `[静态/…] **不一致**`
#    （不要用「改 deploy.sh」演练 —— 那会真的动线上）
```
