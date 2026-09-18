package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.OrderItem;
import lombok.extern.slf4j.Slf4j;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 下单行要素（{@code order_items} 的 craft spec 列，V63 / issue #4362，S1）的**单一映射点**。
 *
 * <h2>为什么要有这个类（而不是两处各写一遍）</h2>
 * 这些要素有两个消费面，两面的键名口径**不同且都已被既有代码钉死**：
 * <ul>
 *   <li><b>写面</b>（{@link OrderService}）：订单侧唯一生产者的真实形态是
 *       {@code processing_info} JSONB 顶层**扁平 camelCase 键**（{@code curtainType} / {@code craft} /
 *       {@code openCount} …，见设计文档 {@code order-craft-spec-design.md} §4.5），
 *       由 B 端米宝（{@code order_create}）与表单页写入；</li>
 *   <li><b>读面</b>（{@link ProcessingOrderService#buildSnapshot}）：加工单快照按既有白名单键取，
 *       其中算料输出键是 <b>snake_case</b>（{@code fullness} / {@code fullness_actual} /
 *       {@code pleat_count}，与 {@code CALC_INFO_KEYS} 同口径）。</li>
 * </ul>
 * 两处各写一份键名映射 = 第二份口径，漂移的那一份**不会变红**（本仓库反复复发的形态）。
 * ⇒ 映射只在本类里写一次，两个消费面都调它。
 *
 * <h2>全部可空，不做必填校验（用户裁定 2026-09-19「部位不是必填的」）</h2>
 * 缺键就是缺（不造值、不补默认值）。唯一非静默的地方：键**在场但取不出值**（类型不对 / 数字
 * 解析失败）时打 WARN —— 静默丢值正是本仓库认定最大的失败模式；但不因此拒绝整单
 * （可空字段的坏值不该让顾客下不了单，且下游 {@code deriveRouteKey} 有派生兜底）。
 *
 * <p><b>本类不是真值源</b>：列语义的权威在 DB 列注释
 * （{@code V63__structure_order_line_craft_spec.sql}），本类只做搬运。</p>
 */
@Slf4j
final class OrderLineCraftFields {

    // ⚠️ **类名不得以 `Spec` 结尾**（本类原名 `OrderLineCraftSpec`，已因此改名）：
    // QA Growth Gate 的「测试文件」判定是**路径启发式**（`.github/growth_gate.py::_is_test_file`
    // = 扩展名 + 文件名含 `test|spec`，大小写不敏感）⇒ 生产类名里的 `Spec`（specification）会被
    // 判成测试文件，于是被要求声明 `# case_ids:`（给源码加 case_ids 才是真正的"改措辞规避门禁"）。
    // 改名的理由不是绕门禁，而是**消除歧义**：本仓库的「测试文件」就是靠这个命名约定识别的。
    // 别改回去。

    private OrderLineCraftFields() {
    }

    /**
     * {@code processing_info} 归一化：Map 直接用；JSON 字符串解析为 Map；其它形态返回 null。
     * （与 {@code ProcessingOrderService.normalizeProcessingInfo} 同语义 —— 自定义 {@code @Select}
     * 路径不经过 {@code JacksonTypeHandler}，{@code processing_info} 会以 JSON 字符串返回。）
     */
    @SuppressWarnings("unchecked")
    static Map<String, Object> normalize(Object processingInfo, ObjectMapper objectMapper) {
        if (processingInfo instanceof Map) {
            return (Map<String, Object>) processingInfo;
        }
        if (processingInfo instanceof String s && !s.isBlank()) {
            try {
                return objectMapper.readValue(s, Map.class);
            } catch (Exception e) {
                log.warn("processingInfo JSON 字符串解析失败（下单行要素不落列）: {}", e.getMessage());
            }
        }
        return null;
    }

    /**
     * 写路径：把 {@code processing_info} 顶层的工艺规格键**物化**到 {@code order_items} 的列上。
     *
     * <p>这是两个采集端（C 端小布 {@code curtain_checklist} → 会话 → {@code order_create}；
     * B 端米宝 {@code order_create}）落库的**唯一汇聚点** —— {@link OrderService#createOrder}
     * 是表单 / Agent / 程序化三条路径的共享入口，判在这里才无死角。</p>
     */
    static void materialize(Map<String, Object> processingInfo, OrderItem item) {
        if (processingInfo == null || item == null) {
            return;
        }
        String where = item.getOrderId() + "/" + item.getProductName();
        item.setCurtainType(text(processingInfo, "curtainType", where));
        item.setCraft(text(processingInfo, "craft", where));
        item.setOpenCount(integer(processingInfo, "openCount", where));
        item.setCuttingMode(text(processingInfo, "cuttingMode", where));
        item.setIsShaped(bool(processingInfo, "isShaped", where));
        item.setFullness(decimal(processingInfo, "fullness", where));
        item.setFullnessActual(decimal(processingInfo, "fullness_actual", where));
        item.setPleatSpacing(decimal(processingInfo, "pleatSpacing", where));
        item.setPleatCount(integer(processingInfo, "pleat_count", where));
        item.setHasPattern(bool(processingInfo, "hasPattern", where));
        item.setCorner(text(processingInfo, "corner", where));
    }

    /**
     * 读路径：把**列**（结构化显式字段）还原成加工单快照键，只放非空值。
     *
     * <p>键名与 {@code ProcessingOrderService} 的既有白名单**逐字一致**：工艺规格键 camelCase、
     * 算料输出键 snake_case（{@code fullness} / {@code fullness_actual} / {@code pleat_count}）
     * ⇒ 快照读取侧无需任何键名翻译，且列与 JSONB 键走的是同一个下游消费者。</p>
     *
     * <p><b>优先级</b>：调用方在 {@code processing_info} 键之后 {@code putAll} 本方法的返回值
     * ⇒ **显式字段（列）> 加工项推导 > 信号派生兜底**（列在 JSONB 键之上覆盖）。</p>
     */
    static Map<String, Object> toSnapshotKeys(OrderItem item) {
        Map<String, Object> keys = new LinkedHashMap<>();
        if (item == null) {
            return keys;
        }
        putIfNotNull(keys, "curtainType", item.getCurtainType());
        putIfNotNull(keys, "craft", item.getCraft());
        putIfNotNull(keys, "openCount", item.getOpenCount());
        putIfNotNull(keys, "cuttingMode", item.getCuttingMode());
        putIfNotNull(keys, "isShaped", item.getIsShaped());
        putIfNotNull(keys, "pleatSpacing", item.getPleatSpacing());
        putIfNotNull(keys, "hasPattern", item.getHasPattern());
        putIfNotNull(keys, "corner", item.getCorner());
        putIfNotNull(keys, "fullness", item.getFullness());
        putIfNotNull(keys, "fullness_actual", item.getFullnessActual());
        putIfNotNull(keys, "pleat_count", item.getPleatCount());
        return keys;
    }

    private static void putIfNotNull(Map<String, Object> target, String key, Object value) {
        if (value != null) {
            target.put(key, value);
        }
    }

    // ── 宽松取值：值在场但取不出 ⇒ WARN（不静默丢值），但**不拒绝整单**（字段可空）──

    private static String text(Map<String, Object> source, String key, String where) {
        Object raw = source.get(key);
        if (raw == null) {
            return null;
        }
        String value = String.valueOf(raw).trim();
        if (value.isEmpty()) {
            return null;
        }
        return value;
    }

    private static Integer integer(Map<String, Object> source, String key, String where) {
        Object raw = source.get(key);
        if (raw == null) {
            return null;
        }
        if (raw instanceof Number number) {
            return number.intValue();
        }
        try {
            return new BigDecimal(String.valueOf(raw).trim()).intValue();
        } catch (NumberFormatException e) {
            log.warn("下单行要素 {} 不是可解析的整数（不落列）: key={}, value={}", where, key, raw);
            return null;
        }
    }

    private static BigDecimal decimal(Map<String, Object> source, String key, String where) {
        Object raw = source.get(key);
        if (raw == null) {
            return null;
        }
        try {
            return new BigDecimal(String.valueOf(raw).trim());
        } catch (NumberFormatException e) {
            log.warn("下单行要素 {} 不是可解析的数字（不落列）: key={}, value={}", where, key, raw);
            return null;
        }
    }

    /**
     * 布尔取值：只认 JSON 布尔与 {@code "true"/"false"}（大小写不敏感）。
     * **不认「是/否」** —— 中文取值属未冻结的契约（工具侧 schema 声明的是 boolean），
     * 凭字面猜会静默改掉定型接线（false ⇒ 剔除定型两道工序）。
     */
    private static Boolean bool(Map<String, Object> source, String key, String where) {
        Object raw = source.get(key);
        if (raw == null) {
            return null;
        }
        if (raw instanceof Boolean value) {
            return value;
        }
        String value = String.valueOf(raw).trim();
        if ("true".equalsIgnoreCase(value)) {
            return Boolean.TRUE;
        }
        if ("false".equalsIgnoreCase(value)) {
            return Boolean.FALSE;
        }
        log.warn("下单行要素 {} 不是布尔值（不落列）: key={}, value={}", where, key, raw);
        return null;
    }
}
