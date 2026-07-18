# 二郎神质量铁律 — 项目补充规范

> ⚠️ TDD 流程由 Superpowers `test-driven-development` + `verification-before-completion` 技能强制执行。
> 本文档仅定义二郎神特有的质量门禁补充。

## Superpowers 标准流程

研发 Agent 启动时必须依次加载：
- `/test-driven-development` — Red → Green → Refactor 循环 + CP-1~CP-7
- `/verification-before-completion` — 提交前自检
- `/github-ops` — Issue/PR/Label 操作规范
- `/dispatching-parallel-agents` — 并行任务派遣

## 二郎神特有补充

### 1. QA Growth Gate 门禁

PR 合并前，CI 自动扫描变更文件。以下文件类型强制对应测试：

| 变更类型 | 测试要求 |
|---------|---------|
| Controller (Java) | MockMvc 集成测试 + API contract E2E |
| Service (Java) | JUnit 单测 (覆盖率 ≥80%) |
| Tool (Python) | L2 单测 + L3 Real E2E |
| Component (TSX) | E2E 点击链路 (渲染→点击→发送→验证) |
| Page (TSX) | E2E spec + anti-placeholder 注册 |

### 2. E2E 选择器优先级

```
1. getByRole('heading'/'button'/'columnheader', { name })
2. getByTitle('...')  — 图标按钮（无文字）
3. getByLabel('...')  — 表单字段
4. getByText('...', { exact: true })
5. locator('.class').filter({ hasText })
6. getByText('...').first()  — 最后手段
```

**禁止**: 裸 `getByText('短词')` 用于包含 sidebar 的页面。

### 3. 禁止提交

- `.env` / 密钥 / 敏感配置
- 手写 E2E mock 数据（用 Record-Replay fixture）
- 跳过测试直接写实现的代码

### 4. AI 代码变更反模式（业务真值补充）

> 以下是二郎神实际踩过的坑，每次变更涉及以下模式时必须额外检查。

#### 4.1 CSS 布局类：className prop 覆盖组件默认布局

**场景**：组件有默认的 `flex-col`（垂直堆叠），调用方传入 `className="flex"` 作为 prop。

**坑**：`cn()` 底层用 `tailwind-merge`，同 class group 中后者覆盖前者。
`cn('flex flex-col ...', 'flex')` → `flex-col` 被覆盖成 `flex`（水平），布局完全错乱。

**真值断言**（E2E 级）：
```
组件 data-testid 的两个子区域 rect.top 差 > 10px（垂直排列），而非 rect.left 差 > 10px（水平排列）
```

**修复规则**：
1. 传入 `className` prop 时明确需要的方向语义（如 `flex-row` / `flex-col`），不依赖默认值
2. 或用 `!flex-col`（important 修饰符）防止被覆盖

**实例**：PR #1405 — `MibaoChatPanel` 外层 `flex-col` 被 ChatPage 的 `className="flex"` 覆盖

#### 4.2 组件迁移：机械搬运 className 不理解语义

**场景**：重构时把 `<div className="flex">` 换成 `<Wrapper className="flex">`。

**坑**：原 `<div>` 的 `flex` 是让它自己的子元素水平排列。换到 `<Wrapper>` 后变成 Wrapper 外层布局方向，与 Wrapper 内部的子元素布局逻辑**完全无关**。

**真值断言**（CR 级）：
```
传入 Wrapper 的 className 是否与 Wrapper 自身的默认 className 有同 group 冲突？
✓ 用 tailwind-merge 文档确认合并后结果
```

#### 4.3 Tailwind class group 冲突速查表

| 危险组合 (先 → 后) | twMerge 结果 | 视觉后果 |
|-------------------|-------------|---------|
| `flex-col` → `flex` | `flex` (row) | 垂直布局变水平 |
| `flex-row` → `flex-col` | `flex-col` | 水平布局变垂直 |
| `p-4` → `p-0` | `p-0` | padding 消失 |
| `rounded-lg` → `rounded-none` | `rounded-none` | 圆角消失 |
| `bg-white` → `bg-transparent` | `bg-transparent` | 背景消失 |
| `text-sm` → `text-lg` | `text-lg` | 字号变大 |

> **铁律**：传入组件 prop 的 className 中包含 Tailwind class 时，必须检查是否与组件默认 className 在同一 class group 中冲突。

### 5. 快速命令

```bash
# L1: 单元测试
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/ -v
cd frontend/admin-web && npx vitest run

# L2: 集成测试
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/test_e2e_mibao_scenarios.py -v

# L3: E2E 测试
cd tests && BASE_URL=http://localhost:3001 npx playwright test --project=web
```
