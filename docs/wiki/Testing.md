# 测试体系

> **测试工程规范（文件拆分/ignore 单一来源/数据脱敏/分层归属）见 [docs/testing/test-engineering-standards.md](../testing/test-engineering-standards.md)**

# 测试策略

## 测试金字塔

```
           ┌─────────────┐
           │  E2E 冒烟    │  ← pytest (tests/smoke/), 11 文件, P0~P1
           ├─────────────┤
           │  E2E 浏览器   │  ← Playwright (tests/e2e/specs/), 30 文件, 按域组织
           ├─────────────┤
           │ 集成测试      │  ← API 端到端, 连云 dev 数据库
           ├─────────────┤
           │ 单元测试      │  ← 纯逻辑, Mock 外部依赖
           └─────────────┘
```

## 各模块测试

| 模块 | 工具 | 目录 | 覆盖要求 |
|------|------|------|---------|
| admin-api | JUnit 5 + MockMvc + Mockito | `src/test/` | 核心 Service ≥80% |
| ai-agent-service | pytest + httpx | `tests/` (unit + e2e/real) | 核心 Tool ≥80% |
| admin-web | Vitest + Testing Library | `tests/` (colocated) | 关键页面 100% |
| E2E 浏览器 | Playwright | `tests/e2e/specs/{domain}/` | 核心交互路径 |
| E2E 冒烟 | pytest + httpx | `tests/smoke/` | 核心 API 100% |

## 行为用例单一源（Case Contract，2026-08-14 起）

行为用例只存一份：`.github/cases/<domain>.yml`（18 域 117 条，block style，`truths_ref` 引用真值 ID）。以下均为**生成物，禁止手改**：
- `tests/agent_eval/eval_cases.py`（CI 跑）
- `docs/testing/mibao-verification-cases.md`（人读）

重新生成：`cd .github && python3 render_cases.py`；引用校验：`python3 truths.py check --templates templates --cases cases`（fail-closed，挂在 pr-check 的 case-truth-check job）。

**tier → CI 频率**：

| tier | 数量 | 频率 | workflow |
|------|------|------|----------|
| smoke | 9 | 每次 PR（100% 通过才合并） | pr-check `agent-eval-smoke` |
| normal | 81 | 按需手动触发 | agent-eval（local_runner.py normal） |
| adversarial | 26 | 每周六 03:00（只追踪不阻塞） | agent-eval-adversarial |

**G5 追溯铁律**：新增/修改测试文件头部必须声明 `# case_ids: OR-001, OR-002`（对应 `.github/cases/` 中的用例 ID），否则 qa-growth-gate block。存量测试未声明 → warn。

---

## E2E 测试结构 (tests/e2e/)

```
specs/
├── auth/           # login-sms, register
├── products/       # list, create, edit, detail, edit-render
├── orders/         # list, create, detail, lifecycle, ship
├── customers/      # list, detail
├── after-sales/    # list, detail
├── catalog/        # categories, processing
├── admin/          # roles, employees
├── chat/           # chat (SSE 流式)
├── dashboard/      # dashboard
├── settings/       # settings, notifications
├── quality/        # api-contract, anti-placeholder, cross-page-consistency
├── platform/       # registrations
├── smoke/          # pages-render (全页面渲染检查)
└── storage/        # oss-dual-bucket
```

## E2E 铁律

- **禁止手写 mock 数据** → 使用 Record-Replay fixture (`fixtures/*.json`)
- **强断言** → 检查 tool_result / tool_call / 数据字段，禁止仅检查可见性
- **Page Object 模式** → `pages/{domain}/{page}.page.ts`
- **新增交互组件** → 覆盖完整点击链路 (渲染→点击→发送→验证)
- **新增数据列表页** → 注册到 `quality/anti-placeholder.spec.ts` 的 `PAGES` 数组
- **新增/修改 API 字段** → 更新 `quality/api-contract.spec.ts`

## 运行命令

```bash
# admin-api 全量单测
cd backend/admin-api && ./mvnw test

# ai-agent 全量单测
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/ -v

# admin-web 全量单测 (vitest, 非 jest)
cd frontend/admin-web && npx vitest run

# E2E 增量 (对本地服务)
cd tests && BASE_URL=http://localhost:3001 npx playwright test specs/products/ --reporter=list

# 冒烟测试
cd tests/smoke && SMOKE_ENV=local pytest -m p0
```

---
详见: [E2E README](../../tests/README.md) · [米宝验证用例](../testing/mibao-verification-cases.md)
