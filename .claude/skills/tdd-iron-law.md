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

### 4. 快速命令

```bash
# L1: 单元测试
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/ -v
cd frontend/admin-web && npx vitest run

# L2: 集成测试
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/test_e2e_mibao_scenarios.py -v

# L3: E2E 测试
cd tests && BASE_URL=http://localhost:3001 npx playwright test --project=web
```
