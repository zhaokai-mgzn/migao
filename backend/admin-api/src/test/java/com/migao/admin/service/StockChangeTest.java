// case_ids: OR-062, PR-123

package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link StockChange} 的契约（issues #6299 / #6300）：<b>它是「变更前/变更后」的唯一载体</b>，
 * 而这两个值只允许来自 sql 的 {@code RETURNING}（{@code ProductSkuMapper#deductStock} /
 * {@code receiveStock}）。
 *
 * <p><b>为什么这个类型的形状也要钉</b>：台账链断裂（#6300）的机制是「读数与写入不是同一条语句」。
 * 只要这个类型<b>能</b>从读快照构造，下一个人就会照着老写法继续用快照 —— 所以本判据盯两件事：</p>
 * <ol>
 *   <li><b>唯一的工厂只能吃 mapper 的 RETURNING 行</b>（{@code from(Map)}）——
 *       类型上就没有「从 {@code ProductSku} / 从 {@code getStock()} 构造」的入口；</li>
 *   <li><b>0 行 ⇒ {@code null}</b>（扣不动 / 没改到），调用方必须显式处理，
 *       <b>不许</b>把 {@code null} 洗成 0（那正是 {@code GREATEST(…,0)} 钳 0 的同族掩盖）。</li>
 * </ol>
 *
 * <p><b>红证</b>：把 {@code from(...)} 改成「null 入参返回 {@code new StockChange(ZERO, ZERO, null)}」
 * ⇒ 第 2 条判据红；把 {@code from(...)} 的强转改成「从任意对象读 {@code getStock()}」⇒ 第 1 条判据红
 * （现源码里没有 {@code ProductSku} 形参 / 没有 {@code getStock()} 调用）。</p>
 */
@DisplayName("StockChange（#6299/#6300）：变更前后只许来自原子语句的 RETURNING 行")
class StockChangeTest {

    @Test
    @DisplayName("判据 1·唯一工厂：只能由 mapper 的 RETURNING 行映射构造（无「从读快照构造」的入口）")
    void onlyFactoryTakesTheReturningRow() throws Exception {
        // 生产者 = 返回 StockChange 的静态方法（返不回 StockChange 的方法造不出读数）
        assertThat(java.util.Arrays.stream(StockChange.class.getDeclaredMethods())
                .filter(m -> java.lang.reflect.Modifier.isStatic(m.getModifiers()))
                .filter(m -> StockChange.class.equals(m.getReturnType()))
                .map(m -> m.getName() + "("
                        + java.util.Arrays.stream(m.getParameterTypes()).map(Class::getSimpleName)
                                .collect(java.util.stream.Collectors.joining(",")) + ")")
                .toList())
                .as("唯一能造出 StockChange 的入口 = from(Map)（吃 mapper 的 RETURNING 行）；"
                        + "多一个吃实体/快照的入口 = 快照读又回来了")
                .containsOnly("from(Map)");
        assertThat(StockChange.class.getDeclaredMethod("from", Map.class))
                .as("唯一工厂的入参必须是 mapper 的 RETURNING 行（Map）")
                .isNotNull();
        assertThat(StockChange.class.getDeclaredConstructors())
                .as("记录（record）的唯一构造器 = 规范构造器（before, after, skuCode）")
                .hasSize(1);
    }

    @Test
    @DisplayName("判据 2·0 行 ⇒ null（不洗成 0）：扣不动 / 没改到时调用方必须显式处理")
    void zeroRowsMapsToNullNotZero() {
        assertThat(StockChange.from(null))
                .as("mapper 回 null（= 0 行）⇒ StockChange 必须是 null，"
                        + "不许用 0/0 冒充「扣到了 0」（那正是 GREATEST 钳 0 的同族掩盖）")
                .isNull();
    }

    @Test
    @DisplayName("判据 3·行映射逐值：RETURNING 的 beforeQuantity/afterQuantity/skuCode 原样透传")
    void mapsReturningColumnsVerbatim() {
        Map<String, Object> row = new HashMap<>();
        row.put("skuCode", "SKU-MB-28");
        row.put("beforeQuantity", new BigDecimal("10.0"));
        row.put("afterQuantity", new BigDecimal("2.0"));

        StockChange change = StockChange.from(row);

        assertThat(change).as("RETURNING 行必须映射成 StockChange（不是 null）").isNotNull();
        assertThat(change.skuCode()).as("台账追溯用货号原样透传").isEqualTo("SKU-MB-28");
        assertThat(change.beforeQuantity()).as("变更前 = SQL RETURNING 的值").isEqualByComparingTo("10.0");
        assertThat(change.afterQuantity()).as("变更后 = SQL RETURNING 的值").isEqualByComparingTo("2.0");
    }

    @Test
    @DisplayName("判据 4·非 BigDecimal 的数值列也能映射（不同 JDBC 驱动/类型返回 BigDecimal 之外的类型时不炸）")
    void mapsNonBigDecimalNumerics() {
        Map<String, Object> row = new HashMap<>();
        row.put("skuCode", "SKU-MB-28");
        row.put("beforeQuantity", "10.0");
        row.put("afterQuantity", 2);

        StockChange change = StockChange.from(row);

        assertThat(change).as("字符串/整数形态的数值列也必须能映射成 BigDecimal").isNotNull();
        assertThat(change.beforeQuantity()).isEqualByComparingTo("10.0");
        assertThat(change.afterQuantity()).isEqualByComparingTo("2");
    }

    @Test
    @DisplayName("判据 5·类型上没有「从读快照构造」的入口（现取源码：无 getStock / 无实体形参）")
    void noSnapshotEntryPointInSource() throws Exception {
        String source = java.nio.file.Files.readString(java.nio.file.Path.of(
                "src/main/java/com/migao/admin/service/StockChange.java"));

        assertThat(source).as("不得出现 getStock()（快照读）—— 那正是 #6300 的缺陷形态")
                .doesNotContain("getStock(");
        assertThat(source).as("不得出现读快照的入口（getStock / selectById）")
                .doesNotContain("getStock(", "selectById");
        System.out.println("[#6300 StockChange] 现取源码长度=" + source.length()
                + " 含 getStock=" + source.contains("getStock("));
    }
}
