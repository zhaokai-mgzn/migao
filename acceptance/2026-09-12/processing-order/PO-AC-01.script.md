## 剧本 PO-AC-01：商家订单加工单全流程（issue #3340）
被验收对象：加工单功能（PR #3345，merge commit dfb0fe6b）
环境：admin-web / 米宝 / 测试→生产 / 版本 dfb0fe6b
验收日期：2026-09-12

### 场景 S1 商家在订单详情生成加工单
用户动作序列：
1. 打开含加工项且已确认的订单详情
2. 看到「生成加工单」入口，点击
3. 看到加工单卡：加工单号/状态时间线/快照明细（含加工项 options）
验收点：
- [x] L1 生成后订单状态 confirmed→producing（OrderServiceTest.shippedRejectedWithoutCompletedProcessingOrder 反例 + ProcessingOrderServiceTest.generateSuccess）
- [x] L1 快照含 options、不含销售价（ProcessingOrderServiceTest.generateSuccess: `assertThat(entry).doesNotContainKey("price")` + options 断言）
- [x] L1 幂等：重复生成拒绝（ProcessingOrderServiceTest.generateDuplicateRejected）
- [x] L1 无加工项订单不生成（ProcessingOrderServiceTest.generateWithoutProcessingRejected）
- [ ] L2 真实浏览器走查生成按钮→卡片出现（**未执行：无真实浏览器会话证据，见问题清单 P2-1**）

### 场景 S2 加工单状态流转与订单联动
用户动作序列：
1. 发加工（填加工方+交期）→ 开始加工 → 加工完成
2. 尝试直接发货（未完成加工单）
3. 取消加工单
验收点：
- [x] L1 状态机合法流转 issue/start/complete（ProcessingOrderServiceTest.updateStatusMainChain）
- [x] L1 非法流转拒绝、completed 冻结（updateStatusIllegalTransitionRejected / cancelCompletedFrozen）
- [x] L1 含加工项订单无 completed 加工单 → shipped 被拒（OrderServiceTest.shippedRejectedWithoutCompletedProcessingOrder）
- [x] L1 取消联动：generated 取消 → 订单回退 confirmed（cancelGeneratedRevertsOrder）；订单取消 → 加工单自动作废/拦截（cancelOrderAutoCancelsGeneratedProcessingOrder / cancelOrderBlockedWhenProcessingIssued）
- [x] L1 cancel 必填原因（cancelRequiresReason）

### 场景 S3 米宝对话驱动加工单
用户动作序列：
1. 「把这个订单生成加工单」
2. 「JG-xxx 到哪了」
3. 「加工好了」
验收点：
- [x] L1 工具存在且注册、intent 路由 order skill（test_ontology_contract PG-012 / test_graph_skills / registry）
- [x] L1 工具参数校验（validate_input 规则 + test_tools_processing_order_* 12 例）
- [ ] L2 真实米宝对话：LLM 正确选择工具并产出卡片（**未执行：无真实 LLM 会话 transcript，见问题清单 P1-1**）
- [x] L1 订单 prompt 含加工单规则（test_prompt_snapshots）

### 场景 S4 复制全部 / 打印（前端区块）
验收点：
- [x] L1 复制全部文本含加工单号/加工方/加工项 options（ProcessingOrderBlock.test.tsx 第 4 例，clipboard 断言）
- [x] L1 生成/状态/操作按钮渲染（ProcessingOrderBlock.test.tsx 4/4 + order-detail.test.tsx 20/20 + tsc 0 错误）
- [ ] L2 真实浏览器：打印 CSS 排版/遮挡（**未执行：无真实浏览器证据，见问题清单 P2-1**）

### 场景 S5 复核开发期间留下的会话（§2.2 专项）
- [x] L1 本次开发/验收过程未调用任何 /api/chat 端点创建会话（证据：无 transcript 采集动作、无 session 遍历输出）→ **本交付无历史会话遗留可复核**（开发全程为单测 + MockMvc，未产生真实 agent 会话）
