# 验收报告 加工单功能 2026-09-12 被测版本 dfb0fe6b

## 结论

**有条件通过（Conditional Pass）**：L1 机器断言全覆盖且全绿（状态机/联动/守卫/幂等/快照/租户隔离/前端渲染），CI 全绿（含 Agent Eval smoke 生产档）。

- **复核 AI 独立抽查发现 1 个 P1 缺陷（agent 发货路径绕过加工单守卫）→ 已修复并重放验证**（详见「复核验收抽验」节，修复前 3 个发货测试全绿未捕获该绕过）
- 剩余 **2 项覆盖缺口**：P1-1 米宝 LLM 行为无真实对话 transcript 与可执行评测用例；P2-1 真实浏览器 UI 旅程未执行 → 补齐后可达「验收通过」
- 本次**不下「验收通过」结论**；P1 缺陷修复已由回归测试与 verify-all 重放闭环

## 验收矩阵

| 对象 | 断言 | 档位 | 结果 | 证据 |
|---|---|---|---|---|
| S1 生成加工单 | 生成→订单 producing + 快照五要素 | L1 | ✅ | R1 generateSuccess |
| S1 快照 | 含 options / 不含销售价 | L1 | ✅ | R1 `doesNotContainKey("price")` + options |
| S1 幂等 | 重复生成拒绝 | L1 | ✅ | R1 generateDuplicateRejected + V43 partial unique index |
| S1 条件化 | 无加工项不生成 | L1 | ✅ | R1 generateWithoutProcessingRejected |
| S2 状态机 | issue/start/complete + 非法流转 + completed 冻结 | L1 | ✅ | R1 |
| S2 守卫 | 含加工项禁直跳 shipped | L1 | ✅ | R1 shippedRejected |
| S2 联动 | 取消回退 / 订单取消自动作废/拦截 | L1 | ✅ | R1 |
| S2 约束 | cancel 必填原因 | L1 | ✅ | R1+R3 |
| S3 工具注册 | 三工具注册 + intent 路由 | L1 | ✅ | R3 PG-012 |
| S3 对话行为 | LLM 正确调用工具产出卡片 | **L2** | ❌ 未执行 | 缺真实会话 transcript（问题 P1-1） |
| S4 前端区块 | 生成/操作/复制全部/打印 | L1 | ✅ | R4（组件+页面测试+tsc） |
| S4 真实浏览器 | 打印 CSS 排版/遮挡/写操作可见性 | **L2** | ❌ 未执行 | 缺浏览器证据（问题 P2-1） |
| S5 会话复核 | 开发期无真实会话遗留 | L1 | ✅ | R5 未采集段说明 |

## 问题清单

| 级别 | 问题 | 证据 | 处置 |
|---|---|---|---|
| P1-1 | 米宝加工单 LLM 行为无真实对话 transcript，且无 agent-eval 可执行用例（PG-001~012 均 skip_reason=单测验证，§14.1 新功能必补 LLM 行为用例未做） | processing-order.yml 各 case skip_reason；无 R 轮 transcript | 补 PG-013（LLM 冒烟档，含 order_before/db_verify）→ 真实对话重放验证有效性 → 关联 issue |
| P2-1 | 前端加工单区块未做真实浏览器 UI 旅程走查（协议 §2.3 + dev-flow §15 要求，CI E2E/vitest 不替代浏览器证据） | 无截图/几何证据产出 | 起本地服务走查四类必查项，补证据 |
| P2-2 | 对话内 document 交互卡未实现（设计文档已标注 P2） | processing-order-design.md 第七节 | 后续排期 |

## 复核验收抽验（独立 AI 视角，零人工）

复核 AI（独立 subagent，未接收本剧本、未修改任何文件，仅凭代码/测试事实）结论：

- 总体判定：**有条件通过**（修复前不建议盖章）
- 抽验「生成加工单后订单进入 producing」：**通过**（证据：`ProcessingOrderService.java:137` + generateSuccess 中 `verify(orderService).updateOrderStatus("order-001","producing")`）
- 抽验「含加工项订单不能直接发货」：**不通过**（守卫仅管理端路径生效，agent 发货路径可绕过）→ 修复后重放通过

### 复核发现问题与处置

| 级别 | 问题 | 复核证据 | 处置 |
|---|---|---|---|
| **P1** | agent 发货路径 `shipOrderIfApplicable` 绕过加工单守卫 | `OrderService.java:1596→1636-1648` 直接 `transitionStatusAtomic→shipped`（未调守卫）vs `:525-528→724-733` 管理端有守卫；`AgentOrderServiceTest:249/276/299` stub 注释"加工单守卫：无加工项"证明作者误以为该路径已受保护 | ✅ **已修复**：`shipOrderIfApplicable` 补 `assertProcessingCompletedBeforeShip`；新增回归测试 `shipsRejectedViaAgentPathWithoutCompletedProcessingOrder`，并修正原 3 处 stub 注释 |
| P2① | 并发重复生成 DuplicateKeyException 未转校验错误 → 整批 500 | `ProcessingOrderService` 原仅 catch BusinessException | ✅ **已修复**：捕 DuplicateKeyException → 订单状态回退 + 幂等失败结果（`generateConcurrentDuplicateRollsBackOrder`） |
| P2② | 生成/取消竞态：先 insert 加工单再联动，联动失败被吞 → 孤儿 generated 加工单 | 原 `generateOne` 顺序（insert 在前，`updateOrderStatus` 在后且异常被 generate() 捕获） | ✅ **已修复**：联动先行 + 落库失败回退订单状态（`generateInsertFailureRollsBackAndPropagates`） |
| P2③ | completed 后订单取消永久硬拦截、无人工出口 | `OrderService.java:1035-1051` + 状态机 completed 冻结 | ⏸ 产品决策待定 → [#3352](https://github.com/zhaokai-mgzn/migao/issues/3352) |
| P2④ | shipped 守卫只查「存在 completed 加工单」，不查「覆盖订单当前全部加工项」 | `countCompletedByOrderId` 语义 | ⏸ 产品决策待定（低频场景）→ [#3352](https://github.com/zhaokai-mgzn/migao/issues/3352) |

### 修复重放证据（协议 §1.4 成对证据）

| 项 | 修复前 | 修复后 |
|---|---|---|
| P1 agent 发货绕过 | 复核证据：`update_logistics` 路径直跳 shipped，3 个测试全绿未捕获（无该路径守卫测试） | 新回归测试 `shipsRejectedViaAgentPathWithoutCompletedProcessingOrder` 拦截；`AgentOrderServiceTest` 16 例全绿 |
| P2① 并发重复 | 无测试（DuplicateKeyException 会冒泡 500） | `generateConcurrentDuplicateRollsBackOrder` 断言幂等失败结果 + 状态回退 |
| P2② 孤儿加工单 | 无测试（顺序反了） | `generateInsertFailureRollsBackAndPropagates` 断言回退 + 异常传播 |
| 全量复跑 | — | `verify-all.sh quick` **7 通过 0 失败**（ProcessingOrderServiceTest 14 / OrderServiceTest 73 / AgentOrderServiceTest 16 全绿） |

## 沉淀记录

| 问题 | Case | 有效性验证 | Issue |
|---|---|---|---|
| P1（复核发现） | PG-009 补 agent 发货路径断言 + AgentOrderServiceTest 回归例 | ✅ 修复前该路径无测试（可绕过）→ 修复后拒绝，重放通过 | [#3351](https://github.com/zhaokai-mgzn/migao/issues/3351) |
| P2①② | ProcessingOrderServiceTest 2 例（并发重复/落库失败回退） | ✅ 修复前无覆盖 → 修复后全绿 | [#3351](https://github.com/zhaokai-mgzn/migao/issues/3351) |
| P1-1 米宝 LLM 行为 | PG-013 草稿（断言设计见下） | **待环境重放**（未完成，诚实标注） | [#3348](https://github.com/zhaokai-mgzn/migao/issues/3348) |
| P2-1 UI 旅程 | 四类必查项写入 issue 验收清单 | 待浏览器走查 | [#3349](https://github.com/zhaokai-mgzn/migao/issues/3349) |
| P2③④ 边界决策 | — | — | [#3352](https://github.com/zhaokai-mgzn/migao/issues/3352) |

PG-013 断言设计（草稿）：用户「把 ORD-x 生成加工单」→ L1 断言 `processing_order_generate` 调用（args.order_ids 含订单号）+ 结果文案含「已生成 N 个加工单」+ `db_verify`（processing_orders 出现 order_id 行、status=generated）；用户「JG-x 加工好了」→ 断言 `processing_order_update(action=complete)` 调用 + 文案含「加工完成」。
