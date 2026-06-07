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
