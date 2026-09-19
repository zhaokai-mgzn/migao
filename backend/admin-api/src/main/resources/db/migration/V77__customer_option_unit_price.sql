-- 特殊选项**对客按套单价**（`customer_unit_price`）+ 合成测试数据（V77，issue #4525 = 设计 §4/§7/§8 包 A）
--
-- ## 一句话
-- `production_route_rules` 加一列 `customer_unit_price NUMERIC(12,2)`：该**特殊选项**
-- （`trigger_kind='option'` 行）对**顾客**的**元/套**单价；同时把本方案 §7 的合成价目
-- （92 行组合价 + 16 条选项价）种进库。
--
-- ## 用户裁定（2026-09-19，写进库结构）
-- 「特殊选项也属于加工项的范畴，也需要额外算钱，但是**计价单位是套**」
-- 「加工费 = 组合加工费用 + 特殊选项费用（按套来算）」
-- 「**1 套 = 1 个订单行**」
--
-- ## 两套账不互读（设计 §4.1，本列存在的全部理由）
-- 本列是**对客售价账**（L3②）。计件路径（`ProductionService` / `piecework` /
-- `production_operations.unit_price`）**绝不读本列** —— 互读 = 把内部计件单价泄漏成对客售价
-- （或反向：拿对客售价给工人发工资）。列名带 `customer_` 前缀就是为了让这条纪律
-- **在 grep 层可判**（表内同时存在车间路由语义与对客价语义）。
--
-- ## `NULL` = **未定价**（≠ 0）
-- 取价侧必须显式可见（`special_options[].priced=false` + 可行动 hint），**不得静默按 0 收**。
-- 非 `option` 行一律 `NULL`（工艺变体 `craft` / 定型 `shaped` / 计件系数 `factor` 都不按套收费）。
--
-- ## ⚠️ 设计文档与代码事实的冲突（**以代码事实为准，显式登记**）
-- 设计 §7 写「19 项特殊选项价」，但 §4.1 同时冻结「非 `option` 行一律 `NULL`」。
-- 19 项里**只有 16 项**在 `production_route_rules` 里是 `trigger_kind='option'` 行：
--   · `余料带回-布` / `余料带回-纱` = `NON_PIECEWORK_OPTIONS`（不计件、**无规则行**）；
--   · `一分为二` 只有 `action='factor'` 的计件系数档（计件语义，非对客价）。
-- ⇒ 本迁移只给**那 16 条 `option` 行**定价；为凑「19」而给上述 3 项造 `option` 规则行
-- 会**违反 §4.1 与 R11 的边界**（还会与计件系数档撞业务唯一键）。如实登记，不粉饰。
--
-- ## ⚠️ 测试价不代表任何真实定价（设计 §1 末 / §10.3）
-- 设计 §1 已判定：ERP 截图 OCR 的单价**不可作为改钱的数据源**（两图同段读数不一致）。
-- 用户裁定「测试数据的钱随机生成即可」⇒ 本迁移的价格由**固定种子生成一次后写死**
-- （生成器 = `tests/unit_ci_workflows/synthetic_processing_fee_data.py`，种子 4525），
-- 并显式标 `source='synthetic'`（防止测试价被当成真实价目）。
-- 真实价目以商家在「加工费管理」里配的为准。
--
-- ## 幂等（`MigrationRunner` 要求所有 SQL 可重复执行）
-- `ADD COLUMN IF NOT EXISTS` + `COMMENT ON COLUMN`（幂等）+ `INSERT ... ON CONFLICT DO NOTHING`
-- + 两条带 `WHERE` 守卫的 `UPDATE`（重跑匹配 0 行 ⇒ 空转，**不覆盖商家改过的价**）。
--
-- ## 与 schema.sql 的收敛
-- `docs/sql/schema.sql` 是**全新库的一次性 bootstrap**（该路径**不跑迁移链**）⇒ 同款终态
-- 必须同步写进该文件，否则 bootstrap 建库后取价读不到列（形态见 #3270）。
--
-- ## 为什么不改已发布迁移
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记、已应用的文件**整份跳过**
-- ⇒ 改老迁移只对全新库生效、存量环境永远拿不到（「CI 全绿、功能静默缺失」，issue #4235）。

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 列：特殊选项的**对客元/套**单价
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE production_route_rules ADD COLUMN IF NOT EXISTS customer_unit_price NUMERIC(12,2);

COMMENT ON COLUMN production_route_rules.customer_unit_price IS
    '特殊选项（trigger_kind=''option'' 行）对**顾客**的**元/套**单价 —— **对客售价账**（L3②）。'
    'NULL = **未定价**（≠ 0）：取价侧必须显式可见（special_options[].priced=false + 可行动 hint），'
    '不得静默按 0 收。非 option 行一律 NULL（工艺变体不按套收费）。'
    '⚠️ **计件路径绝不读本列**：ProductionService / piecework 与 production_operations.unit_price '
    '是给工人付的成本账，与本列（对客售价）两套账不互读；列名的 customer_ 前缀即为让该纪律在 grep 层可判。'
    'issue #4525（设计 docs/design/processing-fee-and-option-pricing.md §4.1）。';

COMMENT ON COLUMN production_route_rules.factor IS
    '计件系数（仅 action=''factor'' 时有值；同一触发内后档覆盖前档）。'
    '**车间成本账** —— 与 customer_unit_price（对客售价账）两套账不互读。';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 组合价目：92 行（91 组合 + 缎带），元/米 —— 设计 §7 的 L3①
-- ══════════════════════════════════════════════════════════════════════════════════════
-- `composition_key` = 归一化口径（trim → 丢空 → 去重 → **Unicode 码点升序** → `+` 连接），
-- 与 `ProcessingFeeCombinationCommandService.compositionKey` **同口径**（唯一实现）。
-- `source='synthetic'` = 合成测试价（**不是**真实价目）；商家改价后本行不再被本迁移触碰
-- （`ON CONFLICT DO NOTHING`）。
INSERT INTO processing_fee_combinations
    (id, tenant_id, composition_key, items, unit_price, status, sort_order, source)
VALUES
  ('pfc-synthetic-001', 1, '打孔+超高', '["打孔", "超高"]'::jsonb, 3.12, 'active', 1, 'synthetic'),
  ('pfc-synthetic-002', 1, '打孔+超宽', '["打孔", "超宽"]'::jsonb, 3.43, 'active', 2, 'synthetic'),
  ('pfc-synthetic-003', 1, '打孔+定型', '["打孔", "定型"]'::jsonb, 6.35, 'active', 3, 'synthetic'),
  ('pfc-synthetic-004', 1, '打孔+花边', '["打孔", "花边"]'::jsonb, 7.39, 'active', 4, 'synthetic'),
  ('pfc-synthetic-005', 1, '打孔+扣环', '["打孔", "扣环"]'::jsonb, 8.64, 'active', 5, 'synthetic'),
  ('pfc-synthetic-006', 1, '打孔+超高+超宽', '["打孔", "超高", "超宽"]'::jsonb, 4.66, 'active', 6, 'synthetic'),
  ('pfc-synthetic-007', 1, '打孔+超高+定型', '["打孔", "超高", "定型"]'::jsonb, 9.72, 'active', 7, 'synthetic'),
  ('pfc-synthetic-008', 1, '打孔+超高+花边', '["打孔", "超高", "花边"]'::jsonb, 5.84, 'active', 8, 'synthetic'),
  ('pfc-synthetic-009', 1, '打孔+超高+扣环', '["打孔", "超高", "扣环"]'::jsonb, 14.70, 'active', 9, 'synthetic'),
  ('pfc-synthetic-010', 1, '打孔+超宽+定型', '["打孔", "超宽", "定型"]'::jsonb, 9.99, 'active', 10, 'synthetic'),
  ('pfc-synthetic-011', 1, '打孔+超宽+花边', '["打孔", "超宽", "花边"]'::jsonb, 5.34, 'active', 11, 'synthetic'),
  ('pfc-synthetic-012', 1, '打孔+超宽+扣环', '["打孔", "超宽", "扣环"]'::jsonb, 14.78, 'active', 12, 'synthetic'),
  ('pfc-synthetic-013', 1, '打孔+定型+花边', '["打孔", "定型", "花边"]'::jsonb, 11.15, 'active', 13, 'synthetic'),
  ('pfc-synthetic-014', 1, '打孔+定型+扣环', '["打孔", "定型", "扣环"]'::jsonb, 3.35, 'active', 14, 'synthetic'),
  ('pfc-synthetic-015', 1, '打孔+花边+扣环', '["打孔", "花边", "扣环"]'::jsonb, 3.26, 'active', 15, 'synthetic'),
  ('pfc-synthetic-016', 1, '打孔+超高+超宽+定型', '["打孔", "超高", "超宽", "定型"]'::jsonb, 5.18, 'active', 16, 'synthetic'),
  ('pfc-synthetic-017', 1, '打孔+超高+超宽+花边', '["打孔", "超高", "超宽", "花边"]'::jsonb, 10.38, 'active', 17, 'synthetic'),
  ('pfc-synthetic-018', 1, '打孔+超高+超宽+扣环', '["打孔", "超高", "超宽", "扣环"]'::jsonb, 14.43, 'active', 18, 'synthetic'),
  ('pfc-synthetic-019', 1, '打孔+超高+定型+花边', '["打孔", "超高", "定型", "花边"]'::jsonb, 13.15, 'active', 19, 'synthetic'),
  ('pfc-synthetic-020', 1, '打孔+超高+定型+扣环', '["打孔", "超高", "定型", "扣环"]'::jsonb, 14.48, 'active', 20, 'synthetic'),
  ('pfc-synthetic-021', 1, '打孔+超高+花边+扣环', '["打孔", "超高", "花边", "扣环"]'::jsonb, 11.09, 'active', 21, 'synthetic'),
  ('pfc-synthetic-022', 1, '打孔+超宽+定型+花边', '["打孔", "超宽", "定型", "花边"]'::jsonb, 11.47, 'active', 22, 'synthetic'),
  ('pfc-synthetic-023', 1, '打孔+超宽+定型+扣环', '["打孔", "超宽", "定型", "扣环"]'::jsonb, 12.46, 'active', 23, 'synthetic'),
  ('pfc-synthetic-024', 1, '打孔+超宽+花边+扣环', '["打孔", "超宽", "花边", "扣环"]'::jsonb, 13.15, 'active', 24, 'synthetic'),
  ('pfc-synthetic-025', 1, '打孔+定型+花边+扣环', '["打孔", "定型", "花边", "扣环"]'::jsonb, 11.85, 'active', 25, 'synthetic'),
  ('pfc-synthetic-026', 1, '打孔+超高+超宽+定型+花边', '["打孔", "超高", "超宽", "定型", "花边"]'::jsonb, 3.95, 'active', 26, 'synthetic'),
  ('pfc-synthetic-027', 1, '打孔+超高+超宽+定型+扣环', '["打孔", "超高", "超宽", "定型", "扣环"]'::jsonb, 3.52, 'active', 27, 'synthetic'),
  ('pfc-synthetic-028', 1, '打孔+超高+超宽+花边+扣环', '["打孔", "超高", "超宽", "花边", "扣环"]'::jsonb, 13.73, 'active', 28, 'synthetic'),
  ('pfc-synthetic-029', 1, '打孔+超高+定型+花边+扣环', '["打孔", "超高", "定型", "花边", "扣环"]'::jsonb, 7.91, 'active', 29, 'synthetic'),
  ('pfc-synthetic-030', 1, '打孔+超宽+定型+花边+扣环', '["打孔", "超宽", "定型", "花边", "扣环"]'::jsonb, 5.26, 'active', 30, 'synthetic'),
  ('pfc-synthetic-031', 1, '打孔+超高+超宽+定型+花边+扣环', '["打孔", "超高", "超宽", "定型", "花边", "扣环"]'::jsonb, 11.31, 'active', 31, 'synthetic'),
  ('pfc-synthetic-032', 1, '韩折+超高', '["韩折", "超高"]'::jsonb, 14.04, 'active', 32, 'synthetic'),
  ('pfc-synthetic-033', 1, '韩折+超宽', '["韩折", "超宽"]'::jsonb, 8.04, 'active', 33, 'synthetic'),
  ('pfc-synthetic-034', 1, '韩折+定型', '["韩折", "定型"]'::jsonb, 11.67, 'active', 34, 'synthetic'),
  ('pfc-synthetic-035', 1, '韩折+花边', '["韩折", "花边"]'::jsonb, 11.13, 'active', 35, 'synthetic'),
  ('pfc-synthetic-036', 1, '韩折+扣环', '["韩折", "扣环"]'::jsonb, 5.20, 'active', 36, 'synthetic'),
  ('pfc-synthetic-037', 1, '韩折+超高+超宽', '["韩折", "超高", "超宽"]'::jsonb, 8.90, 'active', 37, 'synthetic'),
  ('pfc-synthetic-038', 1, '韩折+超高+定型', '["韩折", "超高", "定型"]'::jsonb, 3.01, 'active', 38, 'synthetic'),
  ('pfc-synthetic-039', 1, '韩折+超高+花边', '["韩折", "超高", "花边"]'::jsonb, 7.33, 'active', 39, 'synthetic'),
  ('pfc-synthetic-040', 1, '韩折+超高+扣环', '["韩折", "超高", "扣环"]'::jsonb, 12.44, 'active', 40, 'synthetic'),
  ('pfc-synthetic-041', 1, '韩折+超宽+定型', '["韩折", "超宽", "定型"]'::jsonb, 10.44, 'active', 41, 'synthetic'),
  ('pfc-synthetic-042', 1, '韩折+超宽+花边', '["韩折", "超宽", "花边"]'::jsonb, 11.32, 'active', 42, 'synthetic'),
  ('pfc-synthetic-043', 1, '韩折+超宽+扣环', '["韩折", "超宽", "扣环"]'::jsonb, 10.50, 'active', 43, 'synthetic'),
  ('pfc-synthetic-044', 1, '韩折+定型+花边', '["韩折", "定型", "花边"]'::jsonb, 7.89, 'active', 44, 'synthetic'),
  ('pfc-synthetic-045', 1, '韩折+定型+扣环', '["韩折", "定型", "扣环"]'::jsonb, 12.84, 'active', 45, 'synthetic'),
  ('pfc-synthetic-046', 1, '韩折+花边+扣环', '["韩折", "花边", "扣环"]'::jsonb, 6.60, 'active', 46, 'synthetic'),
  ('pfc-synthetic-047', 1, '韩折+超高+超宽+定型', '["韩折", "超高", "超宽", "定型"]'::jsonb, 11.81, 'active', 47, 'synthetic'),
  ('pfc-synthetic-048', 1, '韩折+超高+超宽+花边', '["韩折", "超高", "超宽", "花边"]'::jsonb, 9.49, 'active', 48, 'synthetic'),
  ('pfc-synthetic-049', 1, '韩折+超高+超宽+扣环', '["韩折", "超高", "超宽", "扣环"]'::jsonb, 7.67, 'active', 49, 'synthetic'),
  ('pfc-synthetic-050', 1, '韩折+超高+定型+花边', '["韩折", "超高", "定型", "花边"]'::jsonb, 8.95, 'active', 50, 'synthetic'),
  ('pfc-synthetic-051', 1, '韩折+超高+定型+扣环', '["韩折", "超高", "定型", "扣环"]'::jsonb, 14.14, 'active', 51, 'synthetic'),
  ('pfc-synthetic-052', 1, '韩折+超高+花边+扣环', '["韩折", "超高", "花边", "扣环"]'::jsonb, 7.74, 'active', 52, 'synthetic'),
  ('pfc-synthetic-053', 1, '韩折+超宽+定型+花边', '["韩折", "超宽", "定型", "花边"]'::jsonb, 8.53, 'active', 53, 'synthetic'),
  ('pfc-synthetic-054', 1, '韩折+超宽+定型+扣环', '["韩折", "超宽", "定型", "扣环"]'::jsonb, 4.65, 'active', 54, 'synthetic'),
  ('pfc-synthetic-055', 1, '韩折+超宽+花边+扣环', '["韩折", "超宽", "花边", "扣环"]'::jsonb, 10.28, 'active', 55, 'synthetic'),
  ('pfc-synthetic-056', 1, '韩折+定型+花边+扣环', '["韩折", "定型", "花边", "扣环"]'::jsonb, 13.20, 'active', 56, 'synthetic'),
  ('pfc-synthetic-057', 1, '韩折+超高+超宽+定型+花边', '["韩折", "超高", "超宽", "定型", "花边"]'::jsonb, 3.39, 'active', 57, 'synthetic'),
  ('pfc-synthetic-058', 1, '韩折+超高+超宽+定型+扣环', '["韩折", "超高", "超宽", "定型", "扣环"]'::jsonb, 9.96, 'active', 58, 'synthetic'),
  ('pfc-synthetic-059', 1, '韩折+超高+超宽+花边+扣环', '["韩折", "超高", "超宽", "花边", "扣环"]'::jsonb, 11.74, 'active', 59, 'synthetic'),
  ('pfc-synthetic-060', 1, '韩折+超高+定型+花边+扣环', '["韩折", "超高", "定型", "花边", "扣环"]'::jsonb, 10.87, 'active', 60, 'synthetic'),
  ('pfc-synthetic-061', 1, '韩折+超宽+定型+花边+扣环', '["韩折", "超宽", "定型", "花边", "扣环"]'::jsonb, 13.52, 'active', 61, 'synthetic'),
  ('pfc-synthetic-062', 1, '韩折+超高+超宽+定型+花边+扣环', '["韩折", "超高", "超宽", "定型", "花边", "扣环"]'::jsonb, 7.14, 'active', 62, 'synthetic'),
  ('pfc-synthetic-063', 1, '韩定+S钩+超高', '["韩定", "S钩", "超高"]'::jsonb, 6.63, 'active', 63, 'synthetic'),
  ('pfc-synthetic-064', 1, '韩定+S钩+超宽', '["韩定", "S钩", "超宽"]'::jsonb, 6.33, 'active', 64, 'synthetic'),
  ('pfc-synthetic-065', 1, '韩定+S钩+定型', '["韩定", "S钩", "定型"]'::jsonb, 12.34, 'active', 65, 'synthetic'),
  ('pfc-synthetic-066', 1, '韩定+S钩+花边', '["韩定", "S钩", "花边"]'::jsonb, 7.07, 'active', 66, 'synthetic'),
  ('pfc-synthetic-067', 1, '韩定+S钩+扣环', '["韩定", "S钩", "扣环"]'::jsonb, 5.03, 'active', 67, 'synthetic'),
  ('pfc-synthetic-068', 1, '韩定+S钩+超高+超宽', '["韩定", "S钩", "超高", "超宽"]'::jsonb, 9.54, 'active', 68, 'synthetic'),
  ('pfc-synthetic-069', 1, '韩定+S钩+超高+定型', '["韩定", "S钩", "超高", "定型"]'::jsonb, 7.59, 'active', 69, 'synthetic'),
  ('pfc-synthetic-070', 1, '韩定+S钩+超高+花边', '["韩定", "S钩", "超高", "花边"]'::jsonb, 7.64, 'active', 70, 'synthetic'),
  ('pfc-synthetic-071', 1, '韩定+S钩+超高+扣环', '["韩定", "S钩", "超高", "扣环"]'::jsonb, 5.99, 'active', 71, 'synthetic'),
  ('pfc-synthetic-072', 1, '韩定+S钩+超宽+定型', '["韩定", "S钩", "超宽", "定型"]'::jsonb, 7.81, 'active', 72, 'synthetic'),
  ('pfc-synthetic-073', 1, '韩定+S钩+超宽+花边', '["韩定", "S钩", "超宽", "花边"]'::jsonb, 8.49, 'active', 73, 'synthetic'),
  ('pfc-synthetic-074', 1, '韩定+S钩+超宽+扣环', '["韩定", "S钩", "超宽", "扣环"]'::jsonb, 8.03, 'active', 74, 'synthetic'),
  ('pfc-synthetic-075', 1, '韩定+S钩+定型+花边', '["韩定", "S钩", "定型", "花边"]'::jsonb, 3.10, 'active', 75, 'synthetic'),
  ('pfc-synthetic-076', 1, '韩定+S钩+定型+扣环', '["韩定", "S钩", "定型", "扣环"]'::jsonb, 6.16, 'active', 76, 'synthetic'),
  ('pfc-synthetic-077', 1, '韩定+S钩+花边+扣环', '["韩定", "S钩", "花边", "扣环"]'::jsonb, 6.88, 'active', 77, 'synthetic'),
  ('pfc-synthetic-078', 1, '韩定+S钩+超高+超宽+定型', '["韩定", "S钩", "超高", "超宽", "定型"]'::jsonb, 3.16, 'active', 78, 'synthetic'),
  ('pfc-synthetic-079', 1, '韩定+S钩+超高+超宽+花边', '["韩定", "S钩", "超高", "超宽", "花边"]'::jsonb, 11.56, 'active', 79, 'synthetic'),
  ('pfc-synthetic-080', 1, '韩定+S钩+超高+超宽+扣环', '["韩定", "S钩", "超高", "超宽", "扣环"]'::jsonb, 14.96, 'active', 80, 'synthetic'),
  ('pfc-synthetic-081', 1, '韩定+S钩+超高+定型+花边', '["韩定", "S钩", "超高", "定型", "花边"]'::jsonb, 8.70, 'active', 81, 'synthetic'),
  ('pfc-synthetic-082', 1, '韩定+S钩+超高+定型+扣环', '["韩定", "S钩", "超高", "定型", "扣环"]'::jsonb, 5.41, 'active', 82, 'synthetic'),
  ('pfc-synthetic-083', 1, '韩定+S钩+超高+花边+扣环', '["韩定", "S钩", "超高", "花边", "扣环"]'::jsonb, 13.49, 'active', 83, 'synthetic'),
  ('pfc-synthetic-084', 1, '韩定+S钩+超宽+定型+花边', '["韩定", "S钩", "超宽", "定型", "花边"]'::jsonb, 5.39, 'active', 84, 'synthetic'),
  ('pfc-synthetic-085', 1, '韩定+S钩+超宽+定型+扣环', '["韩定", "S钩", "超宽", "定型", "扣环"]'::jsonb, 10.04, 'active', 85, 'synthetic'),
  ('pfc-synthetic-086', 1, '韩定+S钩+超宽+花边+扣环', '["韩定", "S钩", "超宽", "花边", "扣环"]'::jsonb, 10.59, 'active', 86, 'synthetic'),
  ('pfc-synthetic-087', 1, '韩定+S钩+定型+花边+扣环', '["韩定", "S钩", "定型", "花边", "扣环"]'::jsonb, 14.39, 'active', 87, 'synthetic'),
  ('pfc-synthetic-088', 1, '韩定+S钩+超高+超宽+定型+花边', '["韩定", "S钩", "超高", "超宽", "定型", "花边"]'::jsonb, 9.52, 'active', 88, 'synthetic'),
  ('pfc-synthetic-089', 1, '韩定+S钩+超高+超宽+定型+扣环', '["韩定", "S钩", "超高", "超宽", "定型", "扣环"]'::jsonb, 3.18, 'active', 89, 'synthetic'),
  ('pfc-synthetic-090', 1, '韩定+S钩+超高+超宽+花边+扣环', '["韩定", "S钩", "超高", "超宽", "花边", "扣环"]'::jsonb, 10.38, 'active', 90, 'synthetic'),
  ('pfc-synthetic-091', 1, '韩定+S钩+超高+定型+花边+扣环', '["韩定", "S钩", "超高", "定型", "花边", "扣环"]'::jsonb, 6.36, 'active', 91, 'synthetic'),
  ('pfc-synthetic-092', 1, '缎带', '["缎带"]'::jsonb, 14.15, 'active', 92, 'synthetic')
ON CONFLICT (id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 特殊选项对客单价：16 条 `trigger_kind='option'` 行（元/套）—— 设计 §7 的 L3②
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 按**规则行 id** 定位（`rr-v70-*` = V71 种的 26 条规则里的 16 条 option 行）。
-- `WHERE customer_unit_price IS NULL` ⇒ 重跑空转、**不覆盖商家已改的价**；
-- `AND trigger_kind = 'option'` ⇒ 只可能命中 option 行（非 option 行恒 NULL，设计 §4.1）。
UPDATE production_route_rules AS r
   SET customer_unit_price = v.unit_price,
       updated_at = NOW()
  FROM (VALUES
  ('rr-v70-20', 3.17),
  ('rr-v70-18', 9.87),
  ('rr-v70-23', 6.17),
  ('rr-v70-24', 7.54),
  ('rr-v70-14', 4.58),
  ('rr-v70-15', 5.66),
  ('rr-v70-17', 1.32),
  ('rr-v70-19', 6.99),
  ('rr-v70-25', 8.83),
  ('rr-v70-21', 8.41),
  ('rr-v70-11', 2.70),
  ('rr-v70-12', 4.35),
  ('rr-v70-13', 5.03),
  ('rr-v70-16', 1.37),
  ('rr-v70-22', 7.89),
  ('rr-v70-26', 8.63)
  ) AS v(id, unit_price)
 WHERE r.id = v.id
   AND r.trigger_kind = 'option'
   AND r.customer_unit_price IS NULL;
