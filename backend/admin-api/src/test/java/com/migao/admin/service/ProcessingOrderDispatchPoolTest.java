// case_ids: MC-300
package com.migao.admin.service;

import com.migao.admin.dto.ProductionPoolViews;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 加工单**派单池读面单元**的定点判据（issue #8770 派单池一档，CP-2/CP-4）。
 *
 * <h2>它钉什么（都是切片最容易切坏的形态）</h2>
 * <ol>
 *   <li><b>滞留上限归一</b>：{@code null} ⇒ 缺省 24；非正数 ⇒ **显式拒绝**（不静默回落 ——
 *       静默回落会让「阈值配错」变成「看板看起来正常」）；</li>
 *   <li><b>等待时长口径</b>：{@code from == null} ⇒ 0；时钟倒挂（{@code to < from}）⇒ 0
 *       （负的等待时长会让「超上限」恒为假 = 静默压单）；1 位小数 HALF_UP；</li>
 *   <li><b>临期度</b>：{@code required == null} ⇒ {@code null}（**不编 0** —— 「未指定」与
 *       「今天到期」是两件事）；过去 ⇒ 负数；将来 ⇒ 正数；</li>
 *   <li><b>展示名</b>：{@code 商品名 × 颜色/门幅}（走 {@code MaterialLabels} 的唯一实现，
 *       **不**把机器键摆上屏）；</li>
 *   <li><b>池的三分区</b>：加急 ⇒ 插队区、外发 ⇒ 外发区、其余 ⇒ 物料组；且行序 = 等待时长降序；</li>
 *   <li><b>成批闸</b>：加急 / 外发单混进 {@code pooled=true} 批次 ⇒ **整批显式拒绝**，
 *       文案带订单号且给可行动处置。</li>
 * </ol>
 *
 * <h2>边界（照实登记）</h2>
 * 本类的 {@link ProcessingOrderDispatchPool.Owner} 是**测试替身**：门面侧的
 * {@code buildSnapshot} / 时钟 / 算料服务不在本类射程内（它们仍住门面，由
 * {@code ProcessingOrderPoolCharacterizationTest} 在**真实实现**上逐字节冻结）。
 * 本类只钉「单元自身不变量」，不替门面那一条判据背书。
 */
@DisplayName("派单池读面单元：滞留上限 / 等待时长 / 临期度 / 展示名 / 三分区 / 成批闸（issue #8770）")
class ProcessingOrderDispatchPoolTest {

    private static final Long TENANT = 1L;
    private static final LocalDate TODAY = LocalDate.of(2026, 11, 6);
    private static final OffsetDateTime BASE = OffsetDateTime.parse("2026-11-06T00:00:00+08:00");

    private OrderMapper orderMapper;
    private ProcessingOrderMapper processingOrderMapper;
    private StockBatchConsumptionService stock;

    private List<Order> poolable;
    private List<String> activeOrderIds;
    private final Map<String, List<OrderItem>> itemsByOrder = new LinkedHashMap<>();
    private final Map<String, Order> ordersById = new LinkedHashMap<>();

    @BeforeEach
    void setUp() {
        orderMapper = mock(OrderMapper.class);
        processingOrderMapper = mock(ProcessingOrderMapper.class);
        stock = mock(StockBatchConsumptionService.class);
        poolable = List.of();
        activeOrderIds = List.of();
        itemsByOrder.clear();
        ordersById.clear();
        when(orderMapper.selectList(any())).thenAnswer(inv -> poolable);
        when(processingOrderMapper.selectActiveOrderIds(eq(TENANT), anyCollection())).thenAnswer(inv -> activeOrderIds);
        when(stock.maxRemainingByMaterial(eq(TENANT), any())).thenReturn(Map.of());
    }

    private ProcessingOrderDispatchPool unit() {
        return new ProcessingOrderDispatchPool(orderMapper, processingOrderMapper,
                new ProcessingOrderDispatchPool.Owner() {
                    @Override
                    public LocalDate today() {
                        return TODAY;
                    }

                    @Override
                    public List<OrderItem> loadOrderItems(String orderId, Long tenantId) {
                        return itemsByOrder.getOrDefault(orderId, List.of());
                    }

                    @Override
                    public List<Map<String, Object>> buildSnapshot(List<OrderItem> items, Long tenantId) {
                        List<Map<String, Object>> rows = new ArrayList<>();
                        for (OrderItem item : items) {
                            if (!(item.getProcessingInfo() instanceof Map<?, ?> info)) {
                                continue;
                            }
                            Map<String, Object> row = new LinkedHashMap<>();
                            row.put("itemId", item.getId());
                            row.put("productName", item.getProductName());
                            row.put("quantity", item.getQuantity());
                            row.put("sku", info.get("sku"));
                            row.put("processingItems", info.get("processingItems"));
                            rows.add(row);
                        }
                        return rows;
                    }

                    @Override
                    public StockBatchConsumptionService batchStock() {
                        return stock;
                    }

                    @Override
                    public Order resolveOrder(String rawId, Long tenantId) {
                        return ordersById.get(rawId);
                    }
                });
    }

    // ── 判据 1：滞留上限归一 ───────────────────────────────────────────────

    @Test
    @DisplayName("滞留上限：null ⇒ 缺省 24；显式值原样回口径；非正数 ⇒ 显式拒绝（不静默回落）")
    void maxWaitHoursDefaultsAndRejectsNonPositive() {
        assertThat(unit().pool(TENANT, null).maxWaitHours())
                .as("不传 ⇒ 缺省 24（唯一缺省值载体是门面的 DEFAULT_POOL_MAX_WAIT_HOURS）")
                .isEqualByComparingTo("24");
        assertThat(unit().pool(TENANT, new BigDecimal("6")).maxWaitHours())
                .as("显式值**回口径**：读的人不必猜本次生效的阈值")
                .isEqualByComparingTo("6");
        assertThatThrownBy(() -> unit().pool(TENANT, BigDecimal.ZERO))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("maxWaitHours 必须为正数（实际 0）");
        assertThatThrownBy(() -> unit().pool(TENANT, new BigDecimal("-2")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("maxWaitHours 必须为正数（实际 -2）");
    }

    // ── 判据 2：等待时长口径 ───────────────────────────────────────────────

    @Test
    @DisplayName("等待时长：from 缺值 ⇒ 0；时钟倒挂 ⇒ 0（不得为负 = 不得让「超上限」恒假）；1 位小数 HALF_UP")
    void hoursBetweenClampsAndRounds() {
        assertThat(ProcessingOrderDispatchPool.hoursBetween(null, BASE))
                .as("进池时刻缺值 ⇒ 0，不得 NPE").isEqualByComparingTo("0");
        assertThat(ProcessingOrderDispatchPool.hoursBetween(BASE, BASE.minusHours(5)))
                .as("时间倒挂（时钟回拨 / 脏数据）⇒ 记 0，不记负数").isEqualByComparingTo("0");
        assertThat(ProcessingOrderDispatchPool.hoursBetween(BASE, BASE.plusMinutes(90)))
                .as("90 分钟 ⇒ 1.5（1 位小数）").isEqualByComparingTo("1.5");
        assertThat(ProcessingOrderDispatchPool.hoursBetween(BASE, BASE.plusMinutes(61)))
                .as("61 分钟 ⇒ 1.0（HALF_UP 到 1 位）").isEqualByComparingTo("1.0");
    }

    // ── 判据 3：临期度 ─────────────────────────────────────────────────────

    @Test
    @DisplayName("临期度：未指定 ⇒ null（不编 0）；过去 ⇒ 负数；将来 ⇒ 正数")
    void deliveryDaysLeftKeepsNullAndSign() {
        assertThat(ProcessingOrderDispatchPool.deliveryDaysLeft(null, TODAY)).isNull();
        assertThat(ProcessingOrderDispatchPool.deliveryDaysLeft(TODAY.minusDays(2), TODAY))
                .as("已逾期 ⇒ 负数（前端据此标红）").isEqualTo(-2);
        assertThat(ProcessingOrderDispatchPool.deliveryDaysLeft(TODAY.plusDays(3), TODAY))
                .as("未到期 ⇒ 正数").isEqualTo(3);
        assertThat(ProcessingOrderDispatchPool.deliveryDaysLeft(TODAY, TODAY))
                .as("今天到期 ⇒ 0（与「未指定」必须可分）").isZero();
    }

    // ── 判据 4：展示名 ─────────────────────────────────────────────────────

    @Test
    @DisplayName("展示名：商品名 × SKU（走 MaterialLabels 唯一实现），机器键的 | 不上屏")
    void materialLabelGoesThroughTheSingleImplementation() {
        ProductionPoolViews.PoolLine line = new ProductionPoolViews.PoolLine(
                "o-1", "ORD-1", "i-1", "prod-uuid", "布艺遮光帘A", "SKU-A",
                new BigDecimal("3"), BASE, BigDecimal.ZERO, false, false,
                LocalDate.of(2026, 11, 9), 3);
        assertThat(ProcessingOrderDispatchPool.materialLabel(line))
                .isEqualTo("布艺遮光帘A × SKU-A")
                .doesNotContain("|")
                .doesNotContain("prod-uuid");
    }

    // ── 判据 5：三分区 + 行序 ──────────────────────────────────────────────

    @Test
    @DisplayName("池的三分区：加急进插队区 / 外发进外发区（都不进物料组）；组内行序 = 等待时长降序")
    void poolPartitionsUrgentAndOutsourcedAndSortsByWait() {
        poolable = List.of(
                order("o-normal-old", "ORD-0001", BASE.minusHours(30), false, false),
                order("o-normal-new", "ORD-0002", BASE.minusHours(2), false, false),
                order("o-urgent", "ORD-0003", BASE.minusHours(10), true, false),
                order("o-outsourced", "ORD-0004", BASE.minusHours(12), false, true));
        itemsByOrder.put("o-normal-old", items("o-normal-old", "i-1", "prod-1", "SKU-A", "3"));
        itemsByOrder.put("o-normal-new", items("o-normal-new", "i-2", "prod-1", "SKU-A", "2"));
        itemsByOrder.put("o-urgent", items("o-urgent", "i-3", "prod-1", "SKU-A", "3"));
        itemsByOrder.put("o-outsourced", items("o-outsourced", "i-4", "prod-1", "SKU-A", "3"));

        ProductionPoolViews.Pool pool = unit().pool(TENANT, new BigDecimal("100000"));

        assertThat(pool.orderCount()).as("池内订单数只含非加急 / 非外发").isEqualTo(2);
        assertThat(pool.lineCount()).isEqualTo(2);
        assertThat(pool.urgentCount()).as("加急单去重计数 = 1").isEqualTo(1);
        assertThat(pool.outsourcedCount()).as("外发单去重计数 = 1").isEqualTo(1);
        assertThat(pool.urgentLines()).extracting(ProductionPoolViews.PoolLine::orderId)
                .containsExactly("o-urgent");
        assertThat(pool.outsourcedLines()).extracting(ProductionPoolViews.PoolLine::orderId)
                .containsExactly("o-outsourced");
        assertThat(pool.groups()).hasSize(1);
        assertThat(pool.groups().get(0).lines()).extracting(ProductionPoolViews.PoolLine::orderId)
                .as("组内按等待时长降序（先出现的先派）")
                .containsExactly("o-normal-old", "o-normal-new");
        assertThat(pool.groups().get(0).materialLabel()).isEqualTo("布艺遮光帘A × SKU-A");
    }

    // ── 判据 6：成批闸 ─────────────────────────────────────────────────────

    @Test
    @DisplayName("成批闸：加急 / 外发单混进成批 ⇒ 整批拒绝（带单号 + 可行动处置）")
    void pooledBatchGuardsRejectWithActionableMessages() {
        ordersById.put("o-urgent", order("o-urgent", "ORD-9001", BASE, true, false));
        ordersById.put("o-outsourced", order("o-outsourced", "ORD-9002", BASE, false, true));

        assertThatThrownBy(() -> unit().assertNoUrgentInPooledBatch(List.of("o-urgent"), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("加急单不参与合并派单，请单独派：ORD-9001");
        assertThatThrownBy(() -> unit().assertNoOutsourcedInPooledBatch(List.of("o-outsourced"), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("外发单不参与合并派单，请单独派：ORD-9002");
        // 查不到的单**不在这里报错**（ORDER_NOT_FOUND 归逐单路径）—— 两条闸都必须放行
        unit().assertNoUrgentInPooledBatch(List.of("o-missing"), TENANT);
        unit().assertNoOutsourcedInPooledBatch(List.of("o-missing"), TENANT);
        assertThat(ordersById).hasSize(2);
    }

    // ── 夹具 ───────────────────────────────────────────────────────────────

    private static Order order(String id, String orderNo, OffsetDateTime createdAt, boolean urgent,
                               boolean outsourced) {
        return Order.builder().id(id).tenantId(TENANT).orderNo(orderNo).status("confirmed")
                .createdAt(createdAt).isUrgent(urgent).isOutsourced(outsourced).build();
    }

    /** 一行明细：{@code processing_info} 带 sku + 一条加工项（该单元只读 itemId / 名称 / 数量 / sku）。 */
    private static List<OrderItem> items(String orderId, String itemId, String productId, String skuCode,
                                         String quantity) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("sku", skuCode);
        List<Map<String, Object>> procs = new ArrayList<>();
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("id", "p-" + itemId);
        p.put("name", "打孔");
        procs.add(p);
        info.put("processingItems", procs);
        return List.of(OrderItem.builder().id(itemId).tenantId(TENANT).orderId(orderId)
                .productId(productId).productName("布艺遮光帘A").quantity(new BigDecimal(quantity))
                .processingInfo(info).build());
    }
}
