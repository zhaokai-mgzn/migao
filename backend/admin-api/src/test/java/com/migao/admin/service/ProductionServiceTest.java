// case_ids: PG-018, CH-039, CH-040
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
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

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * ProductionService 语义测试（生产报工，issue #3995，M4-G-2）
 *
 * 与 M4-G-1 确定性核心（app/production/piecework.py）同口径，走 HTTP 层之外的边界语义：
 * 部分报工不算完成 / 订单非 producing 时不动状态 / 工序实例缺失时不误计件 / 计件按期过滤。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductionService 报工/计件语义")
class ProductionServiceTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-1";
    private static final String PO_ID = "po-1";

    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private OrderMapper orderMapper;

    private ProductionService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        service = new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper, orderMapper);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private Order order(String status) {
        Order o = new Order();
        o.setId(ORDER_ID);
        o.setTenantId(TENANT);
        o.setOrderNo("ORD-20260917-001");
        o.setStatus(status);
        o.setDeleted(0);
        return o;
    }

    private ProcessingOrder processingOrder() {
        ProcessingOrder po = new ProcessingOrder();
        po.setId(PO_ID);
        po.setTenantId(TENANT);
        po.setOrderId(ORDER_ID);
        po.setStatus("in_processing");
        po.setQrToken("tok123");
        po.setDeleted(0);
        return po;
    }

    private ProcessingPositionOperation op(String id, String name, String qty, boolean mustFinish,
                                          String status, String doneQty, String unitPrice, String factor) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("布帘").seq(1).operationName(name).groupName("后道").unit("套")
                .qty(new BigDecimal(qty)).unitPrice(new BigDecimal(unitPrice)).factor(new BigDecimal(factor))
                .isMustFinish(mustFinish).isStartMarker(false)
                .status(status).doneQty(new BigDecimal(doneQty)).deleted(0)
                .build();
    }

    private Map<String, Object> reportBody(String qty, String qualifiedQty, String workType) {
        return Map.of("worker_name", "蒋雪云", "qty", new BigDecimal(qty),
                "qualified_qty", new BigDecimal(qualifiedQty), "work_type", workType);
    }

    @Test
    @DisplayName("部分报工：done_qty 累加但进度仍算未完成（done_qty < qty）")
    void partialReportKeepsOperationNotDone() {
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(op("op-1", "外帘装袋", "10.00", true, "pending", "0.00", "1.00", "1.00"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "外帘装袋", "10.00", true, "done", "4.00", "1.00", "1.00")));

        Map<String, Object> result = service.report(ORDER_ID, "op-1", reportBody("4", "4", "normal"), TENANT);

        assertThat((BigDecimal) result.get("done_qty")).isEqualByComparingTo("4.00");
        assertThat(result.get("status")).isEqualTo("done");
        // 必完工序 4 < 10 ⇒ 不完工，订单状态不动（生产中的订单只能由「必完全绿」推进）
        assertThat(result.get("order_completed")).isEqualTo(false);
        verify(orderMapper, never()).update(isNull(), any());
    }

    @Test
    @DisplayName("必完全绿但订单已不在 producing（并发/已发货）→ 条件更新 0 行，order_completed=false")
    void completionIsAtomicAndOnlyFromProducing() {
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(op("op-1", "外帘装袋", "1.00", true, "pending", "0.00", "1.00", "1.00"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "外帘装袋", "1.00", true, "done", "1.00", "1.00", "1.00")));
        when(orderMapper.update(isNull(), any())).thenReturn(0);

        Map<String, Object> result = service.report(ORDER_ID, "op-1", reportBody("1", "1", "normal"), TENANT);

        assertThat(result.get("order_completed")).isEqualTo(false);
        ArgumentCaptor<Wrapper<Order>> captor = ArgumentCaptor.forClass(Wrapper.class);
        verify(orderMapper).update(isNull(), captor.capture());
        assertThat(captor.getValue().getSqlSegment())
                .as("订单状态推进必须带 producing 前置条件（原子，不覆盖已发货/已完成）")
                .contains("status");
    }

    // ── issue #4116：实例化幂等（重复调用不得重插行 / 不得清零已有报工进度）──
    //
    // 病灶：instantiate 原语义「每次调用先软删旧实例再重插」⇒ 重复调用会把已报工的
    // done_qty 清零（新实例从 0 起算），工序进度凭空回退。修法：配置一致 ⇒ 空操作。

    /** 与 existingInstances() 完全一致的实例化请求（同配置）。 */
    private Map<String, Object> instantiateBody(String qtyOfFirstOp) {
        List<Map<String, Object>> ops = List.of(
                Map.of("seq", 1, "operation", "精裁-布", "group", "裁剪", "unit", "米",
                        "qty", new BigDecimal(qtyOfFirstOp), "unit_price", new BigDecimal("0.40"),
                        "factor", BigDecimal.ONE, "is_must_finish", false, "is_start_marker", true),
                Map.of("seq", 2, "operation", "外帘装袋", "group", "后道", "unit", "套",
                        "qty", BigDecimal.ONE, "unit_price", BigDecimal.ONE,
                        "factor", BigDecimal.ONE, "is_must_finish", true, "is_start_marker", false));
        return Map.of("positions", List.of(Map.of("position_name", "布帘", "operations", ops)));
    }

    private ProcessingPositionOperation instance(String id, int seq, String operation, String group, String unit,
                                                 String qty, String unitPrice, String status, String doneQty) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("布帘").seq(seq).operationName(operation).groupName(group).unit(unit)
                .qty(new BigDecimal(qty))
                .unitPrice(new BigDecimal(unitPrice))
                .factor(BigDecimal.ONE)
                .isMustFinish("外帘装袋".equals(operation))
                .isStartMarker("精裁-布".equals(operation))
                .status(status).doneQty(new BigDecimal(doneQty)).deleted(0)
                .build();
    }

    /** 已落库的活跃实例：精裁-布（应做 12.30 米，未报工）+ 外帘装袋（必完，已报满 1.00）。 */
    private List<ProcessingPositionOperation> existingInstances() {
        return List.of(
                instance("op-1", 1, "精裁-布", "裁剪", "米", "12.30", "0.40", "pending", "0.00"),
                instance("op-2", 2, "外帘装袋", "后道", "套", "1.00", "1.00", "done", "1.00"));
    }

    @Test
    @DisplayName("#4116 幂等：同配置连续两次实例化 → 不重插、不软删、报工进度不清零、token 复用")
    void instantiateTwiceIsIdempotent() {
        List<ProcessingPositionOperation> existing = existingInstances();
        when(positionOperationMapper.selectList(any())).thenReturn(existing);

        Map<String, Object> first = service.instantiate(ORDER_ID, instantiateBody("12.30"), TENANT);
        Map<String, Object> second = service.instantiate(ORDER_ID, instantiateBody("12.30"), TENANT);

        // 已是同一配置 ⇒ 不软删旧实例（那是清零报工进度的机制）、不重插行、不动 token
        verify(positionOperationMapper, never()).update(isNull(), any());
        verify(positionOperationMapper, never()).insert(any(ProcessingPositionOperation.class));
        verify(positionOperationMapper, never()).updateById(any(ProcessingPositionOperation.class));
        verify(processingOrderMapper, never()).updateById(any(ProcessingOrder.class));
        assertThat(second.get("operation_count")).isEqualTo(2);
        assertThat(first.get("qr_token")).isEqualTo("tok123");
        assertThat(second.get("qr_token")).isEqualTo("tok123");
        // 已报工实例仍是原对象（done_qty=1.00 未被重置为 0）——软删+重插是唯一会清零的路径，
        // 上面两条 never() 即该断言的机制层证据
        assertThat(existing.get(1).getDoneQty()).isEqualByComparingTo("1.00");
        assertThat(existing.get(1).getStatus()).isEqualTo("done");
    }

    @Test
    @DisplayName("#4116 工艺变更（配置不同）→ 旧实例软删 + 重插（保留既有重新实例化语义）")
    void instantiateReinstantiatesWhenConfigurationChanged() {
        when(positionOperationMapper.selectList(any())).thenReturn(existingInstances());

        Map<String, Object> result = service.instantiate(ORDER_ID, instantiateBody("15.00"), TENANT);

        ArgumentCaptor<Wrapper<ProcessingPositionOperation>> wrapperCaptor = ArgumentCaptor.forClass(Wrapper.class);
        verify(positionOperationMapper).update(isNull(), wrapperCaptor.capture());
        assertThat(wrapperCaptor.getValue().getSqlSegment())
                .as("配置变更才软删旧实例（保留审计）")
                .contains("deleted");
        verify(positionOperationMapper, times(2)).insert(any(ProcessingPositionOperation.class));
        assertThat(result.get("operation_count")).isEqualTo(2);
        assertThat(result.get("qr_token")).isEqualTo("tok123");
    }

    @Test
    @DisplayName("报工数量非法（qty<=0 / qualified_qty<0）→ 422 校验错误，不落库")
    void invalidQuantitiesRejected() {
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(op("op-1", "精裁-布", "10.00", false, "pending", "0.00", "0.40", "1.00"));

        assertThatThrownBy(() -> service.report(ORDER_ID, "op-1", reportBody("0", "0", "normal"), TENANT))
                .hasMessageContaining("qty");
        assertThatThrownBy(() -> service.report(ORDER_ID, "op-1", reportBody("1", "-1", "normal"), TENANT))
                .hasMessageContaining("qualified_qty");
        verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
    }

    @Test
    @DisplayName("计件跳过工序实例已不存在的报工（软删实例不误计件）")
    void pieceworkSkipsMissingOperationInstance() {
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                ProductionWorkLog.builder().tenantId(TENANT).processingOrderId(PO_ID).operationId("op-gone")
                        .operationName("精裁-布").workerName("张三").qty(new BigDecimal("10"))
                        .qualifiedQty(new BigDecimal("10")).workType("normal").deleted(0).build()));
        when(positionOperationMapper.selectById("op-gone")).thenReturn(null);

        Map<String, Object> result = service.piecework(ORDER_ID, TENANT);

        assertThat((BigDecimal) result.get("total")).isEqualByComparingTo("0.00");
        assertThat((Map<?, ?>) result.get("per_worker")).isEmpty();
    }

    @Test
    @DisplayName("工人计件按期过滤：work_date 落在 YYYY-MM 首末之间")
    void workerPieceworkFiltersByPeriod() {
        when(workLogMapper.selectList(any())).thenReturn(List.of());

        service.workerPiecework("张三", "2026-09", TENANT);

        ArgumentCaptor<com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<ProductionWorkLog>> captor =
                ArgumentCaptor.forClass(com.baomidou.mybatisplus.core.conditions.query.QueryWrapper.class);
        verify(workLogMapper).selectList(captor.capture());
        assertThat(captor.getValue().getSqlSegment()).contains("work_date");
        assertThat(captor.getValue().getParamNameValuePairs().values())
                .as("期间边界取当月首末（含端点）")
                .contains(LocalDate.of(2026, 9, 1), LocalDate.of(2026, 9, 30));
    }

    @Test
    @DisplayName("工人计件：缺 worker_name / 非法 period → 422")
    void workerPieceworkValidatesParams() {
        assertThatThrownBy(() -> service.workerPiecework("  ", "2026-09", TENANT))
                .hasMessageContaining("worker_name");
        assertThatThrownBy(() -> service.workerPiecework("张三", "2026-13", TENANT))
                .hasMessageContaining("period");
    }

    @Test
    @DisplayName("订单进度：全部实例完成时 current_operation 为空串、pending 为空数组")
    void progressReportsEmptyCurrentOperationWhenAllDone() {
        when(orderMapper.selectOne(any())).thenReturn(order("producing"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "精裁-布", "10.00", false, "done", "10.00", "0.40", "1.00"),
                op("op-2", "外帘装袋", "1.00", true, "done", "1.00", "1.00", "1.00")));

        Map<String, Object> result = service.progress("ORD-20260917-001", TENANT);

        assertThat(result.get("total_operations")).isEqualTo(2);
        assertThat(result.get("done_operations")).isEqualTo(2);
        assertThat(result.get("progress_percent")).isEqualTo(100);
        assertThat(result.get("current_operation")).isEqualTo("");
        assertThat((List<?>) result.get("pending_operations")).isEmpty();
    }

    // ── 生产进度查询的订单解析（issue #4007：progress 与 report 同口径，不得只认 order_no）──
    //
    // 病灶（run 35233821582 的 CH-039/CH-040）：米宝/小布拿到的是**内部 order_id** 或
    // 用户点名的不存在形态时，`progress` 只按 `order_no` 查 ⇒ 明明有单却 404 ⇒
    // 工具层 `no_success(production_progress_query)`。修复 = 复用 `resolveOrder`
    // （order_id → order_no → qr_token，与 #4006 的报工链路同一口径）。

    @Test
    @DisplayName("订单进度：按内部 order_id 命中（不再只认 order_no）")
    void progressResolvesByInternalOrderId() {
        // setUp 已把 selectById(ORDER_ID) 指向该订单；positionOperationMapper.selectList → null ⇒ 空工序
        Map<String, Object> result = service.progress(ORDER_ID, TENANT);

        assertThat(result.get("order_no")).isEqualTo("ORD-20260917-001");
        assertThat(result.get("status")).isEqualTo("producing");
        assertThat(result.get("progress_percent")).isEqualTo(0);
    }

    @Test
    @DisplayName("订单进度：按订单号 order_no 命中（手输单号口径保持）")
    void progressResolvesByOrderNo() {
        when(orderMapper.selectById("ORD-20260917-001")).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(order("producing"));

        Map<String, Object> result = service.progress("ORD-20260917-001", TENANT);

        assertThat(result.get("order_no")).isEqualTo("ORD-20260917-001");
    }

    @Test
    @DisplayName("订单进度：三形态都不命中 → notFound（不静默返回空进度）")
    void progressUnknownKeyNotFound() {
        when(orderMapper.selectById("nope")).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(null);
        when(processingOrderMapper.selectOne(any())).thenReturn(null);

        assertThatThrownBy(() -> service.progress("nope", TENANT))
                .hasMessageContaining("订单");
    }

    // ── 订单解析三形态（issue #4005：打印二维码内容 qr_token 必须可用于报工/查询）──

    @Test
    @DisplayName("路径参数为加工单 qr_token → 解析到订单（扫码报工链路）")
    void getOperationsResolvesByQrToken() {
        when(orderMapper.selectById("tok123")).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(null);                        // order_no 未命中
        when(processingOrderMapper.selectOne(any())).thenReturn(processingOrder()); // qr_token 命中
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = service.getOperations("tok123", TENANT);

        assertThat(result.get("order_id")).isEqualTo(ORDER_ID);
    }

    @Test
    @DisplayName("路径参数为订单号 order_no → 解析到订单（手输纸质单号）")
    void getOperationsResolvesByOrderNo() {
        when(orderMapper.selectById("ORD-20260917-001")).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(order("producing"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = service.getOperations("ORD-20260917-001", TENANT);

        assertThat(result.get("order_id")).isEqualTo(ORDER_ID);
    }

    @Test
    @DisplayName("三形态都不命中 → notFound（不静默返回空）")
    void getOperationsUnknownKeyNotFound() {
        when(orderMapper.selectById("nope")).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(null);
        when(processingOrderMapper.selectOne(any())).thenReturn(null);

        assertThatThrownBy(() -> service.getOperations("nope", TENANT))
                .hasMessageContaining("订单");
    }
}
