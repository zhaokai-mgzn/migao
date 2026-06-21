# 08 — QA Growth Gate

事前测试覆盖门禁，在 PR 合并前检查每个变更文件是否有对应测试。

## 工作原理

`pr-check.yml` → `qa-growth-gate` job — 扫描 PR diff 中的每个文件，按路径匹配规则判定。

## 规则矩阵

### Java admin-api

| 文件路径模式 | 层级 | 要求 | 豁免条件 |
|-------------|------|------|---------|
| `controller/*.java` | L3 | MockMvc 集成测试 + API contract E2E | — |
| `service/*.java` | L2 | JUnit 单测 (覆盖率 ≥80%) | — |
| `mapper/*.java` | L2 | JUnit SQL 验证测试 | — |
| `security/*.java` | L2 | 安全测试 (JWT/认证流程) | — |
| `config/*.java` | L2 | JUnit 配置测试 | — |
| `exception/*.java` | L2 | 异常处理测试 | — |
| `entity/*.java` / `dto/*.java` | WARN | API contract E2E 验证新字段 | — |

### Python ai-agent-service

| 文件路径模式 | 层级 | 要求 |
|-------------|------|------|
| `app/tools/*.py` | L2+L3 | L2 单测 + L3 Real E2E |
| `app/graph/*.py` | L2 | L2 单测 |
| `app/agents/*.py` | L2 | L2 单测 |
| `app/utils/*.py` | L2 | L2 单测 |
| `app/api/*.py` | L3 | L3 集成测试 |
| `app/router/*.py` | L2 | L2 单测 |
| `app/llm/*.py` | L2 | L2 单测 |
| `app/memory/*.py` | L2 | L2 单测 |

### Frontend admin-web

| 文件路径模式 | 层级 | 要求 |
|-------------|------|------|
| `components/*.tsx` | L4 | E2E 点击链路 (渲染→点击→发送→验证) |
| `app/*` (pages) | L4 | E2E spec + anti-placeholder PAGES 注册 |
| `lib/*.ts` / `store/*.ts` | L2 | L2 单测 |

### 自动通过项

- `*/test*` / `*/tests/*` — 测试文件本身
- `*.md` / `.gitignore` / `.env.example` / `*.xml` / `*.json` / `*.lock` / `*.sql` — 配置/文档
- `docs/*` / `*.png` / `*.jpg` / `*.svg` — 文档/图片

### 信息项 (非阻塞)

| 文件路径模式 | 层级 |
|-------------|------|
| `deploy/terraform/*.tf` / `.github/workflows/*.yml` | ℹ️ 需确认 smoke test 覆盖 |

## 豁免机制

在 `.github/qa-exemptions.yml` 声明豁免 pattern：

```yaml
exemptions:
  - pattern: "backend/admin-api/src/main/java/com/migao/admin/security/*.java"
    reason: "安全模块由 CI E2E 覆盖，暂不需要单独安全测试"
    until: "2026-07-01"
```

- 支持 glob 匹配
- 安全检查：拒绝含 shell 元字符的 pattern ($ \` ; | & < >)

## 自愈闭环

```
PR Check 失败 (QA Growth Gate / 单测 / typecheck / E2E)
  → "Label needs-changes on any failure" step
  → gh pr edit --add-label "junshi-review/needs-changes"
  (需要 pull-requests: write 权限)
  → agent-poll 扫描 → dev-agent 修复 → push
```

## 覆盖率追踪

由 OpenClaw `junshi-coverage-track` (每天 6:00) 驱动：
1. 运行 `check-jacoco-coverage.sh` + `npx vitest run --coverage`
2. 模块覆盖率 < 60% → 创建 `coverage-tracking` parent issue
3. 按文件拆分子 issue (qa-growth + qa-todo)
4. 分区追踪: admin-api / admin-web / ai-agent-service

### 当前覆盖率目标

| 模块 | 当前 | 目标 |
|------|------|------|
| admin-api | ~50% | ≥60% |
| admin-web | ~19% | ≥60% |
| ai-agent-service | ~60% | ≥60% |
