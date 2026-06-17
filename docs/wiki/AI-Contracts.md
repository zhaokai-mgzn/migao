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

---

## 契约：研发 Review（Phase 1 Gate）

> Agent 在写码前**必须**完成 Review，贴 REVIEW_JSON 评论。不通过不进 Phase 2。

### 格式

```html
## ✅ Review 通过 / ❌ Review 不通过 / ➕ 补充 case

<!-- REVIEW_JSON
{
  "action": "accept | reject | supplement",
  "issue_id": 100,
  "reason": "case 覆盖全部 2 条业务真值",
  "additions": []
}
-->
```

### 三种动作

| action | 含义 | Agent 下一步 |
|--------|------|-------------|
| `accept` | case 覆盖全、真值清晰 | 进入 Phase 2 TDD 写码 |
| `reject` | case 与真值矛盾 / 真值不清 | **停止**，等军师修正 |
| `supplement` | case 不全 | 补充后进入 Phase 2 |

### reject 示例

```html
## ❌ Review 不通过

L2 case 1 覆盖的是"无加工订单"，但业务真值要求"含加工待发货订单"。
请军师修正 case 草稿。

<!-- REVIEW_JSON
{"action":"reject","issue_id":100,"reason":"L2 case 1 与业务真值不符","additions":[]}
-->
```

---

## 军师验收执行（⑥⑦ 合并）

> 验收由军师直接在服务器执行，不经过 Agent。

```
PR merge → deploy 完成 →
  军师检测 →
    挂 ai-verify/pending →
    直接跑验收脚本（不经过 Agent/Claude Code）：

    cd /opt/youke
    python3 scripts/dual_verify/primary.py <issue_id>
    python3 scripts/dual_verify/reviewer.py <issue_id>
    python3 scripts/dual_verify/merge.py <issue_id>

    merge.py 自动：
      pass → gh issue close + verified/auto
      block → BLOCK_LOG 评论 + 重打 needs-verification
      hold → hold/auto-fail
```

Agent 不参与验收。军师验收完成后贴 AI验收报告评论即可。

---

## 验收执行（⑥⑦）

> Agent 执行验收脚本。原因：E2E real + 集成测试需要连接云服务，只有 Agent 服务器有完整测试环境（localhost 服务 + DB 连接 + Playwright）。

```
PR merge → deploy 完成 →
  军师检测 →
    挂 ai-verify/pending →
    评论: <!-- VERIFY_TRIGGER {"issue_id":N} -->

Agent 扫到 VERIFY_TRIGGER（无 VERIFY_RESULT）→
  确认服务 alive →
  python3 primary.py → reviewer.py → merge.py
  （直接 shell 执行，不走 Claude Code）

merge.py 自动 close/block/hold + 贴 AI验收报告评论
```

---

## ⚠️ 第二步是质量命门

> 军师 case 草稿的质量直接决定整条链的 block 率。
> 草稿不准 → Agent 写歪 → 验收 block → 反复打回 → 熔断。

### 军师出 case 必须满足

```
1. 每条业务真值 → 至少 1 个 L2 单测 case
2. 每条业务真值 → 至少 1 个 L4 独立断言（reviewer 能自动验证）
3. 涉及前端交互 → 至少 1 个 L3 E2E case
4. case 描述必须可执行（Agent 能直接翻译成代码，不需要再猜）
```

### 不合格 case 示例（会导致 Agent reject）

```
❌ "测试订单状态正确"           → 太模糊，什么叫正确？
❌ "验证系统行为符合预期"       → 不可执行
❌ "SELECT * FROM orders..."   → 带了 SQL，违反业务语言铁律
```

### 合格 case 示例

```
✅ "含加工项 + 状态待发货 → 订单列表显示'待发货'标签"
✅ "租户A创建的商品 → 租户B搜索不到"
✅ "输入手机号13800138000 + 验证码123456 → 登录成功，跳转首页"
```

### 军师自检清单（发 DRAFT_JSON 前逐条确认）

```
□ 所有业务真值都有对应 case 覆盖
□ 每个 case 可被 Agent 直接翻译成测试代码
□ L4 断言能用 DB/API 自动验证（不是 manual）
□ 没有 SQL/API 技术细节泄露到 case 中
□ 模板匹配正确（8 种业务模式至少命中 1 种）
```

---

# 军师自进化手册

> 质量数据全部可追溯、可衡量。每个 issue 的评论链记录了全生命周期数据，军师定期跑质量报告即可识别改进方向。

## 质量源头：第二步 Case 草稿

### 硬 Gate 机制

```
case_draft.py 发草稿前必须通过 quality_gate：

  auto_asserts >= truths_count  → 通过，正常发稿
  auto_asserts <  truths_count  → 拒绝发稿，返回错误信息
  真值数为 0                     → 拒绝发稿
```

拒绝示例：
```
- 🔴 **拒绝发稿**: L4自动断言(1) < 业务真值(3)
  缺少自动验证的真值会导致 reviewer 无法验收 → block 率 100%
  请为每条真值补充 DB/API 验证方式后重试。
```

### 8 个模板 + 关键词匹配

| 模板 | 最小命中 | 关键词 |
|------|---------|--------|
| dashboard-jump | 2 | 看板跳转、待发货数、含加工订单数、低库存数 |
| order-classify | 2 | 订单分类、8个分类、6个状态、含加工订单 |
| product-sku-stock | 1 | SKU库存、库存汇总、低库存阈值 |
| customer-list | 1 | 客户列表、客户详情、客户搜索 |
| aftersales-flow | 1 | 售后工单、售后状态、退款 |
| auth-sms | 1 | 短信登录、验证码登录、注册 |
| employee-role | 1 | 员工列表、角色权限、岗位 |
| knowledge-ai | 2 | 知识库文档、知识库检索、AI回答 |

### Reviewer 自动验证覆盖（25+ 关键词）

reviewer.py 的 `infer_business_asserts` 根据业务真值关键词自动生成 DB/API 断言，覆盖所有 8 种模板：

- **dashboard-jump**: 含加工待发货 / 含加工订单数 / 低库存 / 卡片数据 / 跳转URL
- **order-classify**: 状态分类 / 分类计数 = 列表总数
- **product-sku-stock**: SKU库存聚合 / 低库存
- **customer-list**: 客户搜索 / 客户订单数 / 租户隔离
- **aftersales-flow**: 售后状态流转 / 售后列表
- **auth-sms**: 短信登录 / 密码登录已禁用 / 注册
- **employee-role**: 员工列表 / 角色权限
- **knowledge-ai**: 知识库文档 / AI客服回答

> 未命中任何关键词的真值 → 兜底标 `manual` → merge 时自动 `hold`（不 block），等军师补充 SQL。

## 可追溯数据

每个 issue 的评论链记录了全流程：

| 评论类型 | JSON 块 | 记录内容 |
|---------|---------|---------|
| Case 草稿 | `DRAFT_JSON` | 模板、真值数、L4 自动覆盖率、spec 路径 |
| Agent Review | `REVIEW_JSON` | accept / reject / supplement + 原因 |
| 验收报告 | `VERDICT_JSON` | primary/reviewer 状态 + 置信度 + 冲突 |
| 打回日志 | `BLOCK_LOG` | block_depth、失败 spec、冲突原因 |

merge.py 自动写 `block-rate.jsonl`，每次 block 事件一行。

## 军师自检：跑质量报告

```bash
cd /opt/youke
python3 scripts/dual_verify/quality_report.py --days 7
```

输出示例：
```
## 总览
| **block 率** | 2/10 (20%) |
| **close 率** | 7/10 (70%) |
| 平均置信度    | 93%        |
| Agent reject 率 | 1/10 (10%) |
| L4 有人工断言   | 2          |

## 模板维度
| 模板             | 总数 | block率 | L4自动覆盖率 |
| dashboard-jump   | 3    | 33%     | 67%          |
| order-classify   | 5    | 0%      | 100%         |

## 改进建议
- dashboard-jump block率 33% — 请review该模板的reviewer_asserts
- 2 个 issue 有 L4 人工断言 — 请补充自动验证方式
```

## 改进闭环

```
质量报告 → 识别弱项（哪个模板 block 率高？哪个 L4 缺自动断言？）
       → 军师修正模板或补充 reviewer_asserts
       → 下一轮 case 质量提升 → block 率下降
       → 再跑报告验证
```

## 军师自检节奏

- **每 7 天**：跑 quality_report.py，看 block 率趋势
- **block 率 > 30%**：暂停新 issue，修正模板 + reviewer 关键词
- **某个模板 block 率 > 50%**：该模板 reviewer_asserts 需重写
- **Agent reject 率 > 30%**：case 草稿质量需提升（更具体、更可执行）
- **熔断 (≥3 次)**：真值本身可能有歧义，需凯总/娜总澄清

目标：**block 率 < 15%，close 率 > 80%，Agent reject 率 < 10%，L4 人工断言 = 0**。
