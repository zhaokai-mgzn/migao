# CI/CD 流水线

## 14 个 GitHub Actions 工作流

| 工作流 | 触发 | 说明 |
|--------|------|------|
| `pr-check` | PR → main | 多 job 门禁: 拦截 .env / admin-api 单测 / admin-web tsc+lint+vitest / E2E 质量门禁(4 个 fixture spec) / UI 回退检测 / QA Growth Gate(G1+G5+弱断言) / Case Contract 校验 / needs-changes 打标（**agent-eval-smoke 已于 #3653 移除**：B 端云冒烟评的是已部署 main、与本 PR 无因果；~~B 端行为信号由 agent-behavior-eval 映射用例承担~~ —— **#4275 起该 workflow 已删除，PR 上无行为信号**） |
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
- **变更门控（job 内，不整层 skip）**：`ai-agent-tests`/`mini-app` 等 required job 在 job 内用 `git diff origin/main...HEAD` 检测相关路径；无变更时实际执行 step 跳过（job 仍 success，required check 永不悬空）。**注意：不要改回 workflow 级 `paths` 过滤——required check 会卡在 "Waiting" 永不报告**（见 §3.2 技能说明）。（#4275 前此处还提到 `agent-behavior-eval.yml` 的 workflow 级 `paths` 门；该文件已删除。）
- **真实 LLM 成本**：**PR 层 = 0 次真实 LLM**（#4034 裁定 2′/4′；#4275 起 `agent-behavior-eval.yml` 整个删除，PR 上连零 LLM 映射信号也没有了）。判定走**单一入口** `post-deploy-eval`（**每周一** normal 全量 + 手动 dispatch —— #4262 用户裁定由每 3 天收紧为每周；两条每周 adversarial 定时亦已删除，改仅手动）。LLM 红例的闭环改由**确定性下沉台账**承接（`.github/llm-finding-ledger.json` + `llm_sink_check.py`，见 `docs/testing/llm-finding-sinking.md`）。
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
