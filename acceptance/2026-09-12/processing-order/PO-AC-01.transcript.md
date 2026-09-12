# PO-AC-01 transcript（证据采集）
日期：2026-09-12 ｜ 被测版本：dfb0fe6b（PR #3345 合并） ｜ 环境：测试单测层 + CI（Agent Eval smoke 生产档）

## R1 证据源：Java 服务层测试（L1 机器断言）
- ProcessingOrderServiceTest（12 例全过）：
  - generateSuccess：`assertThat(inserted.getStatus()).isEqualTo("generated")`、`assertThat(entry).doesNotContainKey("price")`、`procs.get(0).get("options")).isEqualTo(List.of("四爪钩"))`、`verify(orderService).updateOrderStatus("order-001","producing")`
  - generateDuplicateRejected：`verify(processingOrderMapper, never()).insert(any())`
  - generateWithoutProcessingRejected / generatePendingOrderRejected
  - updateStatusMainChain（issue→issued 含 processor/expectedDeliveryDate 断言；start→in_processing；complete→completed 且 `never updateOrderStatus(shipped)`）
  - updateStatusIllegalTransitionRejected / cancelRequiresReason / cancelGeneratedRevertsOrder（`verify(orderService).revertProducingToConfirmed(...)`）/ cancelCompletedFrozen
- OrderServiceTest 新增（9 例）：shippedRejectedWithoutCompletedProcessingOrder（`hasMessageContaining("须先完成加工单")`）、shippedAllowedWithCompletedProcessingOrder、shippedAllowedWithoutProcessingItems、cancelOrderAutoCancelsGeneratedProcessingOrder（captor status=cancelled + 原因含"自动作废"）、cancelOrderBlockedWhenProcessingIssued（`hasMessageContaining("已发加工")`）、revertProducingToConfirmed

## R2 证据源：Controller/Mapper 测试
- ProcessingOrderControllerTest（5 例）：generate/list/detail/updateIssue/cancelMissingReason 端点 + 参数透传 + 错误码
- ProcessingOrderMapperTest（3 例）：SQL 形状（显式 tenant_id = #{tenantId} fail-closed、活跃态/完成态过滤、三路解析）

## R3 证据源：Python 工具与契约
- test_tools_processing_order_generate/update/query（12 例）：payload 结构（orderIds/action/processor/expectedDeliveryDate/reason）、cancel 必填 reason、权限拒绝、批量上限、部分失败文案
- test_ontology_contract（PG-012）：schema 登记 29 intent、双端视图对齐
- test_prompt_snapshots：order prompt 含加工单规则、长度上限内
- contract-check.sh：7 项全过（含 intent 归属）

## R4 证据源：前端
- ProcessingOrderBlock.test.tsx（4 例）：生成入口可见、生成后结果可见（加工单号/时间线/加工项 options/复制全部）、issued 态展示、剪贴板文本断言
- order-detail.test.tsx（20 例）+ tsc 0 错误

## R5 证据源：CI（生产档 Agent Eval smoke）
- PR #3345 首轮 CI：Agent Eval (smoke tier) pass（order 域行为回归未破）；E2E quality gate pass；视觉回归 pass；三端单测 pass；UI 回退 pass

## 未采集项（如实标注）
- 米宝加工单真实 LLM 对话 transcript（无真实会话）→ 问题 P1-1
- 真实浏览器 UI 旅程（无本地服务走查）→ 问题 P2-1
- 开发期间未创建任何真实 /api/chat 会话 → §2.2 复核项 N/A（证据：全程无会话采集动作）
