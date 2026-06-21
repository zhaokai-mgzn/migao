# 03 — CI 工作流 (GitHub Actions)

## 总览

| # | Workflow | 触发 | 职责 | 机械/LLM |
|---|----------|------|------|----------|
| 1 | `pr-check.yml` | PR → main | 安全门禁 + 单测 + Growth Gate + E2E | 机械 |
| 2 | `e2e-web.yml` | PR → main | Playwright E2E 全量 | 机械 |
| 3 | `e2e-real.yml` | PR → main | AI Agent 真实验收测试 | 混合 |
| 4 | `junshi/verify-trigger` | PR closed (merged) | 贴 VERIFY_TRIGGER + reopen | 机械 |
| 5 | `junshi/case-draft` | issue opened/labeled | 无 draft? → needs-draft | 机械 |
| 6 | `junshi/redraft` | issue_comment created | REJECT/SUPPLEMENT → 打 needs-draft | 机械 |
| 7 | `issue-contract-check` | issue opened | 检查 CONTRACT_JSON | 机械 |
| 8 | `smoke-test.yml` | workflow_call | P0 冒烟测试 (pytest) | 机械 |
| 9 | `deploy-admin-api.yml` | push main (admin-api/**) | 部署 admin-api 到 SAE | 机械 |
| 10 | `deploy-admin-web.yml` | push main (admin-web/**) | 部署 admin-web 到 OSS+CDN | 机械 |
| 11 | `deploy-ai-agent-service.yml` | push main (ai-agent/**) | 部署 ai-agent-service 到 SAE | 机械 |
| 12 | `bash-syntax-check.yml` | push | bash 语法检查 | 机械 |
| 13 | `mini-app.yml` | PR | 小程序编译检查 | 机械 |

## 1. PR Check (`pr-check.yml`)

**触发**: `pull_request → main` | `workflow_dispatch`
**权限**: `contents: read` + `pull-requests: write`

### Job 1: block-env-files
- 检查 diff 中是否有 `.env` / `.env.*` 文件 (`.env.example` 除外)
- 有 → exit 1

### Job 2: admin-api-test
- `./mvnw test` 全量单测
- `check-jacoco-coverage.sh`: 变更文件覆盖率 ≥80%

### Job 3: admin-web-test
- `npx tsc --noEmit` 类型检查
- `npx vitest run` 单测全量

### Job 4: qa-growth-gate
- 扫描 PR diff 中每个文件
- 根据文件路径匹配规则：
  - `backend/*/controller/*.java` → 需 MockMvc 测试
  - `backend/*/service/*.java` → 需 JUnit 单测
  - `frontend/*/components/*.tsx` → 需 E2E 点击链路
  - `frontend/*/app/*` → 需 E2E spec + anti-placeholder
  - `backend/*/entity/*.java` / `dto/*.java` → warn: 需 API contract
  - 测试文件/文档/SQL → auto-pass
- **BLOCKERS > 0** → `gh pr edit --add-label "junshi-review/needs-changes"` + exit 1
- **failure()** → 兜底打标签

### Job 5: e2e-web (separate workflow)
- Playwright 全量 E2E 测试
- 失败 → 创建 `[E2E Web] 测试失败` issue

## 4. verify-trigger (`junshi/verify-trigger.yml`)

**触发**: `pull_request: closed` (merged only, `if: github.event.pull_request.merged == true`)

**逻辑**:
```bash
ISSUE_NUM=$(echo "$PR_BODY" | grep -oP '(Fixes|Closes|Resolves)\s+#\K\d+' | head -1)
# 贴 VERIFY_TRIGGER comment (含 JSON metadata)
# gh issue edit "$ISSUE_NUM" --add-label "ai-verify/pending"
# reopen if closed
```

## 5. case-draft (`junshi/case-draft.yml`)

**触发**: `issues: opened, edited, labeled`
**动作**: issue 有 CONTRACT_JSON 但无有效 DRAFT_JSON → `gh issue edit --add-label "needs-draft"`

## 6. redraft (`junshi/redraft.yml`)

**触发**: `issue_comment: created`
**动作**: 评论含 REJECT/SUPPLEMENT → 隐藏旧 DRAFT (OUTDATED) → `gh issue edit --add-label "needs-draft"`

## 7. issue-contract-check (`issue-contract-check.yml`)

**触发**: `issues: opened`
**动作**: issue body 无 CONTRACT_JSON 且非 skip_template → `gh issue edit --add-label "needs-truths"`

## CI 失败自愈链路

```
任一 CI job 失败
  → pr-check.yml "Label needs-changes on any failure" step
  → gh pr edit --add-label "junshi-review/needs-changes"
  → agent-poll 扫描 → dev-agent 修复 → git push
  → 新的 commit 触发重新 CI
```
