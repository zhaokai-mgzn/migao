-- 种子：工序库 + 工艺路线模板（issue #4116 P0-2）
--
-- ## 背景（取证事实，不是推测）
-- `production_operations` / `production_routings` 自 V49 建表起**零消费者、零种子**：
-- 商家无配置入口、库里无数据 ⇒ §3 工艺路线在 DB 层不可查、不可展示。
-- 真值源 = `backend/ai-agent-service/app/production/routing.py` 的
-- `OPERATION_CATALOG`（30 道工序）+ `ROUTINGS`（6 条 部位×工艺 路线，布帘·韩褶 = 11 道实证走线，
-- 2026-09 行业 ERP 截图）。本迁移把这两份**既有确定性常量**作为**初始种子**落库。
--
-- ## 本迁移**不做**什么（如实登记，见 #4116 包内报告「未做」节）
-- ① **不切换**「生成加工单即自动实例化」的工序来源：`ProcessingOrderService.instantiateOperations`
--    仍读**加工项目录**快照。切到「从库读工序」**待裁定**（会与 #4117 的完工语义、加工项自定义
--    工序名交互，需单独一包）。
-- ② **不改**「末道工序必完」的临时默认（#4131 落的是「每部位末道工序 `is_must_finish=true`」）。
--    本迁移的 `is_must_finish` 只按真值源 `MUST_FINISH_OPS` 标记「外帘装袋」（库里**一工序一行**，
--    位置语义 ≠ 加工单实例的「部位末道」）⇒ **两者含义不同，不要互读**。
--    ⚠️ 待裁定落地后应改为**读库**（届时实例化改读本表 `is_must_finish`，两处口径才合一）。
--
-- ## 幂等性
-- 全部 `ON CONFLICT DO NOTHING`；`MigrationRunner` 要求所有 SQL 文件幂等、可重复执行。
-- 冲突目标 = V49 既有的**部分唯一索引**（`uk_production_operations_tenant_name` /
-- `uk_production_routings_tenant_type_craft`，均 `WHERE deleted = 0`），因此软删后同名工序
-- 可重建、本迁移不会把软删行「复活」（`ON CONFLICT` 的推断需要与索引谓词一致，故 SQL 里
-- 显式写出 `WHERE deleted = 0`）。
--
-- ## 与真值源的收敛判据（防第二份口径漂移）
-- 本文件是 Python 常量的**一次快照**，不是第二份真值源。防漂移由测试守：
-- `backend/ai-agent-service/tests/test_production/test_operation_catalog_seed.py`
-- 逐行解析本文件的 VALUES 与 `OPERATION_CATALOG`/`ROUTINGS` 比对（改名/改价/加减工序即红）。

-- ── 工序库种子（tenant_id=1；id 确定性 `op-v54-NN`，N = 真值源字典序位）──
INSERT INTO production_operations
    (id, tenant_id, name, group_name, position, unit, unit_price,
     is_must_finish, is_start_marker, sort_order, status)
VALUES
  ('op-v54-01', 1, '精裁-布', '裁剪', '布帘', '米', 0.4, FALSE, TRUE, 1, 'active'),
  ('op-v54-02', 1, '精裁-纱', '裁剪', '纱帘', '米', 0.4, FALSE, TRUE, 2, 'active'),
  ('op-v54-03', 1, '裁剪-布', '裁剪', '布帘', '米', 0.4, FALSE, FALSE, 3, 'active'),
  ('op-v54-04', 1, '裁剪-纱', '裁剪', '纱帘', '米', 0.4, FALSE, FALSE, 4, 'active'),
  ('op-v54-05', 1, '布三边', '车位', NULL, '米', 0.4, FALSE, FALSE, 5, 'active'),
  ('op-v54-06', 1, '纱三边', '车位', NULL, '米', 0.4, FALSE, FALSE, 6, 'active'),
  ('op-v54-07', 1, '韩褶-布', '车位', '布帘', '折', 0.4, FALSE, FALSE, 7, 'active'),
  ('op-v54-08', 1, '韩褶-纱', '车位', '纱帘', '折', 0.4, FALSE, FALSE, 8, 'active'),
  ('op-v54-09', 1, '上车布-布', '车位', '布帘', '米', 0.5, FALSE, FALSE, 9, 'active'),
  ('op-v54-10', 1, '上车布-纱', '车位', '纱帘', '米', 0.5, FALSE, FALSE, 10, 'active'),
  ('op-v54-11', 1, '打孔-布', '车位', '布帘', '孔', 0.15, FALSE, FALSE, 11, 'active'),
  ('op-v54-12', 1, '打孔-纱', '车位', '纱帘', '孔', 0.15, FALSE, FALSE, 12, 'active'),
  ('op-v54-13', 1, '拼1次-布', '车位', '布帘', '幅', 0.8, FALSE, FALSE, 13, 'active'),
  ('op-v54-14', 1, '拼2次-布', '车位', '布帘', '幅', 1.2, FALSE, FALSE, 14, 'active'),
  ('op-v54-15', 1, '拼3次-布', '车位', '布帘', '幅', 1.6, FALSE, FALSE, 15, 'active'),
  ('op-v54-16', 1, '花边-布', '车位', '布帘', '米', 0.6, FALSE, FALSE, 16, 'active'),
  ('op-v54-17', 1, '铅坠-布', '车位', '布帘', '米', 0.3, FALSE, FALSE, 17, 'active'),
  ('op-v54-18', 1, '接高-布', '车位', '布帘', '幅', 1.0, FALSE, FALSE, 18, 'active'),
  ('op-v54-19', 1, '帘头制作', '车位', '帘头', '个', 2.0, FALSE, FALSE, 19, 'active'),
  ('op-v54-20', 1, '熨烫-布', '后道', '布帘', '米', 0.35, FALSE, FALSE, 20, 'active'),
  ('op-v54-21', 1, '定型-布', '后道', '布帘', '米', 0.4, FALSE, FALSE, 21, 'active'),
  ('op-v54-22', 1, '复烫-布', '后道', '布帘', '米', 0.35, FALSE, FALSE, 22, 'active'),
  ('op-v54-23', 1, '布帘车被', '后道', NULL, '米', 0.4, FALSE, FALSE, 23, 'active'),
  ('op-v54-24', 1, '外帘打卷', '后道', '外帘', '套', 1.0, FALSE, FALSE, 24, 'active'),
  ('op-v54-25', 1, '外帘装袋', '后道', '外帘', '套', 1.0, TRUE, FALSE, 25, 'active'),
  ('op-v54-26', 1, '质检', '后道', NULL, '套', 1.5, FALSE, FALSE, 26, 'active'),
  ('op-v54-27', 1, '外帘发货', '后道', '外帘', '套', 1.0, FALSE, FALSE, 27, 'active'),
  ('op-v54-28', 1, '绑带-布', '其他', '布帘', '套', 0.5, FALSE, FALSE, 28, 'active'),
  ('op-v54-29', 1, '抱枕', '其他', NULL, '个', 2.0, FALSE, FALSE, 29, 'active'),
  ('op-v54-30', 1, '腰靠垫', '其他', NULL, '个', 2.0, FALSE, FALSE, 30, 'active')
ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;

-- ── 工艺路线模板种子（部位 × 工艺 → 工序名有序序列）──
-- 与 routing.py ROUTINGS 逐字同构（含 布帘·韩褶 11 道实证走线）；条件工序/定型开关
-- 由实例化时按特殊选项插入（routing.build_routing 的语义，本表只存**基准**序列）。
INSERT INTO production_routings
    (id, tenant_id, curtain_type, craft, operations, status)
VALUES
  ('rt-v54-01', 1, '布帘', '韩褶',
   '["精裁-布","布三边","韩褶-布","上车布-布","熨烫-布","定型-布","复烫-布","布帘车被","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active'),
  ('rt-v54-02', 1, '布帘', '打孔',
   '["精裁-布","布三边","打孔-布","熨烫-布","定型-布","复烫-布","布帘车被","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active'),
  ('rt-v54-03', 1, '布帘', '四爪钩',
   '["精裁-布","布三边","上车布-布","熨烫-布","布帘车被","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active'),
  ('rt-v54-04', 1, '布帘', '穿杆',
   '["精裁-布","布三边","熨烫-布","布帘车被","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active'),
  ('rt-v54-05', 1, '纱帘', '韩褶',
   '["精裁-纱","纱三边","韩褶-纱","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active'),
  ('rt-v54-06', 1, '帘头', '平幔',
   '["精裁-布","布三边","帘头制作","定型-布","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active')
ON CONFLICT (tenant_id, curtain_type, craft) WHERE deleted = 0 DO NOTHING;

COMMENT ON COLUMN production_operations.is_must_finish IS
    '必完工序：全绿才可打包（issue #3995）。V54 种子只标「外帘装袋」（真值源 MUST_FINISH_OPS）；'
    '与加工单实例的「每部位末道工序 is_must_finish」是**两套口径**（#4116 待裁定：实例化改读本表后合一）';