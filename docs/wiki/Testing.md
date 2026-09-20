# 测试体系

> **测试工程规范（文件拆分/ignore 单一来源/数据脱敏/分层归属）见 [docs/testing/test-engineering-standards.md](../testing/test-engineering-standards.md)**

# 测试策略

## 测试金字塔

```
           ┌─────────────┐
           │  E2E 冒烟    │  ← pytest (tests/smoke/), ~~11~~ 12 文件, P0~P1
           ├─────────────┤
           │  E2E 浏览器   │  ← Playwright (tests/e2e/specs/), 30 文件, 按域组织
           ├─────────────┤
           │ 集成测试      │  ← API 端到端, 连云 dev 数据库
           ├─────────────┤
           │ 单元测试      │  ← 纯逻辑, Mock 外部依赖
           └─────────────┘
```

> 🔴 **口径订正（issue #4759，2026-09-20）**：上面金字塔里「E2E 冒烟 `tests/smoke/`」的文件数原写 **11**。
> **① 当时基线**：= **11**（原措辞保留在上一行的删除线里）。**② 后来变了**：该目录下
> `test_*.py` 实测 **12** 个（`test_01_*.py`~`test_11_*.py` 之外还有 `test_react_smartness.py`）。
> **③ 故改为 Z**：**现取 + 复算命令**（本页不写死）：
>
> ```bash
> ls -1 tests/smoke/test_*.py | wc -l   # 只数用例文件；同目录的 config.py / conftest.py / helpers.py / __init__.py 是夹具不是用例
> ```
>
> ⚠️ **口径边界**：这里数的是 `test_*.py`（**用例文件**），不是「目录下所有 `.py`」（后者含 4 个夹具文件）。
> ⚠️ **同代码块里的另一处计数本单只登记不改**：「Playwright `tests/e2e/specs/` **30 文件**」实测已 **37**
> —— 本单边界是「只改 #4759 登记的 5+1 处」，该处已在关联 PR body 登记为**同族发现**，**本单未改**
> （故那一格仍是已知过期值，勿据以当真值）。

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
| smoke | **现取**（命令见上） | ~~每次 PR（100% 通过才合并）~~ ⇒ **无自动档**（仅手动） | ~~pr-check `agent-eval-smoke`~~（该 job 已按 #3653 移除）⇒ 手动 `post-deploy-eval` 的 `workflow_dispatch` 可选 `tier=smoke` |
| normal | **现取**（命令见上） | ~~按需手动触发~~ ⇒ **每周一自动**（`post-deploy-eval` 定时档）+ 按需手动 | `post-deploy-eval`（每周一，normal 全量）/ `agent-eval`（手动，local_runner.py normal） |
| adversarial | **现取**（命令见上） | ~~每周六 03:00（只追踪不阻塞）~~ ⇒ **仅手动 `workflow_dispatch`**（定时已按 #4262 删除） | agent-eval-adversarial |

> 🔴 **口径订正（issue #4751，2026-09-20）**：本表「数量」列原写 `smoke 7 / normal 81 / adversarial 26`。
> **① 当时基线**：= **7 / 81 / 26**（原措辞保留在上表的删除线里）。**② 后来变了**：用例库逐条增长
> ⇒ 当时读数早已过期（#4751 实测当时为 **10 / 319 / 31**，另有 **1 条** `tier` 缺省 —— 见下）。
> **③ 故改为 Z**：**数量列不再写死**，改为「**现取**」（命令 = 上面那条复算命令的 `tier` 字典，
> **本页不复制第二份口径**）。⚠️ **连 #4751 自己写的「现取」读数也已再次漂移**（#4759 核清：
> `normal` 319 → **320**、总条数 361 → **362**）⇒ 这正是「不写死」的理由，**本单不再补写新数字**。
>
> 🔴 **口径订正（issue #4759，2026-09-20）——「频率」+「workflow」两列**：#4751 明说这两列
> 「未逐格复核」，本单**逐格回看 workflow 文件本体**后订正三处（原措辞保留在上表的删除线里）：
> **① `smoke`**：原写「每次 PR（100% 通过才合并）」+ workflow `pr-check agent-eval-smoke` ——
> 该 job 已按 **#3653**（2026-09-15）移除（理由：云环境不含 PR 分支代码 ⇒ 结果与本 PR 无因果；
> 锚点 = `.github/workflows/pr-check.yml` 里 gitleaks 段前的那段注释）⇒ **该档现在没有任何自动触发**，
> 只剩手动（`post-deploy-eval` 的 `workflow_dispatch` `tier` 输入可选 `smoke`）。
> **② `normal`**：原写「按需手动触发」—— 实测 `.github/workflows/post-deploy-eval.yml` 有
> `schedule: cron '0 3 * * 1'`（**每周一**；按 #4262 由「每 3 天」收紧），定时档恒跑 **normal 全量**
> （`${{ github.event.inputs.tier || 'normal' }}`，schedule 无 inputs ⇒ 回落 normal）⇒ 频率是
> 「**每周一自动 + 按需手动**」，不是「仅手动」。
> **③ `adversarial`**：原写「每周六 03:00」—— 实测 `.github/workflows/agent-eval-adversarial.yml`
> 的 `on:` **只有 `workflow_dispatch`**（每周定时已按 **#4262** 用户裁定删除：自动真实 LLM 触发
> 由 3 条收敛为 1 条）⇒ 改为「**仅手动**」。
> ✅ **「谁对」的结论（先核清再改，本单只改一边）**：**workflow 文件是权威，文档是过期副本**。
> 依据：① 定时档的**成本裁定**（#4262，用户原话「不要自动进行验证，都是重复的验证，白白消耗成本」）
> 落在 workflow 上 —— 把文档改回「每周六」= **与用户裁定相反**；② 频率是**运行期事实**，
> 只有 workflow 能证明它（`.github/workflows/**` 是唯一可执行真值源）。
> ⇒ 三处**一律改文档**，workflow **一个字节未动**（同时满足本单「禁改 `.github/workflows/**`」的边界，关联 #4717）。
> ⚠️ **`tier` 缺省 1 条**（`PG-020`，`processing-order.yml`）⇒ 三档之和 ≠ 总条数，**这是现状不是漏算**
> （核法 = 复算命令的 `tier` 字典里那个 `None` 键）。
> ✅ **该条根因已核清（issue #4759）**：`PG-020`（#4204 新增）**应落 `normal`** ——
> 同域 `PG-*` 全族（`PG-001`~`PG-041`，40+ 条）**无一例外**都是 `normal`，且形状同族
> （`skip_reason` 带 `[backend-contract]`、断言全由 Java 单测执行、不进 agent-eval 冒烟）；
> 更关键的是 `tier` 的**缺省语义本身就是 `normal`**（`.github/render_cases.py` 里
> `c.get("tier", "normal")`）⇒ **运行期行为与显式声明完全一致，缺的只是那一行声明**。
> ⛔ **本单不做（如实登记，不粉饰）**：改它必须动 `.github/cases/processing-order.yml`，而
> ① 本单文件边界明确「`.github/cases/**` 别碰」；② 触碰用例库会触发 `Case Trust Gate` 的
> **burn-down 缴费**（`scope=case_touching_prs` ⇒ 同 PR 必须**整条销账 ≥1 条**存量违规）+ 生成物重渲染，
> 属另一条专路的活 ⇒ **登记为后续小单**（预期改动 = 加一行 `tier: normal`；生成物**零变化**，
> 因为缺省已是 `normal`）。

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
