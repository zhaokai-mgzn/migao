# AGENTS.md — MIGAO（AI 智能客服系统）

> DSH（DeepSeek Harness）会话的仓库级入口。开发前先读本文件；Claude Code 会话走
> [CLAUDE.md](CLAUDE.md)（本文件是其 DSH 面向的索引式视图，规则同源）。

## 这是什么

面向布艺行业的多租户 AI 智能客服 SaaS：C 端小布 + B 端米宝双 Agent（LangGraph），
Java admin-api + Python ai-agent-service + Next.js admin-web + Taro mini-app。

## 改代码前（铁律）

1. **测试先行**：先写失败测试（Red）→ 最小实现（Green）→ 重构。全量单测必须 PASS。见 [CLAUDE.md](CLAUDE.md) 的 AI-TDD CP-1~CP-7。
2. **三把工具**：提交前跑 `./verify-all.sh gate`（与 CI 同规则）、`./check-ui-regression.sh`（UI 回退）；跨模块改动加 `./contract-check.sh`。
3. **case_ids**：新增/修改测试文件头部必须声明 `# case_ids:`（对应 `.github/cases/` 用例，否则 CI QA Growth Gate block）。
4. **GitHub 操作**：禁止直推 main，必须走 PR 且关联 Issue。

## 按场景找文档（先查索引，按需 Read）

| 场景 | 入口 |
|---|---|
| 全部场景索引 | [docs/wiki/INDEX.md](docs/wiki/INDEX.md) |
| 铁律全文 / 验证命令清单 | [CLAUDE.md](CLAUDE.md) |
| 测试工程规范（拆分/ignore/脱敏/分层） | [docs/testing/test-engineering-standards.md](docs/testing/test-engineering-standards.md) |
| CI/CD / 部署 | [docs/wiki/CI-CD.md](docs/wiki/CI-CD.md) |
| 行为用例单一源 | `.github/cases/`（改后必须跑 `render_cases.py` 并提交生成物） |

## 环境

- 本地只启 3 组件：admin-api(:8080) + ai-agent-service(:8001) + admin-web(:3001)；DB/Redis 用云 dev
- DSH 专用技能：`migao-dev-flow`（三把工具/提交流程）、`tdd-iron-law`（质量铁律）——由「米高研发」preset 自动加载
