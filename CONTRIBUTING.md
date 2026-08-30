# 贡献指南（Contributing Guide）

欢迎参与 MIGAO（AI 智能客服系统）！本指南面向**外部贡献者**与首次参与的开发者。内部研发流程见 [docs/wiki/Development.md](docs/wiki/Development.md)。

## 1. 项目速览

- **这是什么**：面向通用行业（示例场景：布艺窗帘）的多租户 AI 智能客服 SaaS。C 端客服"小布" + B 端工作助手"米高"双 Agent（LangGraph），Java admin-api + Python ai-agent-service + Next.js admin-web + Taro mini-app。
- **文档入口**：先读 [README.md](README.md) 了解架构与技术栈；详细文档索引见 [docs/wiki/INDEX.md](docs/wiki/INDEX.md)。
- **许可证**：[MIT](LICENSE)。参与贡献即表示同意在 MIT 条款下贡献。

## 2. 首次运行

按 [README.md 快速开始](README.md#-快速开始) 启动三组件（admin-api :8080、ai-agent-service :8000、admin-web :3001）。本地数据库/中间件使用云 dev 环境（连接信息在各模块 `.env.example` 模板中）。

## 3. 开发流程

### 3.1 从 Issue 开始

- 新功能/修复先创建 Issue（用 `.github/ISSUE_TEMPLATE/` 模板），描述清楚动机、范围与验收标准。
- 如果只是修文档或小改，可直接提 PR，但 PR 描述中仍需说明动机。

### 3.2 分支与提交

- 分支命名：`feat/<scope>-<desc>` / `fix/<scope>-<desc>` / `chore/<scope>-<desc>`；scope 取 `frontend` / `backend` / `ai-agent` / `qa` / `infra`。
- 提交信息遵循 Conventional Commits 风格：
  ```
  feat(frontend): 新增商品批量上架
  fix(backend): 修复 JWT 过期未返回 401
  test: 补充订单状态机单测
  ```
- **禁止直接 push main**，一律通过 Pull Request 合入。

### 3.3 测试是硬门槛

本项目对 PR 有自动门禁（QA Growth Gate），合入前必须满足：

1. **测试先行**：先写失败测试（Red）→ 最小实现（Green）→ 重构。
2. **单测全量通过**：改动涉及模块的全量单测必须 PASS：
   ```bash
   cd backend/admin-api && ./mvnw test
   cd backend/ai-agent-service && .venv/bin/python -m pytest tests/ -v
   cd frontend/admin-web && npx vitest run
   ```
3. **case_ids 声明**：新增/修改的测试文件头部必须声明对应的行为用例 ID（`# case_ids: OR-001`），ID 见 `.github/cases/`（否则 QA Growth Gate 会阻塞合并）。
4. **提交前自查（三把工具）**：
   ```bash
   ./verify-all.sh gate          # 与 CI 同规则的 QA 门禁预检
   ./check-ui-regression.sh      # UI 回退检测（前端改动必跑）
   ./contract-check.sh           # 三端契约一致性（跨模块改动必跑）
   ```

### 3.4 Pull Request

- 关联 Issue：PR 描述中用 `Fixes #xxx` / `Closes #xxx`。
- 按 `.github/PULL_REQUEST_TEMPLATE.md` 勾选自检清单。
- CI 全绿（含真实 LLM 冒烟评测）后由维护者合并（squash）。

## 4. 行为与安全

- 参与社区请遵守 [行为准则（CODE_OF_CONDUCT）](CODE_OF_CONDUCT.md)。
- 发现安全问题请**不要**公开披露，按 [SECURITY.md](SECURITY.md) 的流程私下报告。
- 禁止提交任何密钥/`.env` 文件（CI 有拦截门禁）。

## 5. 接受 PR 的标准

维护者会检查：功能正确性、测试覆盖（含 case_ids）、代码风格（与现有代码一致）、文档是否需要同步更新、无安全/合规风险。小步、聚焦的 PR 比大而全的 PR 更容易被快速合并。

有疑问欢迎通过 Issue 讨论。
