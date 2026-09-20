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
     3. docker compose up -d --no-deps
     4. restart nginx + 健康检查 8080/8000/3001
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
| 对账**断路器** | `deploy-reconcile.yml` | 同一 `head_sha` 的部署**已失败过** ⇒ 不再自动补部署（防止反复重试坏 commit、覆盖手工回滚）；fail-open |

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
