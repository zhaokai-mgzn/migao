# TDD 铁律 — AI-TDD 强制执行规范

> ⚠️ 本规范为项目铁律，优先级高于所有其他指令。AI 在每次代码变更时必须逐条遵守，不得跳过任何检查点。

## 0. PR 合并前置条件（最高优先级）

**PR 合并前必须完成以下步骤，缺一不可：**

```
1. 重启本地服务（确保运行最新代码）
2. 运行全量单元测试
3. 运行增量集成测试（真实 LLM）
4. 运行增量 E2E 测试（Playwright）
5. 以上全部 PASS 后方可合并
```

**本地服务重启命令：**
```bash
# 1. 重启 admin-api
kill $(lsof -t -i :8081) 2>/dev/null
cd backend/admin-api && ./mvnw spring-boot:run &

# 2. 重启 ai-agent-service  
kill $(lsof -t -i :8001) 2>/dev/null
cd backend/ai-agent-service && .venv/bin/python -m uvicorn app.main:app --port 8001 --reload &

# 3. 重启 admin-web
kill $(lsof -t -i :3001) 2>/dev/null
cd frontend/admin-web && npm run dev &

# 4. 验证服务就绪
lsof -i :8081 -sTCP:LISTEN && lsof -i :8001 -sTCP:LISTEN && lsof -i :3001 -sTCP:LISTEN
```

**禁止在以下情况合并 PR：**
- ❌ 未重启本地服务（可能运行旧代码）
- ❌ 单元测试未全量通过
- ❌ 增量集成测试未运行（符合触发条件时）
- ❌ 增量 E2E 测试未运行（符合触发条件时）
- ❌ 任何测试出现 FAIL
- ❌ 服务未就绪就运行测试

## 1. 三层测试金字塔 — 缺一不可

每次代码变更必须通过以下三层验证，**禁止只跑单测就声称完成**：

```
┌──────────────────────┐
│  E2E 测试 (Playwright) │  ← 覆盖核心业务流程，真实浏览器交互
├──────────────────────┤
│  集成测试 (pytest)    │  ← 真实 LLM 调用，验证 Tool Calling 链路
├──────────────────────┤
│  单元测试 (pytest/vitest) │  ← Mock 外部依赖，验证纯逻辑
└──────────────────────┘
```

| 层级 | 触发条件 | 工具 |
|------|---------|------|
| 单元测试 | 任何代码变更 | pytest (back) / vitest (front) |
| 集成测试 | 涉及 Tool/LLM/Skill/SSE/路由 | pytest + 真实 LLM 调用 |
| E2E 测试 | 涉及前端组件/交互/SSE/用户流程 | Playwright + 本地服务 |

## 2. E2E 测试强制覆盖清单

### 2.1 必须覆盖的场景

以下场景 **必须** 有 E2E 测试，禁止只写单元测试：

| 场景类别 | 具体覆盖项 | 测试要求 |
|---------|-----------|---------|
| **新增前端组件** | 新组件渲染、交互、状态变化 | 至少 1 个渲染测试 + 1 个交互测试 |
| **交互式组件** (Choice/Confirm/Form) | 渲染、点击选项、确认/取消流程 | 至少覆盖：渲染 → 点击 → 发送消息 完整链路 |
| **流式响应** (SSE) | text/tool_call/tool_result/interactive/suggestions/done/error | 至少覆盖 3 种事件类型 |
| **核心业务流程** | 商品创建/搜索、订单创建/查询、客户管理 | 完整多轮对话链路 |
| **权限边界** | 不同角色的操作权限 | 至少覆盖 admin 和 customer 两个角色 |
| **错误处理** | 网络错误、超时、工具调用失败 | 至少 1 个异常场景 |

### 2.2 禁止的 E2E 测试模式

```
❌ 只测 "页面加载不报错" → 太简单，没有业务价值
❌ 只测 "按钮可见" → 没有覆盖交互逻辑
❌ 只用 `expect(count).toBeGreaterThanOrEqual(0)` → 弱断言，不验证实际行为
❌ 跳过真实 LLM 调用 → 必须连真实后端服务
```

### 2.3 强制的 E2E 断言模式

```
✅ 验证完整的用户操作链路：输入 → 发送 → 等待响应 → 验证内容
✅ 验证 SSE 事件类型的出现（text/tool_call/interactive/done）
✅ 验证交互组件渲染后的点击行为
✅ 验证错误场景的错误提示文本
✅ 多轮对话：验证上下文保持
```

## 3. 测试执行流程 — 7 个检查点

### CP-1：变更范围识别
```
□ 后端：admin-api / ai-agent-service
□ 前端：admin-web / mini-app
□ 涉及新组件：_____（名称）
□ 涉及 SSE 事件：_____（类型）
□ 涉及 Tool：_____（名称）
□ 涉及核心业务流程：_____（描述）
```

### CP-2：单元测试 — 先写后跑，确认失败
```bash
# 后端（增量）
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/test_xxx.py -v
cd backend/admin-api && ./mvnw test -Dtest=XxxTest

# 前端（增量）
cd frontend/admin-web && npx vitest run tests/unit/xxx.test.ts
```
必须看到 **FAIL** 才算有效测试（证明测试能捕获缺陷）。

### CP-3：单元测试 — 实现后确认通过
```bash
# 同上命令，必须看到 PASS
```

### CP-4：全量单测验证
```bash
# 后端
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/ -v
cd backend/admin-api && ./mvnw test

# 前端
cd frontend/admin-web && npx vitest run
```
**必须全部 PASS**，不允许有任何 FAIL。

### CP-5：增量集成测试（真实 LLM 调用）
```bash
# 启动本地服务后运行
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/test_e2e_mibao_scenarios.py -v
```
涉及 Tool/Skill/SSE 变更时 **必须** 跑，不可跳过。

### CP-6：增量 E2E 测试（Playwright 浏览器）
```bash
# 1. 确认本地服务运行（8081 + 8001 + 3001）
# 2. 运行相关 spec
cd tests && BASE_URL=http://localhost:3001 npx playwright test specs/xxx/xxx.spec.ts
```

**触发条件**（满足任一即必须执行）：
- [ ] 新增/修改前端组件
- [ ] 新增/修改 SSE 事件类型
- [ ] 新增/修改交互式组件（Choice/Confirm/Form）
- [ ] 变更核心业务流程（商品/订单/客户）
- [ ] 变更用户交互流程（多轮对话/引导流程）

如不涉及以上任何场景，可声明跳过并说明原因。

### CP-7：完成自检 — 逐项勾选

```
□ CP-1：已识别变更范围
□ CP-2：已写单测，确认 FAIL
□ CP-3：已实现代码，单测 PASS
□ CP-4：全量单测 PASS
□ CP-5：增量集成测试 PASS（_____个）
□ CP-6：增量 E2E 测试 PASS（_____个）
  □ 如跳过 CP-6，原因：_____
□ E2E 测试质量自检：
  □ 覆盖完整用户链路（非仅检查元素存在）
  □ 覆盖交互式组件（如有新增）
  □ 覆盖核心业务流程（如有涉及）
  □ 断言有效（非 `toBeGreaterThanOrEqual(0)` 类弱断言）
□ 代码已提交推送
```

## 4. 状态持久化验证

> 涉及 State/路由/Interact/执行循环的变更，必须在 E2E 测试中覆盖多轮对话场景（≥2 轮 graph 调用），确保跨轮 state 正确保持。

**为什么不用裸 DB 测试**：`test_pending_interact_persistence.py` 常年失败（硬编码不存在的 tenant、event loop 生命周期冲突、DB 可达性不稳定）。真实的状态丢失 bug 只有通过多轮对话 E2E 才能捕获——因为 bug 的根因在 `_build_initial_state` 未加载上一轮 state，而非 DB 读写本身。

## 5. E2E 测试开发规范

### 5.1 测试文件命名
```
tests/e2e/specs/{domain}/{feature}.spec.ts

例：
  tests/e2e/specs/chat/chat.spec.ts          — 基础聊天
  tests/e2e/specs/chat/interactive.spec.ts   — 交互组件（待创建）
  tests/e2e/specs/products/product-create.spec.ts — 商品创建
```

### 5.2 Page Object 模式
```
tests/e2e/pages/{domain}/{page}.page.ts

每个 Page Object 必须提供：
  - 元素定位器（使用 data-testid 优先，语义化备选）
  - goto() / waitForLoad() — 页面导航
  - 业务操作函数（如 fillMessage, createProduct 等）
```

### 5.3 本地 E2E 运行前检查清单
```
□ 确认 admin-api 运行在 :8081
□ 确认 ai-agent-service 运行在 :8001  
□ 确认 admin-web 运行在 :3001
□ 确认 .auth/admin.json 已生成（auth setup 通过）
□ 确认测试数据已准备（如需）
```

## 6. 违规后果

| 违规行为 | 处理方式 |
|---------|---------|
| 跳过 CP-5 集成测试 | **禁止合并 PR** |
| 跳过 CP-6 E2E 测试（满足触发条件时） | **禁止合并 PR** |
| E2E 测试只用弱断言 | **视为未完成，必须重写** |
| 新增交互组件无 E2E 覆盖 | **禁止合并 PR** |
| 只跑单测声称"完成" | **视为虚假完成，重做 CP-1~7** |
| 新增核心业务流程无 E2E | **禁止合并 PR** |

## 7. 快速命令参考

```bash
# === PR 合并前三层测试全量 ===

# L1: 单元测试（核心模块全量）
cd backend/ai-agent-service && .venv/bin/python -m pytest \
  tests/test_graph_nodes.py \
  tests/test_graph_skills.py \
  tests/test_intent_router.py -v
cd frontend/admin-web && npx vitest run

# L1-full: ai-agent-service 全量单测
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/ -v \
  --ignore=tests/test_e2e_mibao_scenarios.py

# L2: 集成测试（需先启动本地服务，真实 LLM 调用）
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/test_e2e_mibao_scenarios.py -v

# L3: E2E 测试（需本地服务全启动）
cd tests && BASE_URL=http://localhost:3001 npx playwright test specs/chat/chat.spec.ts --reporter=list

# === 本地服务启动 ===
# 1. admin-api:    cd backend/admin-api && ./mvnw spring-boot:run
# 2. ai-agent:     cd backend/ai-agent-service && .venv/bin/python -m uvicorn app.main:app --port 8001 --reload
# 3. admin-web:    cd frontend/admin-web && npm run dev
```

## 8. E2E 测试铁律（2026-06-20 实战教训总结）

> 经历 101→22 失败、7 轮修复、3 次回退后的经验法则。

### 8.1 前端变更必须同步更新 E2E

| 前端变更类型 | E2E 必须做的事 |
|-------------|---------------|
| 页面 UI 重构（卡片/图表/布局） | 重写对应 spec 的断言和选择器 |
| API 路由变更（加 `/admin/` 前缀等） | 更新 mock `page.route()` pattern |
| 组件替换（recharts→内联 SVG 等） | 更新 locator（`recharts-responsive-container`→`svg`） |
| 按钮改图标（文字→SVG） | `getByText('编辑')`→`getByTitle('编辑')` 或 `getByRole('button', { name: '编辑' })` |
| 删除功能/面板 | 删除对应测试，不留死代码 |
| AuthProvider 新增 API 调用 | 补 `page.route('**/api/auth/me')` mock |

**铁律**：修改前端代码时，必须同时 grep 对应的 E2E spec 并更新。不允许"先改前端，E2E 后面再说"。

### 8.2 auth.setup.ts 修改必须本地 + CI 双验证

| 规则 | 说明 |
|------|------|
| 禁止仅验证 CI 通过 | CI 用真实 SMS token，本地用 mock token，行为不同 |
| 修改后必须清缓存重跑 | `rm -f e2e/.auth/admin.json && npx playwright test --project=auth-setup` |
| injectAuth 方案已被证明不可靠 | `page.evaluate` 设置 `document.cookie` + `localStorage` 无法保证 Zustand 水合时序。**优先用 `addCookies` + `addInitScript`** |
| mock token 场景必测 | `E2E_MOCK_AUTH=true` 是本地默认值，必须能过 |

### 8.3 禁止批量 sed 脚本修改 spec 文件

**2026-06-20 教训**：用 sed 批处理 18 个文件的 import 导致：
- JSDoc 注释首行 `/**` 被截断为 `*`
- `import { test, expect }` 被误删
- 重复 import 导致语法错误
- 176 failed（比修之前更差）

**铁律**：
- 修改 spec 文件必须逐个读取、逐个编辑
- 每个 spec 的 import 结构、beforeEach 签名、缩进风格不同
- 批量操作后用 `grep -rn "import { test, expect }" specs/` 校验

### 8.4 CI 失败定位流程

```
1. 先查 auth-setup 是否通过（auth-setup 失败 → 级联所有测试）
2. 看错误类型分布（strict mode / element not found / timeout）
3. strict mode → getByText 匹配了 sidebar 导航项，改用 getByRole
4. element not found → 页面可能重定向到 /login，检查 /api/auth/me mock
5. timeout → mock 路由可能没拦截到（检查 /admin/ 前缀）
```

### 8.5 E2E 选择器优先级

```
1. getByRole('heading', { name: '...' })   # 页面标题
2. getByRole('button', { name: '...' })    # 按钮
3. getByRole('columnheader', { name })     # 表头
4. getByTitle('...')                        # 图标按钮（无文字）
5. getByLabel('...')                        # 表单字段
6. getByText('...', { exact: true })       # 唯一文本
7. locator('.class').filter({ hasText })    # 限定作用域
8. getByText('...').first()                 # 最后手段
```

**禁止**：裸 `getByText('短词')` 用于包含 sidebar 的页面（`分类管理`、`订单管理`、`客户` 等会匹配到 sidebar 导航链接）。

### 8.6 提交前自检

```
□ 本次前端变更涉及哪些页面？对应的 E2E spec 是否已更新？
□ auth.setup.ts 是否有改动？是否已清缓存本地验证？
□ 新增/修改的 mock route 是否匹配实际 API 路径（含 /admin/ 前缀）？
□ 是否使用了 getByText 短词？在 sidebar 页面需改用 getByRole
□ 是否批量修改了 spec 文件？是否已逐个文件校验 import 完整性？
```
