# 二郎神 (Erlang Shen) — Quality Loop Engineering v6.0

米高项目 AI 驱动的全链路质量闭环体系。

> **天眼**看穿 mock · **哮天犬**独立嗅探 · **守门神将**不放行

## 一句话

人定义业务真值 → AI 全链路自驱动：issue → draft → TDD → PR → Gate → verify → close → grow

## 架构

```
机械层 (CI + crontab)            LLM 层 (Claude Code + OpenClaw)
─────────────────────────       ─────────────────────────────
确定性操作：标签、模板评论、      理解和判断：DRAFT生成、Review、
git、语法检查、心跳告警           TDD写码、验收判定、模式反思

CI 做闹钟（事件驱动，瞬时）        LLM 做大脑（理解上下文，推理）
bash 做手臂（机械执行）            Agent 做手（写码+验收）
```

## 三层验证

| 层 | 机制 | 防什么 |
|----|------|--------|
| Gate | 检查测试文件是否存在 + Growth Gate 规则矩阵 | 偷懒不写测试 |
| LLM 验收 (verify-agent) | 调 API + check_assert.py 确定性校验 | 业务真值不通过 |
| 双独立证据 | verify-agent 与 dev-agent 完全隔离 | 自己验收自己 |

## 目录

```
ershen/
├── README.md                    ← 本文件
├── handbook.md                  ← 运维手册
├── user-handbook.md             ← 用户手册（如何参与 quality loop）
├── casebook.md                  ← 案例集（典型 issue 的处理流程）
├── case-review-workflow.md      ← Case Review 工作流
├── openclaw-migration.md        ← OpenClaw 迁移记录
├── contracts/                   ← 契约格式定义
│   └── AI-Contracts.md          ← 7 种交互契约
├── templates/                   ← 验证模板
│   └── README.md
└── design/                      ← 🆕 完整设计方案 (v6.0)
    ├── README.md                ← 总索引
    ├── 01-architecture.md       ← 架构总览
    ├── 02-roles.md              ← 角色体系
    ├── 03-ci-workflows.md       ← CI 工作流 (13 个)
    ├── 04-scripts.md            ← 执行脚本
    ├── 05-cron-jobs.md          ← 定时任务 (9 个)
    ├── 06-agent-prompts.md      ← Agent Prompt
    ├── 07-signals-and-labels.md ← 信号与标签 (18 标签 + 5 JSN)
    ├── 08-qa-growth-gate.md     ← QA Growth Gate
    ├── 09-self-healing.md       ← 自愈机制 (8 种)
    ├── 10-evolution.md          ← 进化体系 (L1/L2/L3)
    ├── 11-observability.md      ← 可观测性
    ├── 12-setup-guide.md        ← 部署指南
    └── 13-loop-engineering-comparison.md ← 与 Loop Engineering 对比
```

## 生长维度

1. **关键词自生长** — 从 reviewer manual 断言中学习新业务领域
2. **模板自生长** — 检测 auto_asserts < truths_count 自动补充
3. **规则自生长** — primary=pass + reviewer=fail → Gate 收紧
4. **覆盖率生长** — QA Growth Gate 驱动从 0% → 60% 渐进补全

## 相关链接

- 设计文档: [`design/`](design/README.md)
- 部署手册: [`handbook.md`](handbook.md)
- Agent 指令: `../.claude/agents/dev-agent.md`
- 验收 Agent: `../.claude/agents/verify-agent.md`
- 项目铁律: `../CLAUDE.md` + `../.claude/skills/tdd-iron-law.md`
