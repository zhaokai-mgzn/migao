# AGENTS.md — MIGAO（AI 智能客服系统）

> DSH（DeepSeek Harness）会话的仓库级入口。开发前先读本文件，再按需查阅 docs/wiki/INDEX.md 定位规范页。

## 这是什么

面向布艺行业的多租户 AI 智能客服 SaaS：C 端小布 + B 端米宝双 Agent（LangGraph），
Java admin-api + Python ai-agent-service + Next.js admin-web + Taro mini-app。

## 改代码前（铁律）

1. **测试先行**：先写失败测试（Red）→ 最小实现（Green）→ 重构。全量单测必须 PASS。见 [docs/wiki/Development.md](docs/wiki/Development.md) 的 TDD 检查点。
2. **三把工具**：提交前跑 `./verify-all.sh gate`（与 CI 同规则）、`./check-ui-regression.sh`（UI 回退）；跨模块改动加 `./contract-check.sh`。
3. **case_ids**：新增/修改测试文件头部必须声明 `# case_ids:`（对应 `.github/cases/` 用例，否则 CI QA Growth Gate block）。
4. **GitHub 操作**：禁止直推 main，必须走 PR 且关联 Issue——**PR body 必写 `Closes #<issue号>`**（GitHub 只在 body 含 Closes/Fixes/Resolves 关键词时自动关 issue，标题里的「(issue #xx)」不生效；漏写合并后 issue 不会自动关闭，CI `pr-issue-link` 会打 `needs-issue-link` 标签提醒；无 issue 关联的基建 PR 标 `N/A（基建）`）。详见 `migao-dev-flow` 技能 §2.2/§3.3。合并后 GitHub 异步关闭偶发失效（close-on-merge best-effort，实证 #2910/#2919 未自动关）→ `close-linked-issues.yml` 会解析 body 关键词做合并后补偿关闭（issue #2937），无需人工；若 issue 仍悬挂再按 §2.2 人工兜底。

## 按场景找文档（先查索引，按需 Read）

| 场景 | 入口 |
|---|---|
| 全部场景索引 | [docs/wiki/INDEX.md](docs/wiki/INDEX.md) |
| 开发流程 / 验证命令清单 | [docs/wiki/Development.md](docs/wiki/Development.md) |
| 测试工程规范（拆分/ignore/脱敏/分层） | [docs/testing/test-engineering-standards.md](docs/testing/test-engineering-standards.md) |
| CI/CD / 部署 | [docs/wiki/CI-CD.md](docs/wiki/CI-CD.md) |
| 行为用例单一源 | `.github/cases/`（改后必须跑 `render_cases.py` 并提交生成物） |

## 环境

- 本地只启 3 组件：admin-api(:8080) + ai-agent-service(:8001) + admin-web(:3001)；DB/Redis 用云 dev
- DSH 专用技能：`migao-dev-flow`（三把工具/提交流程）、`tdd-iron-law`（质量铁律）——由「米高研发」preset 自动加载
