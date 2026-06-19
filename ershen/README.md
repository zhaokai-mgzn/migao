# 二郎神 (Erlang Shen)

米高项目 Quality Loop Engineering 体系。

> **天眼**看穿 mock · **哮天犬**独立嗅探 · **守门神将**不放行

## 一句话

人定义业务真值 → AI 全链路自驱动：issue → draft → TDD → PR → Gate → verify → close → grow

## 架构

```
军师 (OpenClaw)           Agent (Claude Code)         CI (GitHub Actions)
─────────────────        ─────────────────────        ───────────────────
调度 · 判定 · 汇报         写码 · TDD · 验收             Gate (测试文件存在性)
junshi-poll.sh           agent-poll.sh                pr-check.yml
case_draft.py            dev-agent.md                 QA Growth Gate
quality_report.py        verify-agent.md
learn.py
```

## 三层验证

| 层 | 机制 | 防什么 |
|----|------|--------|
| Gate | 检查测试文件是否存在 | 偷懒不写测试 |
| 主验收 (primary) | E2E + pytest + JUnit | 测试跑不过 |
| 复核 (reviewer) | 独立 API + expect 规则 | mock 欺骗 |

## 目录

```
ershen/
├── README.md           ← 本文件
├── ARCHITECTURE.md     ← 架构设计
├── loop-spec.md        ← Loop 规格（状态机 + 契约）
├── templates/          ← 验证模板（8 个业务领域）
│   ├── order-classify.yml
│   ├── dashboard-jump.yml
│   └── ...
├── contracts/          ← 契约格式定义
│   └── AI-Contracts.md
└── handbook.md         ← 部署运维手册
```

## 生长维度

1. **关键词自生长** — 从 reviewer manual 断言中学习新业务领域
2. **模板自生长** — 检测 auto_asserts < truths_count 自动补充
3. **规则自生长** — primary=pass + reviewer=fail → Gate 收紧

## 相关链接

- 部署手册: `docs/junshi-handbook.md`
- Agent 指令: `.claude/agents/dev-agent.md`
- 验收 Agent: `.claude/agents/verify-agent.md`
- 项目铁律: `CLAUDE.md` + `.claude/skills/tdd-iron-law.md`
