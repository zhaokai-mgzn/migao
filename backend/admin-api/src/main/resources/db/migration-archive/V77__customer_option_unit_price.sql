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
-- ## 🔴 合成价**一律不得参与取价**（issue #4525 复核裁定的 P1 钱风险，2026-09-19）
--
-- **病根**：`MigrationRunner` 在 **admin-api 启动时执行**本迁移 ⇒ **生产环境一样会跑**；
-- 而 `ProcessingFeeCalculator.pricedCombinations` 只过滤
-- `tenantId + deleted=0 + status='active'`，**不按 `source` 过滤**。
-- ⇒ 若把 92 行合成价以 `status='active'` 种给 `tenant_id=1`，**生产 tenant 1 的真实订单
-- 会按随机价收费**（`source='synthetic'` 只是标记、**无任何门控**）。这与仓库纪律正面冲突
-- （「不发明数据」「改钱不得静默」）。
--
-- **处置（两侧都必须惰性）**：
--   ① **组合价目 92 行**：全部 `status='disabled'` ⇒ `pricedCombinations` 只取 active
--      ⇒ **不参与取价**。商家在「加工费管理」里改价并启用后才生效；
--      未配置的组合仍是 `unpriced`（= 设计原口径「商家必须先配组合，否则加工费为 0」）。
--   ② **特殊选项对客价 16 条**：**不落库**（见 ③ 段）—— `customer_unit_price` 是**列**、
--      没有 `status` 可门控，一旦落库就会参与真实取价（取价侧只判 `IS NOT NULL`）。
--      ⇒ 本迁移**不执行**任何 `UPDATE … SET customer_unit_price`，该列在库中恒为 `NULL`
--      （= 未定价）⇒ 取价侧 `priced:false` + 可行动 hint，**显式可见、不静默按 0 收**。
--      合成值以注释形式保留为测试资产（③ 段），生成器可重算（两次生成逐值相同）。
--
-- **判据（可红）**：`tests/unit_ci_workflows/test_option_fee_seed.py` 的
-- `test_synthetic_combination_rows_are_all_disabled`（有任何一行 active ⇒ 红）与
-- `test_migration_never_prices_customer_unit_price`（出现 `UPDATE … SET customer_unit_price` ⇒ 红）。
-- **e2e fixture 是 mock 面**，不受本条影响（设计 §7 的测试数据三落点里，只有「迁移」这一份
-- 需要惰性化）。
--
-- ## 幂等（`MigrationRunner` 要求所有 SQL 可重复执行）
-- `ADD COLUMN IF NOT EXISTS` + `COMMENT ON COLUMN`（幂等）+ `INSERT ... ON CONFLICT DO NOTHING`
-- （重跑空转）。本迁移**无 UPDATE**（见上「合成价一律不得参与取价」②）。
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
-- ② 组合价目：92 行（91 组合 + 缎带），元/米 —— 设计 §7 的 L3①（**全部 `status='disabled'`**）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- `composition_key` = 归一化口径（trim → 丢空 → 去重 → **Unicode 码点升序** → `+` 连接），
-- 与 `ProcessingFeeCombinationCommandService.compositionKey` **同口径**（唯一实现）。
-- `source='synthetic'` = 合成测试价（**不是**真实价目）；`status='disabled'` = **不参与取价**
-- （见文件头「合成价一律不得参与取价」）。商家改价并启用后本行不再被本迁移触碰
-- （`ON CONFLICT DO NOTHING`）。
--
-- ⚠️ **这 91 个组合名是按 12 个特征确定性枚举的合成集**（`31 + 31 + 29`），
-- **不等于 ERP 图里那 91 项真实名字**（ERP 里点名而本枚举没有的例：`打孔+拼接+倒幅+定型`、
-- `韩折+超高+接高+定型`、`韩折+超高+超宽+定型`…）。真实名单待客户导出后**替换数据**（结构不动）。
INSERT INTO processing_fee_combinations
    (id, tenant_id, composition_key, items, unit_price, status, sort_order, source)
VALUES
  ('pfc-synthetic-001', 1, '打孔+超高', '["打孔", "超高"]'::jsonb, 3.12, 'disabled', 1, 'synthetic'),
  ('pfc-synthetic-002', 1, '打孔+超宽', '["打孔", "超宽"]'::jsonb, 3.43, 'disabled', 2, 'synthetic'),
  ('pfc-synthetic-003', 1, '打孔+定型', '["打孔", "定型"]'::jsonb, 6.35, 'disabled', 3, 'synthetic'),
  ('pfc-synthetic-004', 1, '打孔+花边', '["打孔", "花边"]'::jsonb, 7.39, 'disabled', 4, 'synthetic'),
  ('pfc-synthetic-005', 1, '打孔+扣环', '["打孔", "扣环"]'::jsonb, 8.64, 'disabled', 5, 'synthetic'),
  ('pfc-synthetic-006', 1, '打孔+超高+超宽', '["打孔", "超高", "超宽"]'::jsonb, 4.66, 'disabled', 6, 'synthetic'),
  ('pfc-synthetic-007', 1, '打孔+超高+定型', '["打孔", "超高", "定型"]'::jsonb, 9.72, 'disabled', 7, 'synthetic'),
  ('pfc-synthetic-008', 1, '打孔+超高+花边', '["打孔", "超高", "花边"]'::jsonb, 5.84, 'disabled', 8, 'synthetic'),
  ('pfc-synthetic-009', 1, '打孔+超高+扣环', '["打孔", "超高", "扣环"]'::jsonb, 14.70, 'disabled', 9, 'synthetic'),
  ('pfc-synthetic-010', 1, '打孔+超宽+定型', '["打孔", "超宽", "定型"]'::jsonb, 9.99, 'disabled', 10, 'synthetic'),
  ('pfc-synthetic-011', 1, '打孔+超宽+花边', '["打孔", "超宽", "花边"]'::jsonb, 5.34, 'disabled', 11, 'synthetic'),
  ('pfc-synthetic-012', 1, '打孔+超宽+扣环', '["打孔", "超宽", "扣环"]'::jsonb, 14.78, 'disabled', 12, 'synthetic'),
  ('pfc-synthetic-013', 1, '打孔+定型+花边', '["打孔", "定型", "花边"]'::jsonb, 11.15, 'disabled', 13, 'synthetic'),
  ('pfc-synthetic-014', 1, '打孔+定型+扣环', '["打孔", "定型", "扣环"]'::jsonb, 3.35, 'disabled', 14, 'synthetic'),
  ('pfc-synthetic-015', 1, '打孔+花边+扣环', '["打孔", "花边", "扣环"]'::jsonb, 3.26, 'disabled', 15, 'synthetic'),
  ('pfc-synthetic-016', 1, '打孔+超高+超宽+定型', '["打孔", "超高", "超宽", "定型"]'::jsonb, 5.18, 'disabled', 16, 'synthetic'),
  ('pfc-synthetic-017', 1, '打孔+超高+超宽+花边', '["打孔", "超高", "超宽", "花边"]'::jsonb, 10.38, 'disabled', 17, 'synthetic'),
  ('pfc-synthetic-018', 1, '打孔+超高+超宽+扣环', '["打孔", "超高", "超宽", "扣环"]'::jsonb, 14.43, 'disabled', 18, 'synthetic'),
  ('pfc-synthetic-019', 1, '打孔+超高+定型+花边', '["打孔", "超高", "定型", "花边"]'::jsonb, 13.15, 'disabled', 19, 'synthetic'),
  ('pfc-synthetic-020', 1, '打孔+超高+定型+扣环', '["打孔", "超高", "定型", "扣环"]'::jsonb, 14.48, 'disabled', 20, 'synthetic'),
  ('pfc-synthetic-021', 1, '打孔+超高+花边+扣环', '["打孔", "超高", "花边", "扣环"]'::jsonb, 11.09, 'disabled', 21, 'synthetic'),
  ('pfc-synthetic-022', 1, '打孔+超宽+定型+花边', '["打孔", "超宽", "定型", "花边"]'::jsonb, 11.47, 'disabled', 22, 'synthetic'),
  ('pfc-synthetic-023', 1, '打孔+超宽+定型+扣环', '["打孔", "超宽", "定型", "扣环"]'::jsonb, 12.46, 'disabled', 23, 'synthetic'),
  ('pfc-synthetic-024', 1, '打孔+超宽+花边+扣环', '["打孔", "超宽", "花边", "扣环"]'::jsonb, 13.15, 'disabled', 24, 'synthetic'),
  ('pfc-synthetic-025', 1, '打孔+定型+花边+扣环', '["打孔", "定型", "花边", "扣环"]'::jsonb, 11.85, 'disabled', 25, 'synthetic'),
  ('pfc-synthetic-026', 1, '打孔+超高+超宽+定型+花边', '["打孔", "超高", "超宽", "定型", "花边"]'::jsonb, 3.95, 'disabled', 26, 'synthetic'),
  ('pfc-synthetic-027', 1, '打孔+超高+超宽+定型+扣环', '["打孔", "超高", "超宽", "定型", "扣环"]'::jsonb, 3.52, 'disabled', 27, 'synthetic'),
  ('pfc-synthetic-028', 1, '打孔+超高+超宽+花边+扣环', '["打孔", "超高", "超宽", "花边", "扣环"]'::jsonb, 13.73, 'disabled', 28, 'synthetic'),
  ('pfc-synthetic-029', 1, '打孔+超高+定型+花边+扣环', '["打孔", "超高", "定型", "花边", "扣环"]'::jsonb, 7.91, 'disabled', 29, 'synthetic'),
  ('pfc-synthetic-030', 1, '打孔+超宽+定型+花边+扣环', '["打孔", "超宽", "定型", "花边", "扣环"]'::jsonb, 5.26, 'disabled', 30, 'synthetic'),
  ('pfc-synthetic-031', 1, '打孔+超高+超宽+定型+花边+扣环', '["打孔", "超高", "超宽", "定型", "花边", "扣环"]'::jsonb, 11.31, 'disabled', 31, 'synthetic'),
  ('pfc-synthetic-032', 1, '韩折+超高', '["韩折", "超高"]'::jsonb, 14.04, 'disabled', 32, 'synthetic'),
  ('pfc-synthetic-033', 1, '韩折+超宽', '["韩折", "超宽"]'::jsonb, 8.04, 'disabled', 33, 'synthetic'),
  ('pfc-synthetic-034', 1, '韩折+定型', '["韩折", "定型"]'::jsonb, 11.67, 'disabled', 34, 'synthetic'),
  ('pfc-synthetic-035', 1, '韩折+花边', '["韩折", "花边"]'::jsonb, 11.13, 'disabled', 35, 'synthetic'),
  ('pfc-synthetic-036', 1, '韩折+扣环', '["韩折", "扣环"]'::jsonb, 5.20, 'disabled', 36, 'synthetic'),
  ('pfc-synthetic-037', 1, '韩折+超高+超宽', '["韩折", "超高", "超宽"]'::jsonb, 8.90, 'disabled', 37, 'synthetic'),
  ('pfc-synthetic-038', 1, '韩折+超高+定型', '["韩折", "超高", "定型"]'::jsonb, 3.01, 'disabled', 38, 'synthetic'),
  ('pfc-synthetic-039', 1, '韩折+超高+花边', '["韩折", "超高", "花边"]'::jsonb, 7.33, 'disabled', 39, 'synthetic'),
  ('pfc-synthetic-040', 1, '韩折+超高+扣环', '["韩折", "超高", "扣环"]'::jsonb, 12.44, 'disabled', 40, 'synthetic'),
  ('pfc-synthetic-041', 1, '韩折+超宽+定型', '["韩折", "超宽", "定型"]'::jsonb, 10.44, 'disabled', 41, 'synthetic'),
  ('pfc-synthetic-042', 1, '韩折+超宽+花边', '["韩折", "超宽", "花边"]'::jsonb, 11.32, 'disabled', 42, 'synthetic'),
  ('pfc-synthetic-043', 1, '韩折+超宽+扣环', '["韩折", "超宽", "扣环"]'::jsonb, 10.50, 'disabled', 43, 'synthetic'),
  ('pfc-synthetic-044', 1, '韩折+定型+花边', '["韩折", "定型", "花边"]'::jsonb, 7.89, 'disabled', 44, 'synthetic'),
  ('pfc-synthetic-045', 1, '韩折+定型+扣环', '["韩折", "定型", "扣环"]'::jsonb, 12.84, 'disabled', 45, 'synthetic'),
  ('pfc-synthetic-046', 1, '韩折+花边+扣环', '["韩折", "花边", "扣环"]'::jsonb, 6.60, 'disabled', 46, 'synthetic'),
  ('pfc-synthetic-047', 1, '韩折+超高+超宽+定型', '["韩折", "超高", "超宽", "定型"]'::jsonb, 11.81, 'disabled', 47, 'synthetic'),
  ('pfc-synthetic-048', 1, '韩折+超高+超宽+花边', '["韩折", "超高", "超宽", "花边"]'::jsonb, 9.49, 'disabled', 48, 'synthetic'),
  ('pfc-synthetic-049', 1, '韩折+超高+超宽+扣环', '["韩折", "超高", "超宽", "扣环"]'::jsonb, 7.67, 'disabled', 49, 'synthetic'),
  ('pfc-synthetic-050', 1, '韩折+超高+定型+花边', '["韩折", "超高", "定型", "花边"]'::jsonb, 8.95, 'disabled', 50, 'synthetic'),
  ('pfc-synthetic-051', 1, '韩折+超高+定型+扣环', '["韩折", "超高", "定型", "扣环"]'::jsonb, 14.14, 'disabled', 51, 'synthetic'),
  ('pfc-synthetic-052', 1, '韩折+超高+花边+扣环', '["韩折", "超高", "花边", "扣环"]'::jsonb, 7.74, 'disabled', 52, 'synthetic'),
  ('pfc-synthetic-053', 1, '韩折+超宽+定型+花边', '["韩折", "超宽", "定型", "花边"]'::jsonb, 8.53, 'disabled', 53, 'synthetic'),
  ('pfc-synthetic-054', 1, '韩折+超宽+定型+扣环', '["韩折", "超宽", "定型", "扣环"]'::jsonb, 4.65, 'disabled', 54, 'synthetic'),
  ('pfc-synthetic-055', 1, '韩折+超宽+花边+扣环', '["韩折", "超宽", "花边", "扣环"]'::jsonb, 10.28, 'disabled', 55, 'synthetic'),
  ('pfc-synthetic-056', 1, '韩折+定型+花边+扣环', '["韩折", "定型", "花边", "扣环"]'::jsonb, 13.20, 'disabled', 56, 'synthetic'),
  ('pfc-synthetic-057', 1, '韩折+超高+超宽+定型+花边', '["韩折", "超高", "超宽", "定型", "花边"]'::jsonb, 3.39, 'disabled', 57, 'synthetic'),
  ('pfc-synthetic-058', 1, '韩折+超高+超宽+定型+扣环', '["韩折", "超高", "超宽", "定型", "扣环"]'::jsonb, 9.96, 'disabled', 58, 'synthetic'),
  ('pfc-synthetic-059', 1, '韩折+超高+超宽+花边+扣环', '["韩折", "超高", "超宽", "花边", "扣环"]'::jsonb, 11.74, 'disabled', 59, 'synthetic'),
  ('pfc-synthetic-060', 1, '韩折+超高+定型+花边+扣环', '["韩折", "超高", "定型", "花边", "扣环"]'::jsonb, 10.87, 'disabled', 60, 'synthetic'),
  ('pfc-synthetic-061', 1, '韩折+超宽+定型+花边+扣环', '["韩折", "超宽", "定型", "花边", "扣环"]'::jsonb, 13.52, 'disabled', 61, 'synthetic'),
  ('pfc-synthetic-062', 1, '韩折+超高+超宽+定型+花边+扣环', '["韩折", "超高", "超宽", "定型", "花边", "扣环"]'::jsonb, 7.14, 'disabled', 62, 'synthetic'),
  ('pfc-synthetic-063', 1, '韩定+S钩+超高', '["韩定", "S钩", "超高"]'::jsonb, 6.63, 'disabled', 63, 'synthetic'),
  ('pfc-synthetic-064', 1, '韩定+S钩+超宽', '["韩定", "S钩", "超宽"]'::jsonb, 6.33, 'disabled', 64, 'synthetic'),
  ('pfc-synthetic-065', 1, '韩定+S钩+定型', '["韩定", "S钩", "定型"]'::jsonb, 12.34, 'disabled', 65, 'synthetic'),
  ('pfc-synthetic-066', 1, '韩定+S钩+花边', '["韩定", "S钩", "花边"]'::jsonb, 7.07, 'disabled', 66, 'synthetic'),
  ('pfc-synthetic-067', 1, '韩定+S钩+扣环', '["韩定", "S钩", "扣环"]'::jsonb, 5.03, 'disabled', 67, 'synthetic'),
  ('pfc-synthetic-068', 1, '韩定+S钩+超高+超宽', '["韩定", "S钩", "超高", "超宽"]'::jsonb, 9.54, 'disabled', 68, 'synthetic'),
  ('pfc-synthetic-069', 1, '韩定+S钩+超高+定型', '["韩定", "S钩", "超高", "定型"]'::jsonb, 7.59, 'disabled', 69, 'synthetic'),
  ('pfc-synthetic-070', 1, '韩定+S钩+超高+花边', '["韩定", "S钩", "超高", "花边"]'::jsonb, 7.64, 'disabled', 70, 'synthetic'),
  ('pfc-synthetic-071', 1, '韩定+S钩+超高+扣环', '["韩定", "S钩", "超高", "扣环"]'::jsonb, 5.99, 'disabled', 71, 'synthetic'),
  ('pfc-synthetic-072', 1, '韩定+S钩+超宽+定型', '["韩定", "S钩", "超宽", "定型"]'::jsonb, 7.81, 'disabled', 72, 'synthetic'),
  ('pfc-synthetic-073', 1, '韩定+S钩+超宽+花边', '["韩定", "S钩", "超宽", "花边"]'::jsonb, 8.49, 'disabled', 73, 'synthetic'),
  ('pfc-synthetic-074', 1, '韩定+S钩+超宽+扣环', '["韩定", "S钩", "超宽", "扣环"]'::jsonb, 8.03, 'disabled', 74, 'synthetic'),
  ('pfc-synthetic-075', 1, '韩定+S钩+定型+花边', '["韩定", "S钩", "定型", "花边"]'::jsonb, 3.10, 'disabled', 75, 'synthetic'),
  ('pfc-synthetic-076', 1, '韩定+S钩+定型+扣环', '["韩定", "S钩", "定型", "扣环"]'::jsonb, 6.16, 'disabled', 76, 'synthetic'),
  ('pfc-synthetic-077', 1, '韩定+S钩+花边+扣环', '["韩定", "S钩", "花边", "扣环"]'::jsonb, 6.88, 'disabled', 77, 'synthetic'),
  ('pfc-synthetic-078', 1, '韩定+S钩+超高+超宽+定型', '["韩定", "S钩", "超高", "超宽", "定型"]'::jsonb, 3.16, 'disabled', 78, 'synthetic'),
  ('pfc-synthetic-079', 1, '韩定+S钩+超高+超宽+花边', '["韩定", "S钩", "超高", "超宽", "花边"]'::jsonb, 11.56, 'disabled', 79, 'synthetic'),
  ('pfc-synthetic-080', 1, '韩定+S钩+超高+超宽+扣环', '["韩定", "S钩", "超高", "超宽", "扣环"]'::jsonb, 14.96, 'disabled', 80, 'synthetic'),
  ('pfc-synthetic-081', 1, '韩定+S钩+超高+定型+花边', '["韩定", "S钩", "超高", "定型", "花边"]'::jsonb, 8.70, 'disabled', 81, 'synthetic'),
  ('pfc-synthetic-082', 1, '韩定+S钩+超高+定型+扣环', '["韩定", "S钩", "超高", "定型", "扣环"]'::jsonb, 5.41, 'disabled', 82, 'synthetic'),
  ('pfc-synthetic-083', 1, '韩定+S钩+超高+花边+扣环', '["韩定", "S钩", "超高", "花边", "扣环"]'::jsonb, 13.49, 'disabled', 83, 'synthetic'),
  ('pfc-synthetic-084', 1, '韩定+S钩+超宽+定型+花边', '["韩定", "S钩", "超宽", "定型", "花边"]'::jsonb, 5.39, 'disabled', 84, 'synthetic'),
  ('pfc-synthetic-085', 1, '韩定+S钩+超宽+定型+扣环', '["韩定", "S钩", "超宽", "定型", "扣环"]'::jsonb, 10.04, 'disabled', 85, 'synthetic'),
  ('pfc-synthetic-086', 1, '韩定+S钩+超宽+花边+扣环', '["韩定", "S钩", "超宽", "花边", "扣环"]'::jsonb, 10.59, 'disabled', 86, 'synthetic'),
  ('pfc-synthetic-087', 1, '韩定+S钩+定型+花边+扣环', '["韩定", "S钩", "定型", "花边", "扣环"]'::jsonb, 14.39, 'disabled', 87, 'synthetic'),
  ('pfc-synthetic-088', 1, '韩定+S钩+超高+超宽+定型+花边', '["韩定", "S钩", "超高", "超宽", "定型", "花边"]'::jsonb, 9.52, 'disabled', 88, 'synthetic'),
  ('pfc-synthetic-089', 1, '韩定+S钩+超高+超宽+定型+扣环', '["韩定", "S钩", "超高", "超宽", "定型", "扣环"]'::jsonb, 3.18, 'disabled', 89, 'synthetic'),
  ('pfc-synthetic-090', 1, '韩定+S钩+超高+超宽+花边+扣环', '["韩定", "S钩", "超高", "超宽", "花边", "扣环"]'::jsonb, 10.38, 'disabled', 90, 'synthetic'),
  ('pfc-synthetic-091', 1, '韩定+S钩+超高+定型+花边+扣环', '["韩定", "S钩", "超高", "定型", "花边", "扣环"]'::jsonb, 6.36, 'disabled', 91, 'synthetic'),
  ('pfc-synthetic-092', 1, '缎带', '["缎带"]'::jsonb, 14.15, 'disabled', 92, 'synthetic')
ON CONFLICT (id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 特殊选项对客单价：**不落库**（issue #4525 复核裁定 (i)，见文件头「为什么选项价不落库」）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 生成器（tests/unit_ci_workflows/synthetic_processing_fee_data.py）算出的 16 条合成价
-- **只作为测试资产保留在注释里**，不作为 SQL 执行 —— 列 `customer_unit_price` 没有 `status`
-- 可门控，一旦落库就会参与真实取价（生产 tenant 1 会按随机价收费）。
--
-- 生成器重算这些值的命令（两次生成逐值相同）：
--   python3 -c "import sys;sys.path.insert(0,'tests/unit_ci_workflows');\
--     import synthetic_processing_fee_data as s;print(s.option_rows())"
--
-- （规则行 id, 元/套）
--   ('rr-v70-20', 3.17)   -- 余料做帘头
--   ('rr-v70-18', 9.87)   -- 余料做绑带
--   ('rr-v70-23', 6.17)   -- 加logo条
--   ('rr-v70-24', 7.54)   -- 加立边
--   ('rr-v70-14', 4.58)   -- 加花边
--   ('rr-v70-15', 5.66)   -- 加铅块
--   ('rr-v70-17', 1.32)   -- 双眼皮接高
--   ('rr-v70-19', 6.99)   -- 布绑带
--   ('rr-v70-25', 8.83)   -- 扣环
--   ('rr-v70-21', 8.41)   -- 抱枕
--   ('rr-v70-11', 2.70)   -- 拼1次
--   ('rr-v70-12', 4.35)   -- 拼2次
--   ('rr-v70-13', 5.03)   -- 拼3次
--   ('rr-v70-16', 1.37)   -- 接高
--   ('rr-v70-22', 7.89)   -- 纱绑带
--   ('rr-v70-26', 8.63)   -- 防翘扣
