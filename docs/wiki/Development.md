# 开发指南

## AI-TDD 流程

强制 Red→Green→Refactor，7 检查点缺一不可：

| CP | 步骤 | 动作 |
|----|------|------|
| 1 | 识别范围 | 列出受影响模块+测试文件 |
| 2 | Red | 先写测试，运行确认 FAIL |
| 3 | Green | 最小实现，测试 PASS |
| 4 | Refactor | 重构，测试保持 PASS |
| 5 | 单测全量 | 受影响模块全量单测 |
| 6 | 集成+E2E | 增量集测 + E2E + tsc |
| 7 | 自检 | 逐项勾选确认 |

**PR 合并前置**: 重启本地服务 → 全量单测 PASS → 增量集测 PASS → 增量 E2E PASS。缺一不可。

## 分支/Commit

```
feat/<scope>-<desc>    # scope: frontend/backend/ai-agent/qa/infra
fix/<scope>-<desc>
chore/<scope>-<desc>
```

Commit: `feat(frontend): 描述` / `fix(backend): 描述` / `test:` / `refactor:` / `docs:` / `chore:`

禁止 push main，必须 PR + 关联 Issue (`Fixes #xxx`)。

## 测试分层

| 层 | 工具 | 覆盖要求 |
|----|------|---------|
| admin-api 单测 | JUnit 5 + MockMvc + TestContainers | 核心 Service ≥80% |
| ai-agent 单测 | pytest + httpx | 核心 Tool ≥80% |
| admin-web 单测 | Vitest + Testing Library | 关键页面 100% |
| E2E 冒烟 | Playwright (tests/smoke/) | 核心流程 100% |

## 安全

- 密钥走环境变量，不硬编码
- JWT RS256 非对称签名
- 所有业务表有 tenant_id，查询必须过滤（从 JWT 取）
- CORS 仅允许已知域名

## 🎯 AI 验收体系（项目生命线，2026-06-16 凯总明确）

**所有交付（人/AI 员工/军师）必须遵守的铁律**：

### 1. 任何功能/Bug 先开 issue
- 用 `.github/ISSUE_TEMPLATE/feature.md` 或 `bug.md`
- 自动加 `needs-verification` label

### 2. 业务真值用业务语言（凯总 11:54 明确）
- ✅ "含加工待发货 = 状态为待发货 且 含加工项"
- ❌ "SELECT COUNT(*) ..."（技术）

### 3. 军师反推 case 草稿 → 研发 review
- 提交 issue 后 1-5 分钟，军师自动评论 L2/L3/L4 草稿
- 研发可改/删/补，**草稿不是命令**

### 4. PR 合 main → 双验收自动跑
- 主验收：跑 spec + L2/L3 业务断言
- 复核验收：DB/API 独立断言（**不看 spec**，避免合谋）
- 双一致 + 100% → 自动 close
- 不通过 → 留研发/凯总

### 5. 5 层兜底
1. 置信度评分
2. 双验收一致性
3. 业务真值独立断言
4. 凯总/娜总抽样
5. commit hash 追溯

### 6. 禁止
- ❌ 跳过 issue 直接写代码
- ❌ 业务真值用技术语言
- ❌ 研发拒绝 review 草稿
- ❌ 凯总/娜总人为验收（除非 block/override）
- ❌ 军师写业务 case 终稿

### 参考
- 模板库：`docs/verification-templates/`
- 使用手册：`docs/verification-handbook.md`
- 研发流程：`docs/case-review-workflow.md`
- 详情见 issue #450 v3.1
