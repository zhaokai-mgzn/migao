# 验收报告 加工单功能 2026-09-12 被测版本 dfb0fe6b

## 结论

**验收通过（Pass）** —— 两项覆盖缺口已补齐并留下可复核证据链：

- **P1-1（米宝 LLM 行为）✅ 已闭环**：新增 `PG-013` 真实对话用例 → 本地 admin-api + ai-agent + 云 dev DB 重放 → **发现并修复 1 个新的 P1 缺陷**（加工项解析未走 typeHandler，issue #3355）→ before/after 重放（❌ 0/1 + 工具失败 25% → ✅ 1/1 + 工具失败 0%）
- **P2-1（真实浏览器 UI 旅程）✅ 已闭环**：起本地 admin-web + admin-api，以「商家运营」persona 走查四类必查项（命名一致性 / 样式基准 / 遮挡几何 / 写操作可见性），截图 + `getBoundingClientRect` 几何数值 + DB 交叉核验
- 首轮复核发现的 P1 守卫绕过 + P2 竞态：已修复重放（PR #3353）
- 遗留**非缺陷项**：#3352 边界产品决策（需产品/客户确认后另行排期），不影响本功能交付

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
| S3 对话行为 | LLM 正确调用工具产出卡片 | **L2** | ✅ **已执行** | PG-013：tools=[order_query, validate_input, interact, processing_order_generate]，1/1 通过、工具失败 0%（§第二轮） |
| S4 前端区块 | 生成/操作/复制全部/打印 | L1 | ✅ | R4（组件+页面测试+tsc） |
| S4 真实浏览器 | 排版/遮挡/写操作可见性 | **L2/UA** | ✅ **已执行** | 四类必查 + 截图 + 几何数值 + DB 交叉核验（§第二轮） |
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

## 第二轮：补齐两项覆盖缺口（2026-09-12，本地 admin-api:8080 + ai-agent:8001 + admin-web:3001，云 dev DB）

### 2.1 米宝 LLM 行为（关闭 #3348）→ 发现并修复 **新 P1 缺陷**

新增用例 **PG-013**（tier normal）：真实对话 3 轮（「最近有没有已确认、需要加工的订单？」→「帮我把这一个生成加工单」→「确认」），断言 `order_query before processing_order_generate` + `required_args: order_ids` + **禁止失败文案**（无加工项/生成未成功/生成失败/无法生成加工单/系统判定为）。

**首轮运行即暴露真实缺陷（issue #3355）**：订单确实含加工项，但生成端点返回「无加工项」——
- 根因 1：`OrderItemMapper.selectByOrderId`（自定义 @Select）不经过 `JacksonTypeHandler` → `processingInfo` 为 JSON 字符串 → `instanceof Map` 判定失败
- 根因 2：`ProcessingOrder` 实体缺 `autoResultMap = true` → `items_snapshot` 同样为字符串 → 详情/列表 `items=null`
- **影响面**：生成加工单对主路径不可用；**发货守卫静默失效**（同一解析 → hasProcessing=false → 放行）

**修复**：加载统一走 BaseMapper（`LambdaQueryWrapper`）+ 解析层兼容 JSON 字符串 + 实体补 `autoResultMap`；回归测试 3 例。

**before/after 重放证据（协议 §1.4 成对）**：

| 项 | before（临时还原修复） | after（修复后） |
|---|---|---|
| PG-013 | ❌ **0/1 未通过**（禁止文案命中「无加工项/生成失败」） | ✅ **1/1 通过** |
| 工具健康度 | 失败率 **25%**（`processing_order_generate!no_success_flag`） | 失败率 **0%** |
| 生成端点 | `{"success":false,"message":"...无加工项..."}` | `{"success":true,"processingOrderNo":"JG-20260912-4817"}` |
| DB 落库 | 无加工单 | 加工单 generated + 快照五要素（商品/颜色/整卷/门幅3.2米/宽2.6/高2.9/数量8）+ 加工项含 unit/options |
| 订单联动 | — | confirmed → **producing** |
| 发货守卫 | 放行（静默失效） | 拦截「订单含加工项，须先完成加工单后再发货」 |

### 2.2 真实浏览器 UI 旅程（关闭 #3349）

环境：admin-web:3001 + admin-api:8080，Chrome（Playwright），商家运营 persona；证据目录 `ui-evidence/`（5 张截图 + `evidence.json`）。

| 必查类 | 证据 | 判定 |
|---|---|---|
| ① 命名一致性 | 面包屑「订单管理 / 订单列表」、h1「订单详情」、区块标题「加工单」；与侧边栏菜单命名一致（截图 05） | ✅ |
| ② 样式基准对照 | 详情页 h1 fontSize `20px` == 基准页 `20px`；容器 padding `24px 24px 96px` == 基准 `24px 24px 96px` | ✅ |
| ③ 布局遮挡几何 | FAB rect `{x:1360,y:820,56×56}`；加工单区块按钮（复制全部/打印/发加工/开始加工/取消加工单）**均无重叠**（滚到底复测一致）；标题中心 `elementFromPoint` 命中 H3（可点击） | ✅ |
| ④ 写操作成果物可见性 | 点「发加工」→ 填加工方「UI验收加工厂」+ 交期 2026-09-30 → 确认 → **状态推进为「已发加工」+ 时间线高亮 + 加工方/交期展示 + 复制全部/打印仍在**；DB 交叉核验：`status=issued, processor=UI验收加工厂, expectedDeliveryDate=2026-09-30` | ✅ |

视觉确认（截图 05）：卡片层级/时间线/快照五要素/无销售价/FAB 不遮挡，与全局设计基准一致。

## 沉淀记录

| 问题 | Case | 有效性验证 | Issue |
|---|---|---|---|
| P1（复核发现：agent 发货绕过） | PG-009 补 agent 发货路径断言 + AgentOrderServiceTest 回归例 | ✅ 修复前该路径无测试（可绕过）→ 修复后拒绝，重放通过 | [#3351](https://github.com/zhaokai-mgzn/migao/issues/3351)（已关闭） |
| P2①②（并发重复/孤儿态） | ProcessingOrderServiceTest 2 例 | ✅ 修复前无覆盖 → 修复后全绿 | [#3351](https://github.com/zhaokai-mgzn/migao/issues/3351)（已关闭） |
| **P1（LLM 验收发现：typeHandler 解析）** | **PG-013 + 3 例单测回归**（JSON 字符串 processingInfo 生成成功 / 守卫拦截 / 快照解析） | ✅ **before 重放 0/1 必 fail（禁止文案命中）→ after 重放 1/1 pass** | [#3355](https://github.com/zhaokai-mgzn/migao/issues/3355) |
| P2-1 UI 旅程 | UI 走查脚本 + 四类必查证据（`ui-evidence/`） | ✅ 四类全绿 + DB 交叉核验 | [#3349](https://github.com/zhaokai-mgzn/migao/issues/3349) |
| P2③④ 边界决策 | — | — | [#3352](https://github.com/zhaokai-mgzn/migao/issues/3352)（非缺陷，待产品决策） |

## 复现方式（零人工）

```bash
# 服务：admin-api(:8080, .env 显式注入) + ai-agent(:8001, ADMIN_API_BASE_URL=localhost) + admin-web(:3001)
# 1) LLM 行为用例（before/after 重放）
backend/ai-agent-service/.venv/bin/python tests/agent_eval/local_runner.py case --case-id PG-013 --cases .github/cases
# 2) UI 旅程验收（截图 + 几何证据）
node accept-processing-order-ui.js <orderId>
# 3) 发货守卫端到端
curl -X PUT localhost:8080/api/admin/orders/<id>/status -d '{"status":"shipped"}'   # 预期 400 须先完成加工单
```
