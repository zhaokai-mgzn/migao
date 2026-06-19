# 军师 OpenClaw 改造清单

> 二郎神体系中，军师（OpenClaw）需要改造的部分。其余保持不动。

## 改造总览

```
┌─────────────────────────────────────────────────┐
│              需要改造 (OpenClaw)                   │
│                                                 │
│  junshi-poll.sh ───→ OpenClaw 内部 cron          │
│  case_draft.py   ───→ OpenClaw LLM 理解           │
│  learn.py --grow ───→ OpenClaw LLM 生长分析        │
│  quality_report  ───→ OpenClaw 日报生成            │
│  crontab 管理    ───→ OpenClaw 原生调度            │
│                                                 │
├─────────────────────────────────────────────────┤
│              保持不动                              │
│                                                 │
│  agent-poll.sh       Agent 调度 (机械)            │
│  primary.py          主验收 (机械)                │
│  reviewer.py         复核验收 (expect验证)         │
│  merge.py            合并判定 (规则)              │
│  pr-check.yml        QA Growth Gate (CI)         │
│  验证模板 YAML        数据结构                    │
│  dev-agent.md        Agent 指令                  │
│  verify-agent.md     Agent 指令                  │
└─────────────────────────────────────────────────┘
```

---

## 改造一：junshi-poll.sh → OpenClaw 内部 cron

**现状**: 外部 crontab 每 3 分钟执行 bash 脚本  
**目标**: OpenClaw 内部 cron 替代，LLM 理解替代 sed/grep

### OpenClaw 需要实现的 6 个定时任务

| # | 频率 | 任务 | OpenClaw 实现方式 |
|---|------|------|------------------|
| 1 | 3min | 扫新 issue → case_draft | LLM 读 issue，判断领域，选模板，生成草稿 |
| 2 | 3min | 扫 PR → auto merge | LLM 检查 CI 状态 + issue 关联 → gh pr merge |
| 3 | 3min | 扫 merged PR → VERIFY_TRIGGER | LLM 检测 deploy 状态 → 发触发评论 |
| 4 | 3min | 巡检 stale (>3天) | LLM 识读 issue 状态 → 评论催促 |
| 5 | 3min | 巡检 hold (>7天) | LLM 判断升级 → 改 label |
| 6 | 19:00 | 质量日报 | LLM 调用 quality_report.py 并追加到日报 issue |

### 仍调用的机械脚本

OpenClaw 在以上任务中仍需调用这些 Python 脚本（它们保持不变）：

```bash
$PYTHON scripts/dual_verify/quality_report.py --days 7    # 生成日报数据
gh issue list / gh pr list / gh issue comment ...           # GitHub 操作
```

---

## 改造二：case_draft.py 关键词匹配 → LLM 理解

**现状**: 硬编码 TEMPLATES 字典 + 关键词计数匹配（只扫前 500 字符）  
**目标**: OpenClaw LLM 直接读 issue，理解业务领域，匹配或建议模板

### OpenClaw 需要做的

1. 读取 issue 标题 + body
2. 理解业务领域（LLM 推理，不需要关键词字典）
3. 浏览 `docs/verification-templates/` 目录
4. 判断：
   - 匹配到已有模板 → 按模板生成 L2/L3/L4 草稿
   - 未匹配 → 提取领域关键词 → 创建 "新建模板" issue
   - 匹配但 asserts 不足 → 创建 "补充模板" issue
5. 以 DRAFT_JSON 格式贴到 issue 评论

### 可以删除的代码

`case_draft.py` 中以下函数不再需要：
- `match_template()` — LLM 替代
- `extract_domain_keywords()` — LLM 替代
- `TEMPLATES` 字典 — LLM 自己读模板目录
- `quality_gate()` 中的关键词匹配逻辑 — LLM 自行判断
- `auto_patch_template()` — 已禁用，可清理

保留的部分（仍供 OpenClaw 调用）：
- `extract_truths()` — 机械提取 CONTRACT_JSON
- `count_auto_asserts()` — 机械统计
- `load_template()` — 加载 YAML

---

## 改造三：learn.py 生长分析 → LLM 深度分析

**现状**: learn.py --grow 用正则分析 keyword gaps，创建 issue  
**目标**: OpenClaw LLM 分析 QA 结果，深度理解模式，生成更精准的生长建议

### OpenClaw 需要做的（每天一次）

1. 读 `/opt/qa-results/` 最新结果
2. 分析 reviewer.json 中 manual 断言模式
3. 分析 primary=pass + reviewer=fail 的 mock 欺骗案例
4. 分析 block 率趋势
5. 创建精准的生长 issue（关键词补充、模板完善、Gate 收紧）

### 可以删除的代码

`learn.py` 中以下函数不再需要：
- `scan_manual_assertions()` 
- `find_keyword_gaps()` 
- `detect_template_gaps()` 
- `detect_mock_deception()` 
- `cmd_grow()` 中的规则判断逻辑
- `CURRENT_KEYWORD_COVERAGE` 字典

保留：
- `scan_real_cases()` — 机械扫描
- `cmd_scan()` / `cmd_stats()` — 统计输出
- `load_rules()` / `save_rules()` — learned_rules.json 管理

---

## 改造四：日报 → OpenClaw 日报 Agent

**现状**: junshi-poll.sh 在 19:00 调用 quality_report.py  
**目标**: OpenClaw 定时触发，LLM 分析 quality_report.py 输出的数据，生成可读报告，追加到日报 issue

### OpenClaw 需要做的

1. 每天 19:00 触发
2. 调用 `$PYTHON scripts/dual_verify/quality_report.py --days 7`
3. LLM 阅读输出，生成可读摘要
4. 追加到 `#日报 issue` 评论

---

## 改造五：外部 crontab → OpenClaw 原生调度

**删除这些 crontab 条目**:

```
*/3 * * * * junshi-poll.sh        # → OpenClaw 3min timer
7 */4 * * *  learn.py --scan      # → OpenClaw 4h timer  
7 3 * * *    learn.py --grow      # → OpenClaw daily timer
```

**保留**:
```
*/5 * * * *  agent-poll.sh        # Agent 调度不动
```

---

## 不变的部分（Agent 侧）

这些完全不动，OpenClaw 不涉及：

| 组件 | 原因 |
|------|------|
| `agent-poll.sh` | Agent 机械调度，crontab 保留 |
| `primary.py` | 跑 E2E + pytest，纯机械 |
| `reviewer.py` | API 调用 + expect 验证，纯机械 |
| `merge.py` | 规则判定 close/hold/block |
| `pr-check.yml` | CI 中检查测试文件 |
| 验证模板 YAML | 数据结构，Agent 修改 |
| `dev-agent.md` | Agent 指令 |
| `verify-agent.md` | Agent 验收指令 |
| `CLAUDE.md` | 项目铁律 |

---

## Agent 与 OpenClaw 的接口

OpenClaw 通过以下方式指挥 Agent：

```
OpenClaw 发 GitHub Comment          Agent 检测并执行
─────────────────────────          ─────────────────
DRAFT_JSON 评论                    agent-poll.sh 抢 issue
VERIFY_TRIGGER 评论                 agent-poll.sh 跑验收
补充/新建模板 issue (qa 标签)       agent-poll.sh 抢模板任务
BLOCK_LOG 评论                     agent-poll.sh 修复 block
```

Agent 完成后，结果写入：
- `PR body (Closes #xxx)` — OpenClaw 自动 merge
- `VERIFY_RESULT 评论` — OpenClaw 读验收结果
- `REVIEW_JSON 评论` — OpenClaw 了解 review 决策
