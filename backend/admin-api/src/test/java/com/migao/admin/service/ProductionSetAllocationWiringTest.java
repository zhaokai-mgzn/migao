// case_ids: PG-018
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper.PartTokenRow;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 实例化路径上的**套号落库 + 部位码**（切片 ⓪.5，issue #4789）。
 *
 * <p>本类钉的是「分配器被真的接进实例化路径」——{@link ProcessingOrderSetAllocatorTest} 只证分配器自身
 * 的口径，证不了它**被调用**、也证不了实例行落 {@code set_id}/{@code set_no}（V92 六列中的两列）
 * 与部位码真的写出来。没有这一层，分配器可能是个**没人调用的孤儿**（= #4725 实测的那个缺口形态：
 * 载体存在、零写方）。</p>
 *
 * <p><b>判据不许恒真</b>：删掉 {@code instantiate} 里的 {@code ensureSetsFor(...)} /
 * {@code ensurePartTokens(...)} 任一处 ⇒ 对应断言必红（见 PR body 的注入式红证读数）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("实例化 ⇒ 套号落库 + 实例行 set_id/set_no + 部位码（切片 ⓪.5）")
class ProductionSetAllocationWiringTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-4789";
    private static final String PO_ID = "po-4789";
    private static final String PO_NO = "JG-20260920-0001";

    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    @Mock
    private ProcessingOrderSetAllocator orderSetAllocator;
    @Mock
    private ProcessingOrderSetMapper orderSetMapper;
    @Mock
    private ProcessingSetPartTokenMapper setPartTokenMapper;

    private ProductionService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        service = new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper,
                orderMapper, orderItemMapper, clientRequestIdService);
        // 生产装配下这三个依赖由 Spring 字段注入（同 #4733 的 WorkerReportAuditMapper）；
        // 单测里用 ReflectionTestUtils 走同一条注入路径（不扩既有测试的构造装配）。
        ReflectionTestUtils.setField(service, "orderSetAllocator", orderSetAllocator);
        ReflectionTestUtils.setField(service, "orderSetMapper", orderSetMapper);
        ReflectionTestUtils.setField(service, "setPartTokenMapper", setPartTokenMapper);

        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("一樘「布+纱+帘头」：实例行落同一个 set_id/set_no，且一部位一码（3 个 token）")
    void instantiateStampsSetAndCreatesPartTokens() {
        ProcessingOrderSet set = ProcessingOrderSet.builder()
                .id("set-1").tenantId(TENANT).processingOrderId(PO_ID)
                .setIndex(1).setNo(PO_NO + "-001").craftLineId("cl-A").deleted(0).build();
        when(orderSetAllocator.ensureSets(any(), any(), eq(TENANT))).thenReturn(List.of(set));
        // 三条部位行同属一樘窗（craftLineId=cl-A）⇒ 同一个套
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                orderItem("i-1", "cl-A"), orderItem("i-2", "cl-A"), orderItem("i-3", "cl-A")));

        service.instantiate(ORDER_ID, body(), TENANT);

        ArgumentCaptor<ProcessingPositionOperation> ops =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(3)).insert(ops.capture());
        assertThat(ops.getAllValues()).allSatisfy(op -> {
            assertThat(op.getSetId()).as("实例行必须落套归属（V92 的 set_id）").isEqualTo("set-1");
            assertThat(op.getSetNo()).as("实例行必须落套号快照（V92 的 set_no）").isEqualTo(PO_NO + "-001");
        });

        ArgumentCaptor<PartTokenRow> tokens = ArgumentCaptor.forClass(PartTokenRow.class);
        verify(setPartTokenMapper, times(3)).insertIgnoreConflict(tokens.capture());
        assertThat(tokens.getAllValues()).allSatisfy(t -> {
            assertThat(t.setId()).isEqualTo("set-1");
            assertThat(t.token()).as("32 位 UUID 去横线（与既有 qr_token 同格式）").hasSize(32);
            assertThat(t.token()).doesNotContain("-");
            // 稳定短链（V99 / issue #4802）：短码与 token **同一次插入**（同一行的两种表示）
            assertThat(t.shortCode()).as("短码必须是 8 位 Crockford Base32").hasSize(8);
            assertThat(t.shortCode()).as("短码不得含易混字符 I/L/O/U")
                    .matches("[0-9ABCDEFGHJKMNPQRSTVWXYZ]{8}");
        });
        assertThat(tokens.getAllValues()).extracting(PartTokenRow::orderItemId)
                .containsExactlyInAnyOrder("i-1", "i-2", "i-3");
        assertThat(tokens.getAllValues()).extracting(PartTokenRow::shortCode)
                .as("同一批的 3 个部位短码必须互不相同（碰撞重试生效；全同 = 判据恒真的坏实现）")
                .doesNotHaveDuplicates();
    }

    @Test
    @DisplayName("同一部位多道工序 ⇒ 只一码（一部位一码，不是一工序一码）")
    void onePartOneCodeEvenWithManyOperations() {
        ProcessingOrderSet set = ProcessingOrderSet.builder()
                .id("set-1").tenantId(TENANT).processingOrderId(PO_ID)
                .setIndex(1).setNo(PO_NO + "-001").craftLineId("cl-A").deleted(0).build();
        when(orderSetAllocator.ensureSets(any(), any(), eq(TENANT))).thenReturn(List.of(set));
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItem("i-1", "cl-A")));

        service.instantiate(ORDER_ID, twoOpsOnePartBody(), TENANT);

        // 同一部位 2 道工序 ⇒ 2 行实例，但**只有 1 个码**
        verify(positionOperationMapper, times(2)).insert(any(ProcessingPositionOperation.class));
        verify(setPartTokenMapper, times(1)).insertIgnoreConflict(any());
    }

    @Test
    @DisplayName("归不到套的部位 ⇒ set_id/set_no 留空（不猜，与 V92「留空不猜」同口径）")
    void unmappedPartKeepsSetColumnsNull() {
        when(orderSetAllocator.ensureSets(any(), any(), eq(TENANT))).thenReturn(List.of());
        when(orderItemMapper.selectList(any())).thenReturn(List.of());

        service.instantiate(ORDER_ID, body(), TENANT);

        ArgumentCaptor<ProcessingPositionOperation> ops =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(3)).insert(ops.capture());
        assertThat(ops.getAllValues()).allSatisfy(op -> {
            assertThat(op.getSetId()).isNull();
            assertThat(op.getSetNo()).isNull();
        });
        verify(setPartTokenMapper, never()).insertIgnoreConflict(any());
    }

    @Test
    @DisplayName("分配器用**加工单快照**作为唯一输入（与 V92 回填同源，不读 order_items 现值）")
    void allocatorIsFedTheProcessingOrderSnapshot() {
        when(orderSetAllocator.ensureSets(any(), any(), eq(TENANT))).thenReturn(List.of());
        when(orderItemMapper.selectList(any())).thenReturn(List.of());

        service.instantiate(ORDER_ID, body(), TENANT);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<Map<String, Object>>> snapshot =
                ArgumentCaptor.forClass(List.class);
        verify(orderSetAllocator).ensureSets(any(ProcessingOrder.class), snapshot.capture(), eq(TENANT));
        assertThat(snapshot.getValue()).hasSize(3);
        assertThat(snapshot.getValue().get(0)).containsEntry("craftLineId", "cl-A");
    }

    // ── 夹具 ──

    private static Order order() {
        Order order = new Order();
        order.setId(ORDER_ID);
        order.setTenantId(TENANT);
        order.setOrderNo("ORD-4789");
        order.setStatus("confirmed");
        return order;
    }

    private static ProcessingOrder processingOrder() {
        List<Map<String, Object>> snapshot = List.of(
                snapshotRow("i-1", "cl-A"), snapshotRow("i-2", "cl-A"), snapshotRow("i-3", "cl-A"));
        return ProcessingOrder.builder()
                .id(PO_ID).tenantId(TENANT).orderId(ORDER_ID).processingOrderNo(PO_NO)
                .status("generated").qrToken("tok-4789").itemsSnapshot(snapshot).deleted(0).build();
    }

    private static Map<String, Object> snapshotRow(String itemId, String craftLineId) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("itemId", itemId);
        entry.put("craftLineId", craftLineId);
        entry.put("processingItems", List.of(Map.of("name", "韩褶")));
        return entry;
    }

    private static OrderItem orderItem(String id, String craftLineId) {
        OrderItem item = new OrderItem();
        item.setId(id);
        item.setTenantId(TENANT);
        item.setOrderId(ORDER_ID);
        item.setProcessingInfo(Map.of("craftLineId", craftLineId));
        item.setDeleted(0);
        return item;
    }

    /** 3 个部位（布/纱/帘头），每个 1 道工序 —— 一樘窗 3 个码的形态。 */
    private static Map<String, Object> body() {
        List<Map<String, Object>> positions = new java.util.ArrayList<>();
        positions.add(position("布帘", "i-1", "布帘"));
        positions.add(position("纱帘", "i-2", "纱帘"));
        positions.add(position("帘头", "i-3", "帘头"));
        return Map.of("positions", positions);
    }

    private static Map<String, Object> position(String name, String itemId, String kind) {
        return position(name, itemId, kind, List.of(operation("精裁-布", 1)));
    }

    private static Map<String, Object> position(String name, String itemId, String kind,
                                                List<Map<String, Object>> operations) {
        Map<String, Object> position = new LinkedHashMap<>();
        position.put("position_name", name);
        position.put("order_item_id", itemId);
        position.put("position_kind", kind);
        position.put("operations", operations);
        return position;
    }

    private static Map<String, Object> operation(String name, int seq) {
        return Map.of(
                "seq", seq, "operation", name, "group", "裁剪", "unit", "米",
                "qty", BigDecimal.ONE, "unit_price", new BigDecimal("0.40"),
                "factor", BigDecimal.ONE, "is_must_finish", false, "is_start_marker", true);
    }

    /** 一个部位（i-1）承载 2 道工序 —— 一部位一码的判据形态。 */
    private static Map<String, Object> twoOpsOnePartBody() {
        return Map.of("positions", List.of(position("布帘", "i-1", "布帘",
                List.of(operation("精裁-布", 1), operation("外帘装袋", 2)))));
    }
}
