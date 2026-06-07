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
kill $(lsof -t -i :8080) 2>/dev/null
cd backend/admin-api && ./mvnw spring-boot:run &

# 2. 重启 ai-agent-service  
kill $(lsof -t -i :8001) 2>/dev/null
cd backend/ai-agent-service && .venv/bin/python -m uvicorn app.main:app --port 8001 --reload &

# 3. 重启 admin-web
kill $(lsof -t -i :3001) 2>/dev/null
cd frontend/admin-web && npm run dev &

# 4. 验证服务就绪
lsof -i :8080 -sTCP:LISTEN && lsof -i :8001 -sTCP:LISTEN && lsof -i :3001 -sTCP:LISTEN
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
# 1. 确认本地服务运行（8080 + 8001 + 3001）
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
□ L0：状态持久化集成测试 PASS（涉及 State/路由/Interact/执行循环时必跑）
  □ 如跳过，原因：_____（必须说明）
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

## 4. AI Agent Service 状态持久化集成测试（强制）

> ⚠️ 涉及以下模块的变更，**必须** 运行 `test_pending_interact_persistence.py`：
> - `execute_skill` / `base_skill.py`（Tool Calling 循环）
> - `_build_initial_state` / `customer_service_agent.py`（State 构建）
> - `route_by_intent` / `nodes.py`（路由逻辑）
> - `session_memory.py`（session 状态管理）
> - `interact` tool 相关
> - 任何新增 State 字段

### 4.1 为什么需要这个测试

**历史教训**：`pending_interact_skill` 机制初版实现了 state 内标记，但 `_build_initial_state` 每次创建全新 state，**从未加载上一轮的值**。整个会话连续性机制形同虚设，多轮交互必定失败。这个 bug 在 Mock 单测中无法发现（mock 不会暴露 state 丢失问题）。

```
❌ 单测 Mock：execute_skill 返回 pending_skill → assert 通过 → 但 state 实际被丢弃
✅ 集成测试：execute_skill → 读 DB 验证 → assert pending_skill 真实存在
```

### 4.2 必须覆盖的验证点

| 验证点 | 测试方法 | 说明 |
|--------|---------|------|
| State 字段持久化到 DB | `test_set_and_get` | set 之后能从 DB 读回 |
| State 字段从 DB 加载 | `test_flow_persistence` | 下次 graph 调用能加载 |
| 清除机制正确 | `test_clear` / `test_no_interact_clears_db` | 流程结束后清除 |
| 覆盖写入 | `test_overwrite` | 多次 set 不产生脏数据 |
| 多会话隔离 | `test_multiple_sessions_independent` | 不同 session 互不干扰 |
| execute_skill 同步更新 DB | `test_interact_writes_to_db` | 执行路径上的 DB 写入确实发生 |

### 4.3 运行命令

```bash
# 前置条件：确认 dev DB 可达（RDS 白名单含本机 IP）
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/test_pending_interact_persistence.py -v

# 如 DB 不可达：添加本机 IP 到 RDS 白名单
# aliyun rds ModifySecurityIps --DBInstanceId pgm-bp1p7w92k81ob5to \
#   --SecurityIps "115.196.136.12,$(curl -s ifconfig.me)" \
#   --DBInstanceIPArrayName dev_local --ModifyMode Cover --region cn-hangzhou
```

### 4.4 ai-agent-service 全量单测快速命令

```bash
# 包含状态持久化测试在内（连接真实 dev DB）
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/ -v \
  --ignore=tests/test_e2e_mibao_scenarios.py \
  --ignore=tests/test_e2e_chat_flow.py \
  --ignore=tests/test_e2e_full_chain.py

# 仅核心测试（路由 + skill + 持久化，快速反馈）
cd backend/ai-agent-service && .venv/bin/python -m pytest \
  tests/test_graph_nodes.py \
  tests/test_graph_skills.py \
  tests/test_intent_router.py \
  tests/test_pending_interact_persistence.py -v
```

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
□ 确认 admin-api 运行在 :8080
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
| 跳过 L0 状态持久化测试（满足触发条件时） | **禁止合并 PR**，历史多次因 state 不持久化导致交互流程中断 |
| 只跑单测声称"完成" | **视为虚假完成，重做 CP-1~7** |
| 新增核心业务流程无 E2E | **禁止合并 PR** |

## 7. 快速命令参考

```bash
# === PR 合并前三层测试全量 ===

# L0: 状态持久化集成测试（涉及 State/路由/Interact 必跑，连接真实 dev DB）
cd backend/ai-agent-service && .venv/bin/python -m pytest \
  tests/test_pending_interact_persistence.py -v

# L1: 单元测试（核心模块全量）
cd backend/ai-agent-service && .venv/bin/python -m pytest \
  tests/test_graph_nodes.py \
  tests/test_graph_skills.py \
  tests/test_intent_router.py \
  tests/test_pending_interact_persistence.py -v
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
