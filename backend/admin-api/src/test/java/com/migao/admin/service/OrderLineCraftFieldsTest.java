package com.migao.admin.service;

// case_ids: OR-008, PG-031

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.OrderItem;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 下单行要素映射的**单一实现点**（V63，issue #4362，S1）。
 *
 * <p>本类存在的理由（为什么不能只靠 {@code OrderServiceTest} 那几条端到端断言）：
 * 键名映射有两个消费面（写面 {@code materialize} → DB 列；读面 {@code toSnapshotKeys} → 加工单快照键），
 * 而两面的**键名口径不同**（工艺规格 camelCase / 算料输出 snake_case）。两处各写一遍 = 第二份口径，
 * 漂移的那一份不会变红。本文件把「逐键一一对应」与「取值宽松规则」钉在**纯函数**层面。</p>
 *
 * <h2>判据</h2>
 * <ol>
 *   <li><b>11 个键逐键落列</b>（Map 形态 + JSON 字符串形态都覆盖 —— 自定义 {@code @Select} 路径
 *       不经过 {@code JacksonTypeHandler}，{@code processing_info} 会是 JSON 字符串）；</li>
 *   <li><b>缺键就是缺</b>（用户裁定「部位不是必填的」⇒ 不造值、不补默认）；</li>
 *   <li><b>读面键名逐字一致</b>：算料输出三个键必须是 snake_case（{@code fullness} /
 *       {@code fullness_actual} / {@code pleat_count}），与 {@code CALC_INFO_KEYS} 同口径 ——
 *       写成 camelCase 会让加工单侧「取不到值」，而那是**静默**的（缺键就缺）；</li>
 *   <li><b>取不出值不静默但也不拒绝整单</b>：类型不对/解析失败 ⇒ 该列留 null（WARN 由实现打，
 *       断言落在「值」上而不是日志文本上 —— 日志是辅助证据，不是判据）。</li>
 * </ol>
 *
 * <p><b>红证（注入式）</b>：① 把 {@code toSnapshotKeys} 里的 {@code pleat_count} 改成
 * {@code pleatCount} ⇒ 判据 3 红；② 把 {@code materialize} 的 {@code isShaped} 那行删掉 ⇒ 判据 1 红；
 * ③ 把 {@code bool} 的 {@code "是"} 分支补上（凭字面猜中文）⇒ 判据 4 红。</p>
 */
@DisplayName("下单行要素映射（V63，issue #4362 S1）")
class OrderLineCraftFieldsTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static Map<String, Object> fullCraftSpec() {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("curtainType", "纱帘");
        info.put("craft", "打孔");
        info.put("openCount", 4);
        info.put("cuttingMode", "定高买宽");
        info.put("isShaped", false);
        info.put("fullness", 2.0);
        info.put("fullness_actual", 1.86);
        info.put("pleatSpacing", 0.1);
        info.put("pleat_count", 48);
        info.put("hasPattern", true);
        info.put("corner", "转角");
        return info;
    }

    @Test
    @DisplayName("判据 1：11 个键逐键落列（Map 形态）")
    void materializeMapsEveryKeyFromMap() {
        OrderItem item = OrderItem.builder().orderId("o1").productName("布艺遮光帘A").build();

        OrderLineCraftFields.materialize(fullCraftSpec(), item);

        assertThat(item.getCurtainType()).isEqualTo("纱帘");
        assertThat(item.getCraft()).isEqualTo("打孔");
        assertThat(item.getOpenCount()).isEqualTo(4);
        assertThat(item.getCuttingMode()).isEqualTo("定高买宽");
        assertThat(item.getIsShaped()).isFalse();
        assertThat(item.getFullness()).isEqualByComparingTo("2.0");
        assertThat(item.getFullnessActual()).isEqualByComparingTo("1.86");
        assertThat(item.getPleatSpacing()).isEqualByComparingTo("0.1");
        assertThat(item.getPleatCount()).isEqualTo(48);
        assertThat(item.getHasPattern()).isTrue();
        assertThat(item.getCorner()).isEqualTo("转角");
    }

    @Test
    @DisplayName("判据 1：JSON 字符串形态（自定义 @Select 路径）同样落列")
    void materializeMapsEveryKeyFromJsonString() throws Exception {
        OrderItem item = OrderItem.builder().orderId("o1").productName("布艺遮光帘A").build();

        OrderLineCraftFields.materialize(
                OrderLineCraftFields.normalize(MAPPER.writeValueAsString(fullCraftSpec()), MAPPER), item);

        assertThat(item.getCurtainType()).isEqualTo("纱帘");
        assertThat(item.getOpenCount()).isEqualTo(4);
        assertThat(item.getPleatCount()).isEqualTo(48);
        assertThat(item.getCorner()).isEqualTo("转角");
    }

    @Test
    @DisplayName("判据 2：缺键就是缺（不造值、不补默认）+ null/空串/非 Map 输入安全")
    void absentKeysStayNull() {
        OrderItem item = OrderItem.builder().orderId("o1").productName("普通商品").build();

        OrderLineCraftFields.materialize(Map.of("sellingMethod", "bulk_cut"), item);
        OrderLineCraftFields.materialize(null, item);
        OrderLineCraftFields.materialize(Map.of("curtainType", "   "), item);
        OrderLineCraftFields.materialize(OrderLineCraftFields.normalize("not-a-json-object", MAPPER), item);

        assertThat(item.getCurtainType()).isNull();
        assertThat(item.getCraft()).isNull();
        assertThat(item.getOpenCount()).isNull();
        assertThat(item.getCuttingMode()).isNull();
        assertThat(item.getIsShaped()).isNull();
        assertThat(item.getFullness()).isNull();
        assertThat(item.getFullnessActual()).isNull();
        assertThat(item.getPleatSpacing()).isNull();
        assertThat(item.getPleatCount()).isNull();
        assertThat(item.getHasPattern()).isNull();
        assertThat(item.getCorner()).isNull();
    }

    @Test
    @DisplayName("判据 3：读面键名逐字一致 —— 算料输出保持 snake_case，工艺规格 camelCase")
    void snapshotKeysUseExactWhitelistNames() {
        OrderItem item = OrderItem.builder().orderId("o1").productName("布艺遮光帘A").build();
        OrderLineCraftFields.materialize(fullCraftSpec(), item);

        assertThat(OrderLineCraftFields.toSnapshotKeys(item)).containsOnlyKeys(
                "curtainType", "craft", "openCount", "cuttingMode", "isShaped", "pleatSpacing",
                "hasPattern", "corner", "fullness", "fullness_actual", "pleat_count");
        // 算料输出键**不得**被写成 camelCase（那样加工单侧取不到值，而缺键是静默的）
        assertThat(OrderLineCraftFields.toSnapshotKeys(item))
                .containsEntry("pleat_count", 48)
                .containsEntry("fullness", new BigDecimal("2.0"))
                .containsEntry("fullness_actual", new BigDecimal("1.86"))
                .doesNotContainKeys("pleatCount", "fullnessActual");
    }

    @Test
    @DisplayName("判据 3：读面只放非空值（列全空 ⇒ 空 map ⇒ 对快照是 no-op）")
    void snapshotKeysSkipNulls() {
        OrderItem empty = OrderItem.builder().orderId("o1").productName("普通商品").build();
        assertThat(OrderLineCraftFields.toSnapshotKeys(empty)).isEmpty();

        OrderItem partial = OrderItem.builder().orderId("o1").productName("x")
                .curtainType("布帘").build();
        assertThat(OrderLineCraftFields.toSnapshotKeys(partial)).containsOnlyKeys("curtainType");
    }

    @Test
    @DisplayName("判据 4：取不出值 ⇒ 该列 null（不静默丢值由实现打 WARN，值层面不猜）")
    void unparseableValuesBecomeNull() {
        OrderItem item = OrderItem.builder().orderId("o1").productName("x").build();
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("openCount", "四开");       // 非数字
        info.put("pleat_count", "48折");      // 带单位的中文
        info.put("isShaped", "是");           // 中文布尔：**不凭字面猜**（猜错会静默改定型接线）
        info.put("hasPattern", 1);            // 数字不是布尔
        info.put("curtainType", "纱帘");      // 同一行里的合法值不受影响

        OrderLineCraftFields.materialize(info, item);

        assertThat(item.getOpenCount()).isNull();
        assertThat(item.getPleatCount()).isNull();
        assertThat(item.getIsShaped()).isNull();
        assertThat(item.getHasPattern()).isNull();
        assertThat(item.getCurtainType()).isEqualTo("纱帘");
    }

    @Test
    @DisplayName("判据 4：布尔只认 JSON 布尔与 true/false（大小写不敏感）")
    void booleanCoercionIsStrict() {
        OrderItem item = OrderItem.builder().orderId("o1").productName("x").build();

        OrderLineCraftFields.materialize(Map.of("isShaped", "TRUE", "hasPattern", Boolean.FALSE), item);

        assertThat(item.getIsShaped()).isTrue();
        assertThat(item.getHasPattern()).isFalse();
    }

    @Test
    @DisplayName("判据 4：数字形态宽松（整数/浮点/数字字符串）但结果类型确定")
    void numericCoercionAcceptsCommonShapes() {
        OrderItem item = OrderItem.builder().orderId("o1").productName("x").build();
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("openCount", 2.0);            // JSON 里 2.0 会被反序列化成 Double
        info.put("pleat_count", "48");          // 字符串数字
        info.put("pleatSpacing", 0.12);
        info.put("fullness", List.of());        // 明显不是数字 ⇒ null（不抛异常炸掉整单）

        OrderLineCraftFields.materialize(info, item);

        assertThat(item.getOpenCount()).isEqualTo(2);
        assertThat(item.getPleatCount()).isEqualTo(48);
        assertThat(item.getPleatSpacing()).isEqualByComparingTo("0.12");
        assertThat(item.getFullness()).isNull();
    }
}
