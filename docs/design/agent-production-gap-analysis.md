# Agent 生产级差距分析（2026-09-09）

> 目标：把「米宝/小布达到生产级」从主观判断变成可度量、可迭代的工程闭环。
> 数据来源：生产评测（local_runner normal 档 × 最新 main）、人工复盘（sess_7f27/sess_50ff，
> regression-mibao/sess-20260908-order-aftersales-review.md）、验收协议（docs/testing/acceptance-protocol.md）。
> 本文件是路线图：每轮落地一项，用评测基线验证进步。

## 一、现状基线（生产，2026-09-08 评测 + 09-09 复测）

| 指标 | 值 | 说明 |
|---|---|---|
| normal 档通过率 | 28/73（38%） | 2026-09-08 生产评测；大量「复现型回归」 |
| 均分 | 53% | 断言命中率（工具调用 vs 期望） |
| 写操作类失败 | ~12 条 | AS-006/007、CT-002、CH-019、CU-003/004、FN-001/004、HR-002/003/005 |
| 只读查询类失败 | 少量 | DA-003（工具选择等价）、PP-002（等价变体） |
| 评测基础设施 | 曾崩溃 | snapshot_product 遇非 JSON 响应 → 整个评测中断（本轮已修） |
| **09-09 复测（最新 main，修复 runner 后）** | **31/72（43%），均分 56%** | 27 条失败，失败根因分类见下 |
| **09-09 二测（#3031+#3032+#3124 上线后）** | **33/72（46%），均分 56%** | 28 条失败；DA-003/PP-002/CU-002 修复（+2），无新增回归 |

**二测（修复上线后）关键结论**：

| 类别 | 数量 | 代表 | 说明 |
|---|---|---|---|
| 多轮引导冗长/重复查询（写工具未达） | ~14 | OR-009/010/011/015、PR-008/014/015/016/019、CH-010/019 | agent 在引导流程里反复 product_detail/category_manage 3-4 次，消耗轮次，预设轮次内走不到写工具（P2-6 系统性问题，非单点 bug） |
| action 选错（list/tree 而非 create） | ~5 | HR-002/003/005、CT-002 | 意图路由到域正确，写 action 被 LLM 选成只读 |
| 评测数据脱节（mock id 不符真实） | ~2 | PR-010(product_id=1)、OR-006(ORD-20260701-0001) | case 用测试数据 id，生产无此记录 |
| 确认-执行链（复杂多步） | 少量 | AS-006/007 | #3031 已修简单链，换货/售后复杂多步仍有残留 |

**核心洞察（二测固化）**：三个修复（#3031 确认链、#3032 卡片契约、#3124 路由）都是
正确的点修，但「写工具未达」的大头（下单/建品/售后/人事 ~14 条）是**多轮引导流程
系统性冗长**——agent 在同一流程里反复查询已查过的数据（product_detail ×4、
category_manage ×4），消耗轮次、走不到终点。这是 Phase 3 的主攻，不能用点修补，需要
跨 prompt 层的「复用已查数据」系统规则。

**评测数据脱节（二测新增发现，独立于 agent 能力）**：
- PR-010：expectation 硬编码 `product_id: "1"`（mock 值），真实 agent 正确返回 UUID ——
  断言矛盾（data_checks 写「来自第2轮结果」，expectation 却写死 "1"）。已校准为语义值。
- OR-006：测试订单 `ORD-20260701-0001` 在生产不存在（API 实测 found: 0）——case 假设
  固定订单存在，无 seed 机制。应改为「先 order_create 测试单再流转」，属 case 重构待办。

**09-09 复测失败根因分类（27 条）**：

| 类别 | 数量 | 代表 | 说明 |
|---|---|---|---|
| 写工具未达（引导链断/卡澄清轮） | ~14 | PR-019、OR-011、FN-001、CH-019 | agent 多轮澄清/引导后未走到写工具（product_manage/order_create/finance_api） |
| action 选错（list 而非 create） | ~5 | HR-002、CT-002 | 意图路由到域正确，但写 action 被 LLM 选成只读（employee_manage list、category_manage tree） |
| 工具等价漂移（评测过严） | ~4 | DA-003、PP-002、PP-005 | 期望工具/action 与实际合法变体不等价（order_query vs dashboard_stats） |
| infra/连接 | ~2 | OR-009、CU-004 | 网络瞬断 |
| 确认-执行链 | 少量 | AS-006/007 | 换货/售后复杂多步场景，写工具在确认后仍未执行 |

**关键认知**：评测失败 ≠ 全是能力缺陷。分三类：
1. **评测资产过严/漂移**（§14.2）：断言期望的工具/轮次与 LLM 合法行为不符（DA-003 期望
   dashboard_stats 实际 order_query 等价；OR-009 期望 5 轮实际 6 轮）→ 校准 case；
2. **真实行为缺口**：写操作执行链不稳、多轮效率低（P2-6 重复查询）、能力边界误宣
   （P0-4 general prompt 静态「不可用工具」清单）→ 修 agent；
3. **基础设施问题**：评测 runner 健壮性（本轮已修）、生产评测干扰（CU-004 连接失败）。

## 二、已确认的真实缺口（按影响排序）

### P0-A 评测基建：runner 非 JSON 响应崩溃（本轮已修 ✅）
- 现象：normal 全量评测中途 snapshot_product 遇 400 HTML → JSONDecodeError → 评测中断，
  后续用例全部未跑，基线拿不到。
- 修复：`_safe_json` 防御 + 所有 `.json()` 调用点接入（local_runner.py）。
- 验证：`test_agent_eval_runner.py::TestJsonParseDefense` 5 例（红→绿）。

### P0-B final_text 正向关键词断言缺失（本轮已修 ✅）
- 现象：验收协议 §3.4 要求「正向关键词 + 反模式禁词表」双轨，runner 只有 forbidden_text
  （反模式），防不住「该说的没说」（写操作完成不声明订单号、兜底话术缺转人工出口）。
- 修复：新增 `want_text` 断言（EvalCase schema → render_cases → runner → run_case 全链路）。
- 落地用例：OR-010「返回订单号」从自然语义 data_check 升级为可执行 want_text 断言。
- 验证：`TestWantTextAssertion` 6 例（含 run_case 接入链路）。

### P1-1 确认-执行链不稳（issue #3031，open）
- 现象（9-08 复盘 sess_50ff）：用户点两次「确认创建换货工单」，agent 弹三张 confirm 卡
  从不调用 after_sales_manage(create)。根因：`pending_validated_input` 全库无实现，
  确认轮从零重走 validate+interact；压缩把「已确认」上下文摘要化。
- 当前状态：生产实测 OR-009「确认→order_create」链路已通（#3026 改善），但售后换货等
  复杂多步场景仍有重走风险；评测 AS-006/007 仍失败。
- 修复方向（issue 已列）：validate_input 通过后持久化 pending_validated_input 到
  session_states；确认轮读状态直接调写工具；压缩保留「已确认待执行」标记。

### P1-2 前端多选卡硬编码加工项文案（issue #3032，open）
- 现象：色号卡 multiSelect=true 被渲染成加工项选择器，提交「已选加工项：2699-02」。
- 修复方向：interact(choice, multiSelect) 增加 submitPrefix/submitLabel/skipLabel 字段，
  前端按字段渲染；跨端契约走 contract-check。

### P2-1 多轮效率低（REPORT P2-6）
- 现象：建品/下单时 agent 重复 product_search/product_detail 3-7 次，创建流程 2-4 分钟。
- 影响：OR-009/OR-010 评测「轮次不匹配」失败的直接原因之一（期望 5 轮实际 6+ 轮）。

### P2-2 能力边界静态声明（9-08 复盘 #4，P0-4）
- 现象：创建订单中途被 L2 分进 product 域 → agent 按 product prompt「不可用工具清单」
  宣称「订单需去后台创建」。能力边界应由工具集注册动态生成，而非 prompt 静态写下限。

## 三、路线图（按依赖顺序）

```
Phase 0  评测基建（runner 健壮性 + want_text）     ← 本轮已完成，待 PR
Phase 1  确认-执行链持久化（#3031）+ 前端卡片契约（#3032）   ← 提升「下限」
Phase 2  跨域 planner（多步任务拆解→逐域执行→汇总）        ← 提升「上限」
Phase 3  思考预算按复杂度放开 + 多轮效率（P2-1/P2-6）       ← 提升「上限」
Phase 4  能力边界动态化（P2-2）+ 评测资产校准（§14.2 漂移清单）
```

**每轮验收方式**：跑生产评测基线（local_runner normal --cases .github/cases），
对比通过率；每个修复必须带可执行 case（order_before/want_text/required_args/db_verify）
+ 旧失败会话重放验证（fail→pass）。

## 四、评测资产漂移清单（§14.2，实测校准）

| case | 期望 | 实测行为（09-09 生产） | 判定 |
|---|---|---|---|
| DA-003 | dashboard_stats(recent_orders) | order_query(list) 语义等价 | **漂移**：工具等价应放行（OR 或等价组） |
| PP-002 | processing_item_manage(list_categories) | processing_item_query 返回分类汇总 | **漂移**：工具等价应放行 |
| PP-005 | processing_item_query(applicable_category_id) | 未传筛选参数 | 真缺口：参数透传不稳 |
| OR-015 | 单轮 validate_input+order_create | agent 先 choice 卡澄清售卖方式 | **漂移**：澄清合理，放宽轮次 |
| OR-009 | 5 轮内完成 | 6 轮（R5 confirm 卡，R6 确认才 order_create） | **漂移**：轮次预设过严 |
| OR-010 | 3 轮内 validate+create | agent 多轮 product_detail+interact 澄清 | 漂移+效率：校准 + P2-6 优化 |
| HR-002 | employee_manage(create) | employee_manage(list) 被调（action 选错） | **真缺口**：意图正确但写 action 选错 |
| CT-002 | category_manage(create) | category_manage(tree) 先被调（多轮引导） | **漂移+时序**：多轮引导合法，需轮次锚定 |
| PR-019 | product_manage(create) + 规格落库 | 4 轮只到 category/interact/processing_item_query | **真缺口**：引导链未走到写工具 |
| FN-001/OR-011 | finance_api/order_create | 写工具未达 | **真缺口**：确认→执行链不稳 |

> 校准原则（migao-dev-flow §14.2）：真实重放 fail 但行为合理（LLM 合法变体）→ 放宽断言
> 或语义化；「工具等价」用 OR/等价组放行；「轮次不匹配」评估是否加轮或放宽；
> 「写工具未达」「action 选错」是真实缺口，必须修 agent（Phase 1/2）。
