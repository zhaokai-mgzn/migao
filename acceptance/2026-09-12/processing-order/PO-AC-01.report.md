# 验收报告 加工单功能 2026-09-12 被测版本 dfb0fe6b

## 结论

**有条件通过（Conditional Pass）**：L1 机器断言全覆盖且全绿（状态机/联动/守卫/幂等/快照/租户隔离/前端渲染 4+20 例），CI 全绿（含 Agent Eval smoke 生产档）；存在 **2 项覆盖缺口**（P1-1 米宝 LLM 行为无真实对话 transcript 与可执行评测用例、P2-1 真实浏览器 UI 旅程未执行），补齐并重放后可达「验收通过」。本次不下「验收通过」结论。

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

复核 AI（独立，不看本剧本）抽样判定将在此处补充（待 subagent 返回）。

## 沉淀记录

| 问题 | Case | 有效性验证 | Issue |
|---|---|---|---|
| P1-1 | PG-013 草稿（断言设计见下） | **待环境重放**（未完成，诚实标注） | [#3348](https://github.com/zhaokai-mgzn/migao/issues/3348) |
| P2-1 | UI 旅程四类必查项写入 issue 验收清单 | 待浏览器走查 | [#3349](https://github.com/zhaokai-mgzn/migao/issues/3349) |

PG-013 断言设计（草稿）：用户「把 ORD-x 生成加工单」→ L1 断言 `processing_order_generate` 调用（args.order_ids 含订单号）+ 结果文案含「已生成 N 个加工单」+ `db_verify`（processing_orders 出现 order_id 行、status=generated）；用户「JG-x 加工好了」→ 断言 `processing_order_update(action=complete)` 调用 + 文案含「加工完成」。
