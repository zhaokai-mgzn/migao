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

行为用例只存一份：`.github/cases/<domain>.yml`（**域数与条数现取、本页不写死**；原写 ~~18 域 117 条~~ = **基线读数**，见下方口径订正注；block style，`truths_ref` 引用真值 ID）。以下均为**生成物，禁止手改**：
- `tests/agent_eval/eval_cases.py`（CI 跑）
- `docs/testing/mibao-verification-cases.md`（人读）

**现取 + 复算命令**（域数 / 总条数 / 各 tier 条数 / `skip_reason` 放行面，**一个脚本一次给全**）：

```bash
python3 -c "import sys,collections;sys.path.insert(0,'.github');from render_cases import load_case_dicts;d=load_case_dicts('.github/cases');print('域数',len({c['_domain'] for c in d}),'总条数',len(d));print('tier',dict(collections.Counter(c.get('tier') for c in d)));print('skip_reason 非空',sum(1 for c in d if str(c.get('skip_reason') or '').strip()))"
```

> 🔴 **口径订正（issue #4751，2026-09-20）**：本条原写「**18 域 117 条**」。
> **① 当时基线**：本文定稿时 = **18 域 / 117 条**（原措辞保留在上一段）。**② 后来变了**：
> 用例库被持续喂养（新增域 + 逐条补用例）⇒ 当时读数早已过期。**③ 故改为 Z**：
> **改为「现取 + 复算命令」**（上面那条命令），数字以**当次输出**为准（**本页不写死**）。
> ⚠️ 顺带订正一处**同名易混**：`registry.yml`（工具注册器域）也算一个域文件 ⇒ **域数 = 25**
> 而非「24 个 yml 去掉 README」（核法 = 上面命令的 `域数`，它按 `_domain` 去重、与文件数同源）。

重新生成：`cd .github && python3 render_cases.py`；引用校验：`python3 truths.py check --templates templates --cases cases`（fail-closed，挂在 pr-check 的 case-truth-check job）。

**tier → CI 频率**：

| tier | 数量 | 频率 | workflow |
|------|------|------|----------|
| smoke | ~~7~~ **10** | 每次 PR（100% 通过才合并） | pr-check `agent-eval-smoke` |
| normal | ~~81~~ **319** | 按需手动触发 | agent-eval（local_runner.py normal） |
| adversarial | ~~26~~ **31** | 每周六 03:00（只追踪不阻塞） | agent-eval-adversarial |

> 🔴 **口径订正（issue #4751，2026-09-20）**：本表「数量」列原写 `smoke 7 / normal 81 / adversarial 26`。
> **① 当时基线**：= **7 / 81 / 26**（原措辞保留在上表的删除线里）。**② 后来变了**：用例库逐条增长
> ⇒ 当时读数早已过期（实测现为 **10 / 319 / 31**，另有 **1 条** `tier` 缺省 —— 见下）。
> **③ 故改为 Z**：数字以**上面那条复算命令**的**当次输出**为准（**本页不写死**）。
> ⚠️ **「数量」与「频率」两列的可信度不同**：数量列已按命令现取；**频率列本单未逐格复核**
> （已知 `adversarial` 的「每周六 03:00」与 `.github/workflows/agent-eval-adversarial.yml`
> 的「**仅手动 `workflow_dispatch`**」不符 —— 关联 #4262 已删该 cron）⇒ **读频率列请回看 workflow 文件本体**，
> 本单只订正数量列（避免把未复核的口径写成真值）。
> ⚠️ `tier` **缺省 1 条**（`PG-020`，`processing-order.yml`）⇒ 三档之和 ≠ 总条数，**这是现状不是漏算**
> （核法 = 复算命令的 `tier` 字典里那个 `None` 键）。

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

### E2E 选择器优先级

```
1. getByRole('heading'/'button'/'columnheader', { name })
2. getByTitle('...')  — 图标按钮（无文字）
3. getByLabel('...')  — 表单字段
4. getByText('...', { exact: true })
5. locator('.class').filter({ hasText })
6. getByText('...').first()  — 最后手段
```

**禁止**: 裸 `getByText('短词')` 用于包含 sidebar 的页面。

### 禁止提交

- `.env` / 密钥 / 敏感配置（CI 有 block-env-files 门禁）
- 手写 E2E mock 数据（必须 Record-Replay fixture）
- 跳过测试直接写实现的代码

## QA Growth Gate — 变更类型 → 强制测试

PR 合并前，CI（pr-check qa-growth-gate）自动扫描变更文件，以下文件类型强制对应测试：

| 变更类型 | 测试要求 |
|---------|---------|
| Controller (Java) | MockMvc 集成测试 + API contract E2E |
| Service (Java) | JUnit 单测 (覆盖率 ≥80%) |
| Tool (Python) | L2 单测 + L3 Real E2E |
| Component (TSX) | E2E 点击链路 (渲染→点击→发送→验证) |
| Page (TSX) | E2E spec + anti-placeholder 注册 |

规则源：`.github/tech-stack.yml`（单一来源）；豁免：`.github/qa-exemptions.yml`；执行器：`.github/growth_gate.py`（fail-closed）。

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
