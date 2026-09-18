-- 商品 ↔ 加工项彻底解耦（issue #4371，用户裁定 2026-09-19）
--
-- ## 背景（业务裁定原文）
-- 「我们的产品和加工项现在是有绑定关系的，但是从实际业务来看，这两者现在需要解耦掉，
--   用户选择完商品以及安装方式后，加工工序已经固定了，额外的加工项可以单独从加工项中选择，
--   不需要通过商品来关联上加工项进行过滤一道。」
--
-- 与 #4365 冻结的领域模型一致：**工序主线固定**（`app/production/routing.py` 的
-- `ROUTINGS[(部位, 工艺)]` 决定「哪些工序要做」），**加工项是触发器/配件**
-- （「选了不同加工项 ⇒ 表现为不同生产工艺」）⇒ 加工项**不应**由商品持有，
-- 也不应由商品分类过滤。
--
-- ## 本迁移删的三样东西（每样都先证明「零消费方」）
-- ① `product_processing_items`：商品↔加工项关联表。
--    消费方只有 `ProductService`（建品/改品时写、详情时读）与
--    `AgentProductController` 的 add/remove 端点 —— 都随本单一起退场。
--    **订单侧不读它**：订单的加工项存在 `order_items.processing_info.processingItems`
--    （订单级快照，见 `OrderService#extractProcessingInfo`），与商品配置无关 ⇒ 存量订单不受影响。
-- ② `products.has_processing`：仅作为「该商品是否绑了加工项」的信号位，
--    唯一消费方是 `product_detail`（告诉 LLM 要不要问加工项）与评测种子。
--    解耦后加工项是**店铺全目录**，与商品无关 ⇒ 该信号位不再有语义。
-- ③ `processing_items.applicable_product_categories`：按商品分类过滤加工项的配置。
--    唯一消费方是 `ProcessingItemService#getProcessingItems` 的
--    `applicableProductCategoryId` 过滤（对应工具参数 `applicable_category_id`）——
--    该参数随本单退场 ⇒ 列失去语义。
--    **注意**：这是**有意的删除**，不是「暂时保留的僵尸列」——
--    留着它会让下一个人以为「还能按商品分类过滤」。
--
-- ## 幂等（MigrationRunner 要求所有 SQL 可重复执行）
-- 全部 `IF EXISTS`。重复执行 = 无操作。
--
-- ## 迁移不可变（issue #4235）
-- 本文件发布后**不得再改**（改已应用迁移会被按文件名整份 skip ⇒ CI 全绿、功能静默缺失）。
-- 新增迁移须同 PR 跑 `python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger` 登记指纹。

DROP TABLE IF EXISTS product_processing_items;

ALTER TABLE products DROP COLUMN IF EXISTS has_processing;

ALTER TABLE processing_items DROP COLUMN IF EXISTS applicable_product_categories;
