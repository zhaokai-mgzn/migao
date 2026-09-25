// case_ids: PR-079, PR-080, PR-081
package com.migao.admin.service;

import com.migao.admin.dto.ProductionPoolViews;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

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
import static org.mockito.Mockito.when;

/**
 * 🔴 <b>智能派单 + 加急插队（issue #5177）的单元判据</b> —— 本单的三个核心判断都在这里可复算。
 *
 * <h2>判据映射（每条都带**能单独让它红**的形态）</h2>
 * <ol>
 *   <li><b>缺省不变</b>（判据 1/2）：没有加急单、没有到货日 ⇒ 池的成员、计数、行序与今天**逐值相同**
 *       （{@code urgentCount=0} / {@code urgentLines} 空），且 {@code poolingEnabled=false} 不动。
 *       红证 = 把缺省改成「总是加急」或「总是入池」⇒ 本类的缺省用例当场红。</li>
 *   <li><b>加急插队</b>（判据 3）：加急单**不进池**（不在任何 {@code groups[].lines} 里），
 *       只出现在 {@code urgentLines}（插队区）；把它混进 {@code pooled=true} 的成批批次
 *       ⇒ **整批显式拒绝**（{@code /dispatch} 与 {@code /preview} 同一条闸）。
 *       红证 = 删掉 {@code assertNoUrgentInPooledBatch} 的调用 ⇒ 拒绝断言红（且回落成逐单错误文案）。</li>
 *   <li><b>排序是真实消费者</b>（判据 5）：到货日升序、{@code null} 排最后、同日后按等待时长降序。
 *       红证 = 把排序键退化成**单号序** ⇒ 本类的排序用例红（夹具刻意让「单号序 ≠ 期望序」）。</li>
 *   <li><b>透传</b>（范围 5）：订单级加急/到货日进加工单快照，{@code isUrgent} **恒落键**
 *       （{@code false} 是真值）、{@code requiredDeliveryDate} **缺值不落键**。</li>
 * </ol>
 *
 * <p><b>为什么不测「加急单走单订单路径能生成加工单」</b>：那是**既有**路径（本单没改它），
 * 本类只钉「加急**不改变**单订单路径」这一条边界 —— 见
 * {@link #singleOrderPathKeepsItsExistingErrorTextForUrgentOrder()}：同一个加急单走
 * {@code pooled=false} 时抛的仍是**既有文案**，不是本单新加的拒绝文案。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("#5177 智能派单：加急不进池 / 排序是真实消费者 / 缺省不变 / 订单级字段透传快照")
class PoolBoardUrgencyTest {

    private static final Long TENANT = 1L;

    @InjectMocks
    private ProcessingOrderService processingOrderService;

    @Mock
    private ProcessingOrderMapper processingOrderMapper;

    @Mock
    private OrderMapper orderMapper;

    @Mock
    private OrderItemMapper orderItemMapper;

    /** {@code buildSnapshot} 会用加工项目录补齐 {@code options} ⇒ 这个 mock 必须在场。 */
    @Mock
    private com.migao.admin.mapper.ProcessingItemMapper processingItemMapper;

    @BeforeEach
    void setUp() {
        com.migao.admin.config.TenantContext.setTenantId(TENANT);
    }

    // ─────────────────────────────────────────── 判据 1/2：缺省不变

    @Test
    @DisplayName("判据1/2 缺省不变：无加急单、无到货日 ⇒ 池的成员/计数/行序与今天逐值相同（插队区为空）")
    void defaultsAreUnchangedWhenNothingIsUrgentAndNoDeliveryDate() {
        OffsetDateTime now = OffsetDateTime.now();
        // 顺序忠于真实查询（pool() 走 orderByAsc(createdAt)）
        when(orderMapper.selectList(any())).thenReturn(List.of(
                orderOf("o-old", "ORD-0001", now.minusHours(30), false, null),
                orderOf("o-new", "ORD-0002", now.minusHours(2), false, null)));
        when(processingOrderMapper.selectActiveOrderIds(eq(TENANT), anyCollection())).thenReturn(List.of());
        when(orderItemMapper.selectList(any())).thenReturn(itemsOf("o-old", "i-old"), itemsOf("o-new", "i-new"));

        ProductionPoolViews.Pool pool = processingOrderService.pool(TENANT, null);

        assertThat(pool.poolingEnabled()).as("池化缺省仍为关（本单不改 #5169 的缺省）").isFalse();
        assertThat(pool.orderCount()).as("两张单都在池（缺省没有任何单被排除）").isEqualTo(2);
        assertThat(pool.lineCount()).isEqualTo(2);
        assertThat(pool.urgentCount()).as("🔴 缺省 ⇒ 插队区计数为 0").isZero();
        assertThat(pool.urgentLines()).as("🔴 缺省 ⇒ 插队区为空").isEmpty();
        assertThat(pool.groups()).hasSize(1);
        assertThat(pool.groups().get(0).lines()).extracting(ProductionPoolViews.PoolLine::orderId)
                .as("行序 = 等待时长降序（= createdAt 升序，记录期既有序；新的第一把键在缺省下恒相等）")
                .containsExactly("o-old", "o-new");
        assertThat(pool.groups().get(0).lines()).allSatisfy(line -> {
            assertThat(line.isUrgent()).as("缺省不得把任何单读成加急").isFalse();
            assertThat(line.requiredDeliveryDate()).as("未指定 ⇒ null（不猜、不拿今天顶替）").isNull();
            assertThat(line.deliveryDaysLeft()).as("未指定 ⇒ 临期度也是 null，不得编 0").isNull();
        });
    }

    // ─────────────────────────────────────────── 判据 3：加急不进池 + 批内拒绝

    @Test
    @DisplayName("判据3 加急不进池：加急单只出现在插队区，池的候选集里一行都没有（一张单都不丢）")
    void urgentOrderStaysOutOfPoolAndAppearsInQueueJumpSection() {
        OffsetDateTime now = OffsetDateTime.now();
        when(orderMapper.selectList(any())).thenReturn(List.of(
                orderOf("o-urgent", "ORD-9001", now.minusHours(20), true, LocalDate.now().plusDays(1)),
                orderOf("o-normal-1", "ORD-9002", now.minusHours(10), false, null),
                orderOf("o-normal-2", "ORD-9003", now.minusHours(3), false, null)));
        when(processingOrderMapper.selectActiveOrderIds(eq(TENANT), anyCollection())).thenReturn(List.of());
        when(orderItemMapper.selectList(any())).thenReturn(
                itemsOf("o-urgent", "i-urgent"), itemsOf("o-normal-1", "i-n1"), itemsOf("o-normal-2", "i-n2"));

        ProductionPoolViews.Pool pool = processingOrderService.pool(TENANT, null);

        assertThat(pool.urgentCount()).as("恰好一张加急单").isEqualTo(1);
        assertThat(pool.urgentLines()).extracting(ProductionPoolViews.PoolLine::orderId)
                .as("🔴 加急单在**插队区**（看板上一个动作即可派它）").containsExactly("o-urgent");
        assertThat(pool.urgentLines().get(0).isUrgent()).isTrue();
        assertThat(pool.urgentLines().get(0).requiredDeliveryDate())
                .as("加急行同样带出到货日（插队区也要能看出临期）").isEqualTo(LocalDate.now().plusDays(1));
        assertThat(pool.urgentLines().get(0).deliveryDaysLeft()).isEqualTo(1);

        assertThat(pool.orderCount()).as("池内 = 两张**非**加急单").isEqualTo(2);
        assertThat(pool.lineCount()).isEqualTo(2);
        assertThat(pool.groups()).allSatisfy(group -> assertThat(group.lines())
                .as("🔴 池的候选集里**不得**出现加急行（加急单不进池）")
                .allSatisfy(line -> assertThat(line.isUrgent()).isFalse()));

        List<String> seen = new ArrayList<>(pool.urgentLines().stream()
                .map(ProductionPoolViews.PoolLine::orderId).toList());
        pool.groups().forEach(g -> g.lines().forEach(l -> seen.add(l.orderId())));
        assertThat(seen).as("池内 + 插队区 = 全部订单（加急只是换了去处，不是被丢掉）")
                .containsExactlyInAnyOrder("o-urgent", "o-normal-1", "o-normal-2");
    }

    @Test
    @DisplayName("🔴 判据3 加急混进成批批次 ⇒ /dispatch 与 /preview 都**整批显式拒绝**（fail-closed，不静默少派）")
    void pooledBatchContainingUrgentOrderIsRejectedFailClosed() {
        Order urgent = orderOf("o-urgent", "ORD-9001", OffsetDateTime.now(), true, null);
        when(orderMapper.selectById("o-urgent")).thenReturn(urgent);

        assertThatThrownBy(() -> processingOrderService.generate(List.of("o-urgent"), List.of(),
                TENANT, null, null, Boolean.TRUE))
                .as("成批派单：加急单一进批次就整批拒绝")
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("加急单不参与合并派单")
                .hasMessageContaining("ORD-9001")
                .hasMessageNotContaining("不允许生成加工单");

        assertThatThrownBy(() -> processingOrderService.preview(TENANT, List.of("o-urgent"),
                List.of(), null))
                .as("成批**预览**同一条闸：预览一个派不出去的批次就是说谎（判据 4）")
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("加急单不参与合并派单")
                .hasMessageContaining("ORD-9001");
    }

    @Test
    @DisplayName("判据2/3 边界：同一个加急单走 pooled=false ⇒ **既有**单订单路径文案一字未变（加急不侵入单派）")
    void singleOrderPathKeepsItsExistingErrorTextForUrgentOrder() {
        // 用「状态不是 confirmed」这张单，让既有单订单路径在自己的闸上失败 ⇒
        // 文案必须是既有那句，而不是本单新加的加急拒绝（判据 2 的「单订单路径错误文案」那一格）。
        Order pending = Order.builder().id("o-urgent").tenantId(TENANT).orderNo("ORD-9001")
                .status("pending").isUrgent(true).build();
        when(orderMapper.selectById("o-urgent")).thenReturn(pending);

        List<ProcessingOrderService.GenerateResult> results = processingOrderService.generate(
                List.of("o-urgent"), List.of(), TENANT, null, null, Boolean.FALSE);

        assertThat(results).hasSize(1);
        assertThat(results.get(0).isSuccess()).as("状态不对 ⇒ 这张单失败（既有行为）").isFalse();
        assertThat(results.get(0).getMessage())
                .as("🔴 加急**不改变**单订单路径的失败文案（加急只影响入池/派单时机）")
                .contains("不允许生成加工单")
                .doesNotContain("加急");
    }

    // ─────────────────────────────────────────── 判据 5：排序是真实消费者

    @Test
    @DisplayName("🔴 判据5 排序：到货日升序（null 排最后）→ 等待时长降序；**不是**单号序")
    void orderingPrefersNearestDeliveryDateThenLongestWaitAndPutsNullsLast() {
        LocalDate today = LocalDate.now();
        OffsetDateTime now = OffsetDateTime.now();
        // 夹具刻意让「单号序 ≠ 期望序」「输入序 ≠ 期望序」——否则这条断言没有判别力
        // 单号序 = o-none-new(0001) < o-none-old(0002) < o-soon(0003) < o-late(0004)
        // 期望序 = o-soon(+2) → o-late(+30) → o-none-old(等 50h) → o-none-new(等 1h)
        when(orderMapper.selectList(any())).thenReturn(List.of(
                orderOf("o-late", "ORD-0004", now.minusHours(5), false, today.plusDays(30)),
                orderOf("o-none-new", "ORD-0001", now.minusHours(1), false, null),
                orderOf("o-soon", "ORD-0003", now.minusHours(4), false, today.plusDays(2)),
                orderOf("o-none-old", "ORD-0002", now.minusHours(50), false, null)));
        when(processingOrderMapper.selectActiveOrderIds(eq(TENANT), anyCollection())).thenReturn(List.of());
        when(orderItemMapper.selectList(any())).thenReturn(
                itemsOf("o-late", "i-late"), itemsOf("o-none-new", "i-nn"),
                itemsOf("o-soon", "i-soon"), itemsOf("o-none-old", "i-no"));

        ProductionPoolViews.Pool pool = processingOrderService.pool(TENANT, null);
        List<ProductionPoolViews.PoolLine> lines = pool.groups().get(0).lines();

        assertThat(lines).extracting(ProductionPoolViews.PoolLine::orderId)
                .as("🔴 临期优先；到货日为空的两张排在**最后**，且它们之间按等待时长降序")
                .containsExactly("o-soon", "o-late", "o-none-old", "o-none-new");
        assertThat(lines).extracting(ProductionPoolViews.PoolLine::orderNo)
                .as("判别力：期望序**不等于**单号序（排序键退化成单号序 ⇒ 本断言红）")
                .containsExactly("ORD-0003", "ORD-0004", "ORD-0002", "ORD-0001");
        assertThat(lines).extracting(ProductionPoolViews.PoolLine::deliveryDaysLeft)
                .as("临期度 = 到货日 − 今天（未指定 ⇒ null，不得编 0）")
                .containsExactly(2, 30, null, null);
        assertThat(lines.get(0).overdue()).as("上限 24 小时：等 4 小时的不算超").isFalse();
        assertThat(lines.get(2).waitHours()).as("到货日为空的组内，等得久的在前").isEqualByComparingTo("50.0");
    }

    @Test
    @DisplayName("判据5 加急插队区也走同一把排序键（临期优先），且看板顺序 = 插队区在前")
    void urgentSectionUsesTheSameOrderingKey() {
        LocalDate today = LocalDate.now();
        OffsetDateTime now = OffsetDateTime.now();
        when(orderMapper.selectList(any())).thenReturn(List.of(
                orderOf("u-late", "ORD-0101", now.minusHours(9), true, today.plusDays(20)),
                orderOf("u-soon", "ORD-0102", now.minusHours(1), true, today.plusDays(1)),
                orderOf("u-overdue", "ORD-0103", now.minusHours(2), true, today.minusDays(3))));
        when(processingOrderMapper.selectActiveOrderIds(eq(TENANT), anyCollection())).thenReturn(List.of());
        when(orderItemMapper.selectList(any())).thenReturn(
                itemsOf("u-late", "i-ul"), itemsOf("u-soon", "i-us"), itemsOf("u-overdue", "i-uo"));

        ProductionPoolViews.Pool pool = processingOrderService.pool(TENANT, null);

        assertThat(pool.groups()).as("三张都是加急 ⇒ 池是空的（候选集为 0）").isEmpty();
        assertThat(pool.orderCount()).isZero();
        assertThat(pool.urgentCount()).isEqualTo(3);
        assertThat(pool.urgentLines()).extracting(ProductionPoolViews.PoolLine::orderId)
                .as("插队区同样按到货日升序 ⇒ **已逾期**的排最前（最该立刻派）")
                .containsExactly("u-overdue", "u-soon", "u-late");
        assertThat(pool.urgentLines().get(0).deliveryDaysLeft())
                .as("已逾期 ⇒ 负数（看板据此显示「已逾期 N 天」）").isEqualTo(-3);
    }

    // ─────────────────────────────────────────── 范围 5：订单级字段透传进快照

    @Test
    @DisplayName("范围5 透传：isUrgent **恒落键**（false 是真值）、requiredDeliveryDate **缺值不落键**")
    void orderLevelFieldsAreStampedIntoSnapshotRows() {
        List<Map<String, Object>> urgentSnapshot = new ArrayList<>();
        urgentSnapshot.add(new LinkedHashMap<>(Map.of("itemId", "i-1")));
        urgentSnapshot.add(new LinkedHashMap<>(Map.of("itemId", "i-2")));
        ProcessingOrderService.stampOrderUrgency(urgentSnapshot,
                Order.builder().id("o").tenantId(TENANT).isUrgent(true)
                        .requiredDeliveryDate(LocalDate.of(2026, 10, 1)).build());

        assertThat(urgentSnapshot).allSatisfy(row -> {
            assertThat(row).as("加急标记逐行固化（订单级事实只能逐行落 —— 快照是行数组）")
                    .containsEntry("isUrgent", true);
            assertThat(row).as("到货日以 YYYY-MM-DD 字符串落快照（JSONB 里就是它）")
                    .containsEntry("requiredDeliveryDate", "2026-10-01");
        });

        List<Map<String, Object>> defaultSnapshot = new ArrayList<>();
        defaultSnapshot.add(new LinkedHashMap<>(Map.of("itemId", "i-1")));
        ProcessingOrderService.stampOrderUrgency(defaultSnapshot,
                Order.builder().id("o").tenantId(TENANT).isUrgent(false).build());

        assertThat(defaultSnapshot.get(0))
                .as("🔴 显式「否」是**真值**：false 必须落键（不得当成「未填」丢弃）")
                .containsEntry("isUrgent", false);
        assertThat(defaultSnapshot.get(0))
                .as("🔴 未指定 ⇒ **不落键**（写空串/占位会把「未指定」读成一个日期）")
                .doesNotContainKey("requiredDeliveryDate");

        // 空快照 / 空订单 ⇒ no-op（不得插出一个只有订单级键的幽灵行）
        List<Map<String, Object>> empty = new ArrayList<>();
        ProcessingOrderService.stampOrderUrgency(empty, null);
        assertThat(empty).isEmpty();
    }

    // ─────────────────────────────────────────── 存量行：processing_info 为 NULL（issue #5550）

    @Test
    @DisplayName("存量行 processing_info 为 NULL ⇒ 池读面不得 500（该行不成候选，正常行照旧入池）")
    void poolReadFaceSurvivesLegacyItemWithoutProcessingInfo() {
        OffsetDateTime now = OffsetDateTime.now();
        when(orderMapper.selectList(any())).thenReturn(List.of(
                orderOf("o-legacy", "ORD-1001", now.minusHours(30), false, null),
                orderOf("o-normal", "ORD-1002", now.minusHours(2), false, null)));
        when(processingOrderMapper.selectActiveOrderIds(eq(TENANT), anyCollection())).thenReturn(List.of());
        when(orderItemMapper.selectList(any())).thenReturn(
                itemsWithoutProcessingInfo("o-legacy", "i-legacy"), itemsOf("o-normal", "i-normal"));

        // 🔴 红证（修复前实测）：`normalizeProcessingInfo` 返回 null ⇒ `str(pi.get("saleForm"))` NPE
        //    ⇒ 整个读面 500（真库实证：待派池 29 行有 15 行 processing_info 为 NULL）。
        ProductionPoolViews.Pool pool = processingOrderService.pool(TENANT, null);

        assertThat(pool.groups()).as("只有带 processing_info 的正常行成组").hasSize(1);
        assertThat(pool.groups().get(0).lines()).extracting(ProductionPoolViews.PoolLine::orderId)
                .as("缺 processing_info 的行既无加工项也无 saleForm ⇒ 不成派单候选（既有语义），"
                        + "正常行一行不丢")
                .containsExactly("o-normal");
        assertThat(pool.lineCount()).as("明细行数 = 1（NULL 行不产出行）").isEqualTo(1);
        assertThat(pool.orderCount())
                .as("NULL 行整单没有快照 ⇒ 按**既有**语义不进池（`if (snapshot.isEmpty()) continue;`，"
                        + "本单不改这条口径）；🔴 关键是不能 500，且不得把正常单一起丢掉")
                .isEqualTo(1);
        assertThat(pool.urgentCount()).as("NULL 行不得被读成加急").isZero();
    }

    // ─────────────────────────────────────────── 夹具

    private Order orderOf(String id, String orderNo, OffsetDateTime createdAt, boolean urgent,
                          LocalDate requiredDeliveryDate) {
        return Order.builder().id(id).tenantId(TENANT).orderNo(orderNo).status("confirmed")
                .createdAt(createdAt).isUrgent(urgent).requiredDeliveryDate(requiredDeliveryDate).build();
    }

    /** 一行明细：带 {@code productId} + {@code processing_info.sku}（「物料」= 商品 × 颜色 × 门幅）。 */
    private List<OrderItem> itemsOf(String orderId, String itemId) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", "米白");
        info.put("sellingMethod", "散剪");
        info.put("doorWidth", "2.8米");
        info.put("sku", "SKU-A");
        info.put("cuttingMode", "定高买宽");
        List<Map<String, Object>> procs = new ArrayList<>();
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("id", "p1");
        p.put("name", "打孔");
        p.put("quantity", 2);
        p.put("unit", "米");
        procs.add(p);
        info.put("processingItems", procs);
        return List.of(OrderItem.builder().id(itemId).tenantId(TENANT).orderId(orderId)
                .productId("prod-1").productName("布艺遮光帘A").quantity(new BigDecimal("3"))
                .width(new BigDecimal("1.5")).height(new BigDecimal("1.1"))
                .processingInfo(info).build());
    }

    /**
     * 存量行：`order_items.processing_info` 为 **NULL**（真库实证 issue #5550：待派明细 15/29 行如此）
     * —— 归一化入口对它返回 null，任何直接解引用都会 NPE（智能派单恒 500 的根因）。
     */
    private List<OrderItem> itemsWithoutProcessingInfo(String orderId, String itemId) {
        return List.of(OrderItem.builder().id(itemId).tenantId(TENANT).orderId(orderId)
                .productId("prod-1").productName("存量布艺帘").quantity(new BigDecimal("3"))
                .width(new BigDecimal("1.5")).height(new BigDecimal("1.1"))
                .build());
    }
}
