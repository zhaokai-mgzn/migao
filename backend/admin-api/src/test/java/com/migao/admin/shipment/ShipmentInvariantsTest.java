// case_ids: OR-045, OR-046, DF-017
package com.migao.admin.shipment;

import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OrderShipmentItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.ShipmentInvariants;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 🔴 <b>发货写面的两条不变式</b>（issue #6157）—— 判定本体 = {@link ShipmentInvariants}，
 * 与「哪条发货路在调它」无关（本类不碰 Spring、不碰 Mapper）。
 *
 * <h3>它补的是哪两个洞（实测读数逐字）</h3>
 * <ol>
 *   <li>{@code quantity=10} 的订单传 {@code shipped_quantity=999} ⇒ 修前 <b>HTTP 2xx</b>、
 *       {@code Σ已发=999.000}（越界 989.000）—— 不变式「累计已发 ≤ 订单量」恒不成立
 *       （{@code acceptance/2026-10-03/shipments-sweep/out/p3-records.json} 的 {@code M1-OVER}）。</li>
 *   <li>同一 {@code order_item_id} 在一个请求里写两行（6+6）⇒ 修前 200、落 2 行、Σ=12 &gt; 10
 *       —— 「每行都不超」的按行校验被合计语义绕过（同 {@code out/} 的 {@code M4-DUP-LINE}）。</li>
 *   <li>{@code shipped_quantity=0.001} 被列精度 {@code numeric(10,2)} 吃成 {@code 0.00} 且仍 200
 *       ⇒ 「已发货但实发 0」（同 {@code out/} 的精度判据）。</li>
 * </ol>
 *
 * <h3>两侧夹住（本类每条判据的形态）</h3>
 * <p>「恰好等于上限 ⇒ 放行」+「超 0.01 ⇒ 拒绝」必须**同时**成立 —— 只判一侧时，把阈值调到 0
 * 也能让「超发被拒」变绿（假绿）。</p>
 *
 * <h3>红证（注入式，见 {@code ShipmentInvariantGuardTest} 的 §三 与 PR body）</h3>
 * <p>把 {@code assertWithinOrderQuantity} 的比较改成 {@code >= 0}（恒不超）⇒ 本类
 * {@code cumulativeOverOrderQuantityIsRejected} / {@code duplicateOrderItemLinesSumBeforeComparing}
 * 当场红；把 {@code assertDbCompatible} 的小数位判定删掉 ⇒ {@code subCentPrecisionIsRejected} 当场红。</p>
 */
@DisplayName("发货写面不变式：累计已发 ≤ 订单量（聚合后）/ 列精度不容吃数据")
class ShipmentInvariantsTest {

    private static final String ITEM = "item-1";
    private static final String OTHER_ITEM = "item-2";

    private static OrderItem item(String id, String quantity) {
        return OrderItem.builder().id(id).orderId("order-1").tenantId(1L)
                .productName("遮光窗帘").quantity(new BigDecimal(quantity)).deleted(0).build();
    }

    private static ShipmentInvariants.ShipmentLine line(String orderItemId, String quantity) {
        return new ShipmentInvariants.ShipmentLine(orderItemId, new BigDecimal(quantity), "米", null, null);
    }

    private static OrderShipmentItem shipped(String orderItemId, String quantity) {
        return OrderShipmentItem.builder().orderItemId(orderItemId)
                .shippedQuantity(new BigDecimal(quantity)).unit("米").build();
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ① 累计已发 ≤ 订单量（两侧夹住 + 请求内聚合）
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("两侧夹住：订单 10 米 —— 恰好发满 10 米放行，超 0.01 ⇒ 拒绝且具名报出差额")
    void cumulativeOverOrderQuantityIsRejected() {
        List<OrderItem> order = List.of(item(ITEM, "10.00"));
        List<OrderShipmentItem> none = List.of();

        // 恰好等于上限 ⇒ 放行（不是「>= 上限就拒」）
        assertThat(ShipmentInvariants.assertWithinOrderQuantity(
                List.of(line(ITEM, "10.00")), none, order)).isEmpty();
        // 超 0.01 ⇒ 拒绝
        List<ShipmentInvariants.Rejection> rejections = ShipmentInvariants.assertWithinOrderQuantity(
                List.of(line(ITEM, "10.01")), none, order);
        assertThat(rejections).hasSize(1);
        assertThat(rejections.get(0).orderItemId()).isEqualTo(ITEM);
        assertThat(rejections.get(0).requested()).isEqualByComparingTo("10.01");
        assertThat(rejections.get(0).allowed()).isEqualByComparingTo("10.00");
        assertThat(rejections.get(0).message()).contains("超出 0.01");
        // 修前实测形态：999 对 10 ⇒ 越界 989.000（同一个判据的极端读数）
        List<ShipmentInvariants.Rejection> over = ShipmentInvariants.assertWithinOrderQuantity(
                List.of(line(ITEM, "999")), none, order);
        assertThat(over).hasSize(1);
        assertThat(over.get(0).message()).contains("超出 989");
    }

    @Test
    @DisplayName("🔴 请求内聚合：同一 order_item_id 两行 6+6 对上限 10 ⇒ 拒绝（求和不放两行）")
    void duplicateOrderItemLinesSumBeforeComparing() {
        List<OrderItem> order = List.of(item(ITEM, "10.00"));

        // 单独看每行都不超（6 ≤ 10）—— 按行校验会被这个形态绕过
        List<ShipmentInvariants.Rejection> rejections = ShipmentInvariants.assertWithinOrderQuantity(
                List.of(line(ITEM, "6"), line(ITEM, "6")), List.of(), order);
        assertThat(rejections).hasSize(1);
        assertThat(rejections.get(0).requested()).isEqualByComparingTo("12");
        // 聚合读数也必须如实 = 12（不是 6）
        assertThat(ShipmentInvariants.cumulativeByOrderItem(
                List.of(line(ITEM, "6"), line(ITEM, "6")), List.of())).containsEntry(ITEM, new BigDecimal("12"));
        // 6+4 = 10 恰好发满 ⇒ 放行（聚合不等于「一律拒两行」）
        assertThat(ShipmentInvariants.assertWithinOrderQuantity(
                List.of(line(ITEM, "6"), line(ITEM, "4")), List.of(), order)).isEmpty();
    }

    @Test
    @DisplayName("累计口径含**已落库**明细：上一张单已发 6 ⇒ 本次 5 累计 11 > 10 拒绝、本次 4 恰好放行")
    void cumulativeIncludesAlreadyPersistedDetails() {
        List<OrderItem> order = List.of(item(ITEM, "10.00"));
        List<OrderShipmentItem> already = List.of(shipped(ITEM, "6.00"));

        assertThat(ShipmentInvariants.assertWithinOrderQuantity(
                List.of(line(ITEM, "4.00")), already, order)).isEmpty();
        List<ShipmentInvariants.Rejection> rejections = ShipmentInvariants.assertWithinOrderQuantity(
                List.of(line(ITEM, "5.00")), already, order);
        assertThat(rejections).hasSize(1);
        assertThat(rejections.get(0).requested()).isEqualByComparingTo("11.00");
    }

    @Test
    @DisplayName("🔴 不属该订单的订单行 ⇒ fail-closed（不把「查不到上限」当「没有上限」）")
    void unknownOrderItemIsRejectedFailClosed() {
        List<ShipmentInvariants.Rejection> rejections = ShipmentInvariants.assertWithinOrderQuantity(
                List.of(line("item-from-other-order", "1.00")), List.of(), List.of(item(ITEM, "10.00")));
        assertThat(rejections).hasSize(1);
        assertThat(rejections.get(0).message()).contains("查不到");
    }

    @Test
    @DisplayName("拿不到订单量（存量脏数据）⇒ 不据此拦货（读不懂 ≠ 超发）；未挂订单行的行无可比上限")
    void unknownLimitDoesNotBlockShipping() {
        // quantity 为空 = 无法判定 ⇒ 放行并如实登记（该边界在 PR 的未固化项里）
        assertThat(ShipmentInvariants.assertWithinOrderQuantity(
                List.of(line(ITEM, "999")), List.of(), List.of(OrderItem.builder().id(ITEM).build()))).isEmpty();
        // 没挂订单行的行（手写/配件行）不参与上限比较
        List<OrderItem> order = List.of(item(ITEM, "10.00"));
        assertThat(ShipmentInvariants.assertWithinOrderQuantity(
                List.of(line(null, "999")), List.of(), order)).isEmpty();
        // 但别的行仍照判（一行无可比对不放过另一行的超发）
        assertThat(ShipmentInvariants.assertWithinOrderQuantity(
                List.of(line(null, "1"), line(ITEM, "11")), List.of(), order)).hasSize(1);
    }

    @Test
    @DisplayName("不改入参：判定是纯函数（不许把聚合写回调用方的明细）")
    void verdictDoesNotMutateInputs() {
        List<OrderShipmentItem> already = new ArrayList<>(List.of(shipped(ITEM, "3.00")));
        List<ShipmentInvariants.ShipmentLine> lines = new ArrayList<>(List.of(line(ITEM, "2.00")));
        ShipmentInvariants.assertWithinOrderQuantity(lines, already, List.of(item(ITEM, "10.00")));
        assertThat(already).hasSize(1);
        assertThat(already.get(0).getShippedQuantity()).isEqualByComparingTo("3.00");
        assertThat(lines).hasSize(1);
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ② 列精度不容吃数据（numeric(10,2)）
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 越界精度 0.001 ⇒ 拒绝（修前被列精度吃成 0.00 且仍 200）；合法两位小数放行")
    void subCentPrecisionIsRejected() {
        assertThat(ShipmentInvariants.assertDbCompatible(List.of(line(ITEM, "0.001")))).hasSize(1);
        assertThat(ShipmentInvariants.assertDbCompatible(List.of(line(ITEM, "0.001")))
                .get(0).message()).contains("列精度").contains("0.00");
        // 两侧夹住：两位小数（含恰好一位 / 两位 / 整数）一律放行
        assertThat(ShipmentInvariants.assertDbCompatible(List.of(
                line(ITEM, "0.01"), line(ITEM, "12.50"), line(ITEM, "10"), line(ITEM, "10.00")))).isEmpty();
        // 尾随零不算小数位（10.00 是 0 位，不是 2 位）
        assertThat(ShipmentInvariants.assertDbCompatible(List.of(line(ITEM, "99999999.99")))).isEmpty();
    }

    @Test
    @DisplayName("整数位不超列宽：numeric(10,2) 放得下 8 位整数，9 位 ⇒ 拒绝")
    void integerWidthIsEnforced() {
        assertThat(ShipmentInvariants.assertDbCompatible(List.of(line(ITEM, "99999999")))).isEmpty();
        assertThat(ShipmentInvariants.assertDbCompatible(List.of(line(ITEM, "100000000")))).hasSize(1);
    }

    @Test
    @DisplayName("🔴 组合形态：同一请求里一行超上限 + 一行精度越界 ⇒ 两条判据各自具名报出")
    void bothInvariantsReportIndependently() {
        List<OrderItem> order = List.of(item(ITEM, "10.00"), item(OTHER_ITEM, "5.00"));
        // 精度：OTHER 行 0.001（上游 parseDetails 会先判正数 + 单位，本层只管列精度）
        assertThat(ShipmentInvariants.assertDbCompatible(List.of(
                line(ITEM, "1.00"), line(OTHER_ITEM, "0.001")))).hasSize(1);
        // 上限：ITEM 行 11 > 10
        assertThat(ShipmentInvariants.assertWithinOrderQuantity(
                List.of(line(ITEM, "11.00"), line(OTHER_ITEM, "1.00")), List.of(), order)).hasSize(1);
    }

    @Test
    @DisplayName("拒绝翻成 4xx：逐条具名 + 明说「未写入任何数据」（不是一句「参数错误」）")
    void rejectionsBecomeActionableValidationErrors() {
        assertThatThrownBy(() -> ShipmentInvariants.assertNoRejections("发货被拒绝", List.of(
                new ShipmentInvariants.Rejection(ITEM, new BigDecimal("12"), new BigDecimal("10"),
                        "累计实发超过订单量：该订单行下单 10，累计已发（含本次）12，超出 2"))))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("累计实发超过订单量")
                .hasMessageContaining("超出 2")
                .hasMessageContaining("未写入任何数据");
        // 0 条拒绝 ⇒ 不抛（放行路径）
        ShipmentInvariants.assertNoRejections("发货被拒绝", List.of());
    }

    @Test
    @DisplayName("🔴 一发定谳：Verdict 同时带两条不变式的拒绝与累计读数（漏判任一条都可判红）")
    void singleVerdictCarriesBothInvariants() {
        List<OrderItem> order = List.of(item(ITEM, "10.00"));
        // 干净形态：两条都空 + 累计读数如实
        ShipmentInvariants.Verdict clean = ShipmentInvariants.verdict(
                List.of(line(ITEM, "10.00")), List.of(shipped(ITEM, "0.00")), order);
        assertThat(clean.isClean()).isTrue();
        assertThat(clean.cumulative()).containsEntry(ITEM, new BigDecimal("10.00"));
        ShipmentInvariants.assertClean("发货被拒绝", clean); // 不抛
        // 超发形态：上限那条红、精度那条空
        ShipmentInvariants.Verdict over = ShipmentInvariants.verdict(
                List.of(line(ITEM, "11.00")), List.of(), order);
        assertThat(over.isClean()).isFalse();
        assertThat(over.quantityRejections()).hasSize(1);
        assertThat(over.precisionRejections()).isEmpty();
        assertThatThrownBy(() -> ShipmentInvariants.assertClean("发货被拒绝", over))
                .isInstanceOf(BusinessException.class).hasMessageContaining("累计实发上限");
        // 越界精度形态：精度那条红、上限那条空（两条判据互不遮蔽）
        ShipmentInvariants.Verdict subCent = ShipmentInvariants.verdict(
                List.of(line(ITEM, "0.001")), List.of(), order);
        assertThat(subCent.precisionRejections()).hasSize(1);
        assertThat(subCent.quantityRejections()).isEmpty();
        assertThatThrownBy(() -> ShipmentInvariants.assertClean("实发数量不合法", subCent))
                .isInstanceOf(BusinessException.class).hasMessageContaining("列精度");
    }
}
