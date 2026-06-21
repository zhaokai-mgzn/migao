# 10 — 进化体系

二郎神通过 3 层机制持续进化：L1 即时修复、L2 模式反思、L3 结构演进。

## 三层进化矩阵

| 层级 | 频率 | 执行者 | 职责 |
|------|------|--------|------|
| **L1 即时** | 每 5min | agent-poll | REJECT→重 draft, HOLD×3→熔断, CI fail→修复 |
| **L2 模式** | 每天 2:00 | OpenClaw pattern-reflect | REJECT/HOLD 聚类, 模板自修 |
| **L3 结构** | 每周 | 军师 + 人工 | CLAUDE.md 更新, 新规则创建, 架构调整 |

## L1 即时修复

### agent-poll 自愈循环
```
CI fail → needs-changes → dev-agent 修复 → push → CI re-run
最多 3 次 → 熔断 → block/need-human
```

### verify-poll 自愈循环
```
验收 fail → block → agent-poll 修复 → 新 PR → CI → merge → 重新验收
HOLD×3 → 死循环检测 → block/need-human
```

## L2 模式反思 (pattern-reflect)

OpenClaw `junshi-pattern-reflect` cron (每天 2:00):

### 聚类分析
```
1. 扫描最近 7 天的 REVIEW_JSON reject
2. 扫描最近 7 天的 VERDICT_JSON block/hold
3. 按模板类型分组
4. 同一模板 + 同一失败原因 ≥ 3 次 → 触发自动修复
```

### 自动修复策略

| 失败模式 | 自动修复 |
|---------|---------|
| 模板 case 不完整 (缺 L3/L4) | 补全模板 YAML 的 `coverage_requirements` |
| E2E spec pattern 不匹配 | 更新 QA Growth Gate 规则 |
| Agent 反复犯同一类错误 | 更新 `.claude/agents/*.md` 的 prompt |
| 覆盖率持续不达标 | 创建 process-improvement issue |

### 无法自动修复 → escalate
- 创建 `junshi-error` + `process-improvement` issue
- 需要人工分析的新型失败模式

## L3 结构演进

### learn 归档 (junshi-learn-archive)
每周日 3:00 执行:
1. 扫描 `/opt/junshi/metrics/` 的指标历史
2. 归档到 `/opt/junshi/archive/YYYY-MM/`
3. 清理 `ai-verify/pending` 超 30 天的 issue

### CLAUDE.md 自进化
由 `.claude/skills/claude-md-management` 驱动:
- 会话结束后自动检测学习要点
- 增量更新 CLAUDE.md
- 版本号同步到 `.claude/settings.json`

### 模板自修
`docs/verification-templates/` 目录:
- `frontend-fix.yml` — 前端 Bug 修复模板
- `backend-fix.yml` — 后端 Bug 修复模板
- `fullstack-fix.yml` — 全栈修复模板
- pattern-reflect 可自动补全模板的 `coverage_requirements` 字段

## 覆盖率进化

### coverage-track 每日追踪
OpenClaw `junshi-coverage-track` (每天 6:00):
```
1. 运行覆盖率报告
2. 对比上次 → 计算 Δ
3. Δ > 0 → 评论 parent issue
4. 新文件无覆盖 → 创建 coverage-gap 子 issue
5. 创建 qa-todo label 的子任务
```

### coverage-tracking 生命周期
```
parent issue (coverage-tracking: "模块 < 60%")
  ├─ 子 issue 1-N (coverage-gap + qa-todo)
  │   └─ agent-poll 处理 → 补测试 → PR → merge
  └─ 全部子 issue close → parent close
```

## 进化约束

- **禁止删历史**: learn 只归档不删除
- **可审计**: 所有自动修改有 git commit history
- **可回滚**: 模板自动修改在 PR 中执行 (人工可 review)
- **熔断保护**: 同模板 ≥5 次自动修改失败 → 停止自修，人工介入
