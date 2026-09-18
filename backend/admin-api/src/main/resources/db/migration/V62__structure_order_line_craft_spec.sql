-- 下单行要素结构化（issue #4362，S1；用户裁定 2026-09-19「部位不是必填的」）
-- + 「四爪钩/四叉钩」从 craft 语义摘出（issue #4365 阶段 1 ②，同批落地）
--
-- ## 为什么要有这个迁移（缺陷形态）
-- 真值源 §1 的**下单行要素**（部位/工艺/开数/加工类型/是否定型/褶倍/褶距/总褶数/对花/转角）
-- 此前**没有列**：要么埋在 `order_items.processing_info` JSONB 里（`#4346` 起才写进去），
-- 要么只在 C 端澄清清单里被问过却从不落库。后果不是"少个展示字段"——
-- 工序库路线是**按部位×工艺索引**的，取不到就只能靠加工项名**猜**（实证 V58：
-- 纱帘订单拿到布帘的 11 道工序 ⇒ 工序与计件工资全错）。
--
-- ## 全部 nullable，**不设必填校验**（用户裁定）
-- 「部位不是必填的」⇒ 本迁移**不加 NOT NULL、不加默认值、不加 CHECK 枚举**。
-- 派生路径**不退场**：没填部位/工艺的单一律存在 ⇒ `deriveRouteKey` + 信号映射表是
-- **长期兜底**（代码注释里「待订单侧补字段后连同信号表一起退场」的表述**已作废**）。
--
-- ## 列名口径（与既有键名逐字对齐，不造第二套词汇）
-- 工艺规格键（`processing_info` 顶层 camelCase）→ 列（snake_case）：
--   curtainType→curtain_type / craft→craft / openCount→open_count / cuttingMode→cutting_mode
--   / isShaped→is_shaped / pleatSpacing→pleat_spacing / hasPattern→has_pattern / corner→corner
-- 算料输出键（`CALC_INFO_KEYS` 白名单，本来就是 snake_case）→ 列名**原样**：
--   fullness（理论褶倍）/ fullness_actual（实际褶倍）/ pleat_count（总褶数）
-- ⇒ 快照读取（`ProcessingOrderService.buildSnapshot`）无需任何键名映射。
--
-- ## ② 信号映射层：「四爪钩/四叉钩」指向**主线**，不再是独立路线键
-- 用户裁定（#4365）：「四爪钩/穿钩」是**加工项（配件）**，工艺（安装工艺＝打褶/悬挂方式）
-- **单值**，两者不是并列维度。V60 的种子里这两行把 `craft` 写成了 `四爪钩`
-- （逐条抄自迁移前的 `CRAFT_KEYWORDS` 常量表）⇒ 派生键会取到「布帘×四爪钩」这条**独立路线**，
-- 与裁定冲突。本迁移把这两行指向**主线工艺**（`韩褶` = `ProcessingOrderService.DEFAULT_CRAFT`，
-- 即真值源 §3 的 11 道主线）。
-- ⚠️ **不改 `production_routings` 的键**（阶段 3 才做数据迁移，等 #4261 客户清单）：
-- 「布帘×四爪钩」路线**原样保留**（存量加工单要能回溯），只是不再有信号指向它。
-- ⚠️ 「穿钩-*」条件工序**不在本迁移**：工序名/单价属客户数据（#4261），
-- 阶段 2/3 才接线（`production_option_routings`），本阶段只做「不再当独立路线键」。
--
-- ## 幂等（MigrationRunner 要求所有 SQL 可重复执行）
-- `ADD COLUMN IF NOT EXISTS`；`UPDATE ... WHERE craft = '四爪钩'` 重跑后 0 行受影响（终态确定）。
--
-- ## 不改已应用的迁移
-- V60/V61 已发布 ⇒ 整份按文件名 skip，往里加行在存量环境**永远不生效**。
-- 故本单的 DDL/DML 一律走新迁移 V62（V61 已被 #4351 占用）。

-- ── ① order_items 的下单行要素列（全部 nullable，无校验）──
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS curtain_type VARCHAR(16);
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS craft VARCHAR(16);
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS open_count INTEGER;
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS cutting_mode VARCHAR(16);
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS is_shaped BOOLEAN;
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS fullness DECIMAL(6,2);
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS fullness_actual DECIMAL(6,2);
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS pleat_spacing DECIMAL(6,3);
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS pleat_count INTEGER;
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS has_pattern BOOLEAN;
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS corner VARCHAR(32);

COMMENT ON COLUMN order_items.curtain_type IS
    '部位/帘种（V62，issue #4362）：布帘/纱帘/帘头 —— 工序库路线**按部位索引**（production_routings.curtain_type）。**可空**（用户裁定「部位不是必填的」）⇒ 空值时加工单侧走派生兜底；不设必填校验';
COMMENT ON COLUMN order_items.craft IS
    '安装工艺（V62，issue #4362；issue #4365 冻结语义 = **打褶/悬挂方式**）：韩褶/打孔/穿杆/平幔（罗马帘）。**单值**。⚠️「四爪钩/四叉钩」是**加工项（配件）不是工艺**（用户裁定），不进本列 —— 它由 processingItems 携带并驱动「要不要穿钩」；不设必填校验';
COMMENT ON COLUMN order_items.open_count IS
    '打开方式（开数，V62）：1 单开 / 2 双开·对开 / 4 四开。对开总折数必须为偶数（真值源 §8）；可空';
COMMENT ON COLUMN order_items.cutting_mode IS
    '加工类型（V62）：定高买宽 / 定宽买高 —— 决定是否出现 `裁高-布`（issue #4343）；取值来自算料 formula_used；可空';
COMMENT ON COLUMN order_items.is_shaped IS
    '是否定型（V62）：部位级开关，打褶后蒸烫固定褶形；加工单实例化时 false ⇒ 剔除 定型-布/复烫-布；可空（缺值＝不定型，与既有接线同口径）';
COMMENT ON COLUMN order_items.fullness IS
    '理论褶倍（V62）：名义倍数（如 2.00）。与 fullness_actual **分开存** —— 实证 用料 12.300 ÷ 成品宽 6.6 ≈ 1.86 ≠ 2.00，实际用料按实际褶倍算（issue #4344 §二）；可空';
COMMENT ON COLUMN order_items.fullness_actual IS
    '实际褶倍（V62）：由实际用料反算（如 1.86）。与理论褶倍是两个独立事实（issue #4344 数值交叉验证已证明不是冗余字段）；可空';
COMMENT ON COLUMN order_items.pleat_spacing IS
    '褶距（V62，单位：米，韩褶默认 0.1）：实证 部位备注「公式--48个折」+ 四开 ⇒ 12 折/开、褶距 ≈ 13.75cm（issue #4344 §二）；可空';
COMMENT ON COLUMN order_items.pleat_count IS
    '总褶数（V62）：与 production_position_operations 的应做数量口径对齐（韩褶-布 的 qty 单位＝折，读 pleat_count）；可空（缺值 ⇒ 加工单侧 qty_source=fallback）';
COMMENT ON COLUMN order_items.has_pattern IS
    '是否对花（V62）：定宽买高时每幅加一个花距；可空（缺值＝不按对花加料）';
COMMENT ON COLUMN order_items.corner IS
    '转角（V62）：转角形态（取自 C 端澄清清单的窗型：平开/落地/飘窗/转角/L窗）。它**影响开数与片数** ⇒ 属算料输入，不该只停在澄清提示（issue #4344 建议 6）；自由文本、可空、不设枚举（形态未由客户冻结）';

-- ── ② 信号映射层：四爪钩/四叉钩 → 主线工艺（不再当独立路线键）──
-- 只改「当前仍指向 四爪钩」的行（`WHERE craft = '四爪钩'`）：终态确定、重跑 0 行受影响，
-- 且**不会**把商家后来手工改过的行再改回去（商家可配面优先）。
UPDATE production_route_signals
   SET craft = '韩褶',
       updated_at = NOW()
 WHERE signal IN ('四爪钩', '四叉钩')
   AND craft = '四爪钩'
   AND deleted = 0;
