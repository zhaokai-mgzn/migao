package com.migao.admin.service;

import java.math.BigDecimal;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 工人读面「部位明细键」的**唯一一份**键清单与写入口径（母单 #6901，面①）。
 *
 * <h2>为什么要有这个类（本仓反复复发的形态：同一件事各写一份）</h2>
 * <p>工人端**三条**读面都在下发「这个部位是什么规格」，而它们此前各自拼键：</p>
 * <ul>
 *   <li>{@code ProductionScanService} 的扫码详情面（{@code set_overview.positions[]} /
 *       旧码 {@code selections[].positions[]}）；</li>
 *   <li>{@code ProductionService#buildPositions}（{@code GET /api/admin/production/orders/{id}/operations}
 *       与工人端点）；</li>
 *   <li>{@code WorkerCuttingHeightService#positionRow}（机台屏一 `/api/worker/production/cutting-height`）。</li>
 * </ul>
 * <p>键集各写一份 ⇒ 「加了一个字段，某一屏静默缺失」（issue #6901 的原始抱怨：
 * 工人屏上没有货号 / 颜色 / 门幅 / 实际褶倍 / 总褶数 / 幅数 / 用料公式 / 档位 / 花距 / 批号 …）。
 * ⇒ 键清单与「键名怎么翻译」**只在本类写一次**，三条读面都调它。</p>
 *
 * <h2>键名口径（🔴 一律 snake_case，与 {@code getOperations.positions[]} 逐字同名）</h2>
 * <p>快照里有两种来源形态，本类**只在此处**归一：</p>
 * <ul>
 *   <li><b>算料输出键</b>（{@code OrderLineCraftFields.CALC_OUTPUT_SNAPSHOT_KEYS}）本来就是 snake_case
 *       —— 逐字搬；</li>
 *   <li><b>工艺规格 / 商品身份键</b>来自 {@code order_items.processing_info} 的**扁平 camelCase**
 *       （写侧口径）或 {@code OrderLineCraftFields.toSnapshotKeys} 的 camelCase —— 按
 *       {@link #SNAPSHOT_SOURCE_KEYS} 翻译一次。</li>
 * </ul>
 * <p>五个键名**刻意与快照同名**（不另立别名）：{@code curtain_type} / {@code open_count} /
 * {@code cutting_mode} / {@code is_shaped} / {@code fullness} —— 它们此前已由 P0-C（issue #5161）
 * 定死为这几个名字，改名就是同一件事实两个名字。</p>
 *
 * <h2>写入口径 = <b>只加不改</b>（{@code putIfAbsent}）</h2>
 * <p>调用方可能**已经**按自己的来源填过某些键（机台面就是：{@code width}/{@code height}/{@code craft}
 * 取自 {@code order_items} 列、{@code fabric_meters} 取自 {@code fabricMeters(scan)}）⇒
 * 本类**绝不覆盖**已有键的已有值（{@code putIfAbsent} 语义）——「只加键」不是「顺手换取值来源」。</p>
 *
 * <h2>缺值口径</h2>
 * <p>缺值 ⇒ <b>键恒在且为 {@code null}</b>（先铺满全键的 {@code null}，再按在场值覆盖）——
 * 不补默认值、不折 0 / false，也不省键（消费方不必写「有没有这个键」的分支）。</p>
 */
final class PositionDetailFields {

    private PositionDetailFields() {
    }

    /**
     * 商品身份键（母单 #6901 组 1）：品名 / 货号 / 颜色 / 门幅 / 售卖方式 / 数量单位。
     *
     * <p>取值面 = 订单行 {@code processing_info}（与 {@code ProcessingOrderService#buildSnapshot}
     * 的 {@code copyIfPresent(pi, entry, "skuCode", "sku")} 等**同一批键**）—— 快照是加工单的固化真相，
     * 在扫码侧另算一份就是第二份口径。</p>
     */
    static final List<String> PRODUCT_IDENTITY_KEYS = List.of(
            "product_name", "sku", "color_name", "door_width", "selling_method", "unit");

    /** 规格尺寸键（组 2）：{@code order_items} 的 V63 列。 */
    static final List<String> SPEC_SIZE_KEYS = List.of("width", "height");

    /**
     * 加工信息键（组 3）：实际褶倍 / 总褶数 / 每片褶数 / 幅数 / 用料公式 / 档位 / 特殊选项 /
     * 款式 / 是否对花 / 花距 / 加工费米数 / 算料公式 / 部位 / 安装工艺 / 加工类型 / 开数 / 是否定型 / 理论褶倍。
     */
    static final List<String> CRAFT_DETAIL_KEYS = List.of(
            "curtain_type", "craft", "cutting_mode", "open_count", "is_shaped",
            "style", "fullness", "fullness_actual", "pleat_count", "per_panel_pleats",
            "panels", "has_pattern", "pattern_repeat",
            "formula", "craft_tier", "special_options",
            "processing_meters", "formula_text");

    /** 算料 / 排料键（组 4）：面料米数（snake_case，逐字搬自引擎输出）。 */
    static final List<String> CALC_DETAIL_KEYS = List.of("fabric_meters");

    /** 派工键（组 5）：批号 / 指派米数 / 组件（主布 / 纱 / 帘头）。 */
    static final List<String> ASSIGNMENT_DETAIL_KEYS = List.of(
            "batch_no", "batch_meters", "component_role");

    /** 部位备注（组 6）：键名 {@code remark}（issue #5685）—— 不新增 {@code position_remark} 别名。 */
    static final List<String> REMARK_KEYS = List.of("remark");

    /**
     * 扫码读面下发的**全部**部位明细键（键**恒在**）。
     *
     * <p>⚠️ P0-C（issue #5161）的 9 键是它的**真子集**（{@code width} / {@code height} / {@code craft} /
     * {@code curtain_type} / {@code open_count} / {@code cutting_mode} / {@code fullness} /
     * {@code is_shaped} / {@code fabric_meters}）⇒ 本次是**只加键**，既有 9 键的名字与取值口径一字未动。</p>
     */
    static final List<String> DETAIL_KEYS = List.copyOf(allKeys());

    /**
     * 快照源键 → 下发键（{@code null} = 逐字同名，无需翻译）。
     *
     * <p>🔴 <b>这是唯一一处键名翻译</b>：{@code OrderLineCraftFields.toSnapshotKeys} 与
     * {@code processing_info} 都是 camelCase，而工人读面是 snake_case —— 翻译散落两处必然漂移。</p>
     */
    private static final Map<String, String> SNAPSHOT_SOURCE_KEYS = Map.ofEntries(
            // 商品身份
            Map.entry("product_name", "productName"),
            Map.entry("sku", "skuCode"),
            Map.entry("color_name", "colorName"),
            Map.entry("door_width", "doorWidth"),
            Map.entry("selling_method", "sellingMethod"),
            Map.entry("unit", "unit"),
            // 工艺规格
            Map.entry("curtain_type", "curtainType"),
            Map.entry("craft", "craft"),
            Map.entry("cutting_mode", "cuttingMode"),
            Map.entry("open_count", "openCount"),
            Map.entry("is_shaped", "isShaped"),
            Map.entry("style", "style"),
            Map.entry("fullness", "fullness"),
            Map.entry("fullness_actual", "fullness_actual"),
            Map.entry("pleat_count", "pleat_count"),
            Map.entry("per_panel_pleats", "per_panel_pleats"),
            Map.entry("panels", "panels"),
            Map.entry("has_pattern", "hasPattern"),
            Map.entry("pattern_repeat", "patternRepeat"),
            Map.entry("formula", "formula"),
            Map.entry("craft_tier", "craftTier"),
            Map.entry("special_options", "specialOptions"),
            Map.entry("processing_meters", "processingMeters"),
            Map.entry("formula_text", "formulaText"),
            // 派工
            Map.entry("component_role", "componentRole"),
            // 部位备注（issue #5685）
            Map.entry("remark", "remark"));

    /**
     * **只**在 {@code order_items.processing_info} 里才有的键（`ProcessingOrderService#buildSnapshot`
     * 逐键搬的同一批；{@code toSnapshotKeys} 只覆盖工艺**列**，覆盖不到这些）——
     * {@code ProductionService#orderSpecByItemId} 把它们**逐字**取进规格快照
     * ⇒ 三条工人读面（扫码详情 / getOperations / 机台裁高）都能拿到同一份。
     *
     * <p>⚠️ 这里的键名是 **{@code processing_info} 的写侧口径**（扁平 camelCase），
     * 不是下发键 —— 下发键仍在 {@link #SNAPSHOT_SOURCE_KEYS} 里翻译一次。</p>
     */
    static final List<String> PROCESSING_INFO_SOURCE_KEYS = List.of(
            // 商品身份（`buildSnapshot` 的 `copyIfPresent(pi, entry, "skuCode", "sku")` 同一批）
            "skuCode", "colorName", "doorWidth", "sellingMethod", "unit",
            // 加工规格（`CRAFT_SPEC_SNAPSHOT_KEYS` 里**没有**对应列的那几个）
            "style", "hasPattern", "patternRepeat", "formula", "craftTier", "specialOptions",
            "processingMeters", "formulaText", "componentRole");

    /** 数字键（wire 上必须是数字；快照里 `processing_info` 的引擎值可能是字符串）。 */
    private static final Set<String> NUMERIC_KEYS = Set.of(
            "width", "height", "fullness", "fullness_actual", "fabric_meters",
            "pattern_repeat", "batch_meters", "processing_meters");

    private static List<String> allKeys() {
        Set<String> keys = new LinkedHashSet<>(PRODUCT_IDENTITY_KEYS);
        keys.addAll(SPEC_SIZE_KEYS);
        keys.addAll(CRAFT_DETAIL_KEYS);
        keys.addAll(CALC_DETAIL_KEYS);
        keys.addAll(ASSIGNMENT_DETAIL_KEYS);
        keys.addAll(REMARK_KEYS);
        return List.copyOf(keys);
    }

    /**
     * 给一个部位行**只加不改**地补齐明细键（{@code putIfAbsent} 语义）。
     *
     * @param view     部位行（就地改；调用方传入的通常是新建的 {@code LinkedHashMap}）
     * @param snapshot 该订单行的规格快照（{@code ProductionService#orderSpecByItemId} 的那一份；
     *                 {@code null} = 取不到订单行 ⇒ 全键恒在为 {@code null}）
     */
    static void fillDetailKeys(Map<String, Object> view, Map<String, Object> snapshot) {
        fillDetailKeys(view, snapshot, Set.of());
    }

    /**
     * 同上，但**跳过**部分键（机台面用：它已有 `position_remark` 这个**同一事实**的键名，
     * 不得再落一个 `remark` 别名 —— 同一面上同一事实两个键名是本仓明令禁止的形态）。
     *
     * @param excludedKeys 本读面**不**下发的键（调用方负责说明为什么）
     */
    static void fillDetailKeys(Map<String, Object> view, Map<String, Object> snapshot,
                               Collection<String> excludedKeys) {
        if (view == null) {
            return;
        }
        for (String key : DETAIL_KEYS) {
            if (excludedKeys.contains(key)) {
                continue;
            }
            view.putIfAbsent(key, valueOf(snapshot, key));
        }
    }

    /**
     * 一个键在快照里的值（**在场才给值**；缺席 ⇒ {@code null}）。
     *
     * <p>键名翻译见 {@link #SNAPSHOT_SOURCE_KEYS}；{@code sku} 兼容存量单的裸 {@code sku} 键
     * （快照生成侧 {@code copyIfPresent(pi, entry, "skuCode", "sku")} 的同一容错，issue #5174）。</p>
     */
    static Object valueOf(Map<String, Object> snapshot, String key) {
        if (snapshot == null) {
            return null;
        }
        String sourceKey = SNAPSHOT_SOURCE_KEYS.getOrDefault(key, key);
        // 🔴 **两种在场形态**：① 翻译后的**快照键**（camelCase，`toSnapshotKeys` / `processing_info` 口径）；
        // ② 与下发键**逐字同名**的键（`ProductionService#orderSpecByItemId` 明确落下的 `product_name` /
        // `width` / `height` 就是这一形态）。只查 ① 会静默丢掉它们（本单第一版真踩过：`product_name`
        // 恒 null）。**在场**判据用 `containsKey`（不是「值非 null」）⇒ 显式 `0` / `false` / 空串照旧留下。
        Object value = snapshot.containsKey(sourceKey) ? snapshot.get(sourceKey) : snapshot.get(key);
        if (value == null) {
            return null;
        }
        return NUMERIC_KEYS.contains(key) ? decimalOrRaw(value) : value;
    }

    /**
     * 数字键的**类型**归一（值不动，只保证 wire 上是数字）。
     *
     * <p>快照值有两种来源：{@code order_items} 的列（{@link BigDecimal}）与 {@code processing_info}
     * 里引擎落的值（**可能是字符串**，如 {@code "12.35"}）。解析不了 ⇒ **原样返回**（不吞值、
     * 不猜 0；口径同 {@code OrderLineCraftFields.decimalOrNull} 的宽松判定，但**不打印 WARN**：
     * 规格列可空是常态）。</p>
     */
    private static Object decimalOrRaw(Object raw) {
        if (raw instanceof BigDecimal) {
            return raw;
        }
        if (raw instanceof Number number) {
            return new BigDecimal(number.toString());
        }
        try {
            return new BigDecimal(String.valueOf(raw).trim());
        } catch (NumberFormatException notANumber) {
            return raw;
        }
    }
}
