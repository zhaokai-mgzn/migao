# AI 协作契约 v2.0 — 单 Issue 全生命周期

> 军师 (GitHub) 和 Agent (服务器) 通过 issue 的**标签 + 评论 + JSON 机读块**协作。
> 一个 issue 从创建到 close 全程不换号。

## 生命周期状态机

```
        创建 issue (CONTRACT_JSON)
              │
              ▼
         needs-verification
              │
              ├── 军师检测 → case_draft → 评论 DRAFT_JSON
              │
              ├── Agent 抢 issue → TDD 写码 → PR → merge
              │
              ├── 军师检测 merge → 评论 VERIFY_TRIGGER
              │
              ├── Agent 跑验收 → primary+reviewer+merge
              │         │
              │         ├── pass → close + verified/auto ✅
              │         │
              │         └── block → +block/dual-mismatch
              │              │      +保留 needs-verification
              │              │      +评论 BLOCK_LOG
              │              │
              │              └── Agent 重新抢 → 修复 → PR → merge
              │                     │
              │                     └── 重新验收 → 循环
              │                            │
              │                            └── 3次打回 → block/need-human 🛑
              │
              └── hold → hold/auto-fail（需人工补充）
```

## 契约格式

### 1. Issue 创建 → CONTRACT_JSON（issue body 末尾）

```html
<!-- CONTRACT_JSON
{"schema_version":"1.0","type":"feature","business_truths":["条件A→结果A"],"affected_modules":["ai-agent-service"]}
-->
```

### 2. 军师反推 case → DRAFT_JSON（issue 评论）

```html
<!-- DRAFT_JSON
{"issue_id":100,"template":"order-classify","business_truths":["..."],"l2_cases":[...],"l3_specs":[...],"l4_asserts":[...]}
-->
```

### 3. 军师触发验收 → VERIFY_TRIGGER（issue 评论）

PR merge + deploy 完成后，军师发：

```html
<!-- VERIFY_TRIGGER {"issue_id":100} -->
```

Agent 扫描到后执行 primary.py → reviewer.py → merge.py（本地全链路）。

### 4. 验收结果 → VERIFY_RESULT（Agent 评论）

```html
<!-- VERIFY_RESULT
{"issue_id":100,"primary":{"status":"pass","confidence":95},"reviewer":{"status":"pass","confidence":92},"merge_decision":"close"}
-->
```

### 5. 打回日志 → BLOCK_LOG（merge.py 自动评论）

```html
## ⚠️ 验收 Blocked（第N/3次）

<!-- BLOCK_LOG
{"block_depth":2,"failed_specs":["tests/..."],"conflicts":["主通过复不通过"]}
-->
```

### 6. Agent 完成 → COMMENT_JSON（Agent 评论）

```html
## 🤖 研发 Agent 完成  PR: #123
<!-- COMMENT_JSON {"from":"claude-code-agent","intent":"pr_submitted","issue_id":100,"pr_number":123,"tests_pass":true} -->
```

## 标签状态机

| 标签 | 谁打 | 含义 | 下一步 |
|------|------|------|--------|
| `needs-verification` | 创建时 | 等军师出 case / Agent 开发 / Agent 修复 | Agent 抢 |
| `block/dual-mismatch` | merge.py | 验收不一致 | Agent 优先抢 + 修复 |
| `block/need-human` | merge.py(熔断) | 打回≥3次 | 凯总/娜总介入 |
| `hold/auto-fail` | merge.py | 双方都失败 | 研发补充 |
| `verified/auto` | merge.py | 验收通过 | 闭环 |

## Agent 扫描优先级

```
1. block/dual-mismatch + needs-verification  → 验收被阻，立即修复
2. needs-verification (有 DRAFT_JSON 评论)   → 新功能/Bug，开始写码
3. VERIFY_TRIGGER 评论 (无 VERIFY_RESULT)    → 跑验收
```

## 铁律

- **一个 issue 走到底**，不创建子 issue
- **所有交互带 JSON 机读块**，不靠自然语言猜
- **军师不跑验收脚本**，只发 VERIFY_TRIGGER + 读 VERIFY_RESULT
- **Agent 跑全链路验收**，merge.py 在服务器本地执行
- **3 次打回熔断**，block_depth 从 BLOCK_LOG 评论累计

---

## 标签完整规范（对齐军师体系）

### 全流程状态 → 标签映射

```
阶段                    issue 标签                  PR 标签 (军师)

① Issue 创建           needs-verification          —

② Agent 抢 issue        needs-verification          —
   (assign @me)

③ Agent 开 PR           needs-verification          junshi-review/pass-with-followups
                         (issue 保持)               (军师自动评审通过 → 允许 merge)

④ PR merge              needs-verification          junshi-review/* → 移除
                         ai-verify/pending          (merge 后 PR 标签失效)

⑤ Agent 跑验收          ai-verify/pending          —
   (primary+reviewer    
    +merge)

⑥ 验收 pass             verified/auto              —
                       (merge.py close issue)

⑥ 验收 block            block/dual-mismatch         —
                       + needs-verification
                       (Agent 重新抢)
                       + BLOCK_LOG 评论

⑥ 验收 hold             ai-verify/hold              —
                       (等云/缺信息/需人工)

⑦ 3次打回熔断           block/need-human            —
                       + block/dual-mismatch
                       - needs-verification 移除

⑧ 部署类 issue          ai-verify/skip-deployment   —
                       (等 cloud verify)
```

### 军师在 PR 阶段的操作

```
Agent 开 PR →
  军师检测 →
    CI 全绿 + Fixes #xxx 齐全 + E2E 有覆盖
      → 挂 junshi-review/pass-with-followups ✅
      → PR 可 merge
    
    CI 红 / 缺测试 / 缺 E2E
      → 挂 junshi-review/needs-changes
      → PR 不能 merge → Agent 需修复后重新 push
    
    业务逻辑改动需人类审批
      → 挂 junshi-review/blocked
      → 等凯总/娜总
```

### 军师在验收阶段的操作

```
PR merge + deploy 完成 →
  军师发 VERIFY_TRIGGER →
    Agent 开始验收 →
      军师挂 ai-verify/pending
      
      Agent 完成验收 →
        军师读 VERIFY_RESULT:
          pass → merge.py 已自动 close + verified/auto
          block → 同 issue 重打 needs-verification
          hold → ai-verify/hold (军师挂)
```

### 标签汇总

| 标签 | 层级 | 含义 | 谁挂 |
|------|------|------|------|
| `needs-verification` | issue | 待军师出case/Agent开发/修复 | 创建时自动 |
| `ai-verify/pending` | issue | 验收进行中 | 军师(PR merge后) |
| `ai-verify/hold` | issue | 验收暂停(等云/缺信息) | 军师 |
| `ai-verify/skip-deployment` | issue | 部署类等云验收 | 军师 |
| `verified/auto` | issue | 验收通过已close | merge.py |
| `block/dual-mismatch` | issue | 验收不一致 | merge.py |
| `block/need-human` | issue | 熔断需人工 | merge.py |
| `hold/auto-fail` | issue | 双方验收都失败 | merge.py |
| `junshi-review/pass-with-followups` | PR | 评审通过 | 军师 |
| `junshi-review/needs-changes` | PR | 评审需改 | 军师 |
| `junshi-review/blocked` | PR | 评审阻塞 | 军师 |

---

## PR → Merge 时序（军师自动合）

```
Agent push PR
  → CI 自动跑 (pr-check: 单测+QA Growth Gate)
  → CI 全绿 + Fixes #xxx 齐全 + E2E 有覆盖
      → 军师检测 → 挂 junshi-review/pass-with-followups → merge
  → CI 红 / 缺测试
      → 军师检测 → 挂 junshi-review/needs-changes → Agent 修复后 push → CI 重跑
  → deploy (GitHub Actions, ~3min)
  → 军师检测 deploy 完成 → 挂 ai-verify/pending → 发 VERIFY_TRIGGER
```

军师合并条件：
- CI 全部绿（6 个 required checks）
- PR body 有关联 issue（Fixes/Closes #xxx）
- 前端改动有对应 E2E spec

以上全部满足 → 自动 merge，不需要人类点按钮。
