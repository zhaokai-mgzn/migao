// case_ids: PG-018, CH-039, CH-040
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.exception.BusinessException;
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
import static org.mockito.ArgumentMatchers.isNull;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * ProductionService 语义测试（生产报工，issue #3995，M4-G-2）
 *
 * 与 M4-G-1 确定性核心（app/production/piecework.py）同口径，走 HTTP 层之外的边界语义：
 * 部分报工不算完成 / 完工 = 加工单置 completed（订单状态不动，issue #4117）/
 * 工序实例缺失时不误计件 / 计件按期过滤。
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
    @Mock
    private ClientRequestIdService clientRequestIdService;

    private ProductionService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        service = new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper,
                orderMapper, clientRequestIdService);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        // 无幂等键 ⇒ 既有用例全部走原路径（claim 返回 true = 首执），故此处只打桩「首执」分支；
        // 幂等自身的语义由 reportIsIdempotentOnSameClientRequestId / 不同键负例 两条专测覆盖。
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(true);
        // 原子有序推进默认生效（真实 DB 首执就是 1 行）；CAS 失败（并发）由专测打桩为 0。
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any()))
                .thenReturn(1);
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

    /** 工序实例夹具（§5 防呆用）：可指定部位/序号/开始标记，便于构造越站与超上限场景。 */
    private ProcessingPositionOperation positionOp(String id, String position, int seq, String name,
                                                   String qty, String doneQty, String status,
                                                   boolean startMarker, Integer deleted) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName(position).seq(seq).operationName(name)
                .groupName("后道").unit("米")
                .qty(new BigDecimal(qty)).unitPrice(new BigDecimal("0.40")).factor(BigDecimal.ONE)
                .isMustFinish(false).isStartMarker(startMarker)
                .status(status).doneQty(new BigDecimal(doneQty)).deleted(deleted)
                .build();
    }

    /** 报工（无幂等键 = 老客户端路径；幂等专测另行传键）。 */
    private Map<String, Object> report(String operationId, Map<String, Object> body) {
        return service.report(ORDER_ID, operationId, body, TENANT, null);
    }

    /** 复位单个测试对 positionOperationMapper 的打桩（不应答 delete 掉 setUp 的通用桩）。 */
    private void resetPositionOperationMapper() {
        org.mockito.Mockito.reset(positionOperationMapper);
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any()))
                .thenReturn(1);
    }

    /**
     * 内存态工序实例（读→CAS 推进→再读得到新值，模拟真实 DB 的 read-modify-write）。
     * 二次报工的 {@code done_qty} 必须从**已推进**的状态起算 —— 否则「两次都执行」的负例
     * 只是在测常量桩，测不出累加语义。
     */
    private ProcessingPositionOperation statefulOp(String id, String qty) {
        ProcessingPositionOperation state =
                positionOp(id, "布帘", 1, "精裁-布", qty, "0.00", "pending", true, 0);
        when(positionOperationMapper.selectById(id)).thenAnswer(inv -> state);
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(
                eq(id), any(), any(), any(), any(), any())).thenAnswer(inv -> {
            state.setDoneQty(inv.getArgument(4));
            state.setStatus("done");
            return 1;
        });
        return state;
    }

    @Test
    @DisplayName("部分报工：done_qty 累加但进度仍算未完成（done_qty < qty）")
    void partialReportKeepsOperationNotDone() {
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(op("op-1", "外帘装袋", "10.00", true, "pending", "0.00", "1.00", "1.00"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "外帘装袋", "10.00", true, "done", "4.00", "1.00", "1.00")));

        Map<String, Object> result = service.report(ORDER_ID, "op-1", reportBody("4", "4", "normal"), TENANT, null);

        assertThat((BigDecimal) result.get("done_qty")).isEqualByComparingTo("4.00");
        assertThat(result.get("status")).isEqualTo("done");
        // 必完工序 4 < 10 ⇒ 不完工，加工单不动（只有「必完全绿」才置 completed）
        assertThat(result.get("order_completed")).isEqualTo(false);
        verify(processingOrderMapper, never()).markCompletedIfActive(any(), any(), any());
        verify(orderMapper, never()).update(any(), any());
    }

    // ── 完工语义（issue #4117）：完工 = 加工单置 completed，**不是**订单状态推进 ──
    //
    // 病灶（P0·订单不可发货）：旧实现必完全绿时用裸 `UpdateWrapper<Order>` 直写订单
    // `producing → completed`，而 OrderService.STATUS_TRANSITIONS 里该迁移**非法**且
    // completed 是**终态**；同时 ProductionService 从不更新加工单状态，而发货守卫
    // （assertProcessingCompletedBeforeShip）读的正是加工单 `status='completed'`
    // ⇒ 含加工项订单报完工后**既发不了货也回不去**。

    @Test
    @DisplayName("必完全绿 → 加工单置 completed（订单状态不动，不写订单表）")
    void completionMarksProcessingOrderCompletedNotOrder() {
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(op("op-1", "外帘装袋", "1.00", true, "pending", "0.00", "1.00", "1.00"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "外帘装袋", "1.00", true, "done", "1.00", "1.00", "1.00")));
        when(processingOrderMapper.markCompletedIfActive(eq(PO_ID), eq(TENANT), any())).thenReturn(1);

        Map<String, Object> result = service.report(ORDER_ID, "op-1", reportBody("1", "1", "normal"), TENANT, null);

        assertThat(result.get("order_completed")).isEqualTo(true);
        // ① 加工单必须被置 completed（生产完工的唯一写路径）
        verify(processingOrderMapper).markCompletedIfActive(eq(PO_ID), eq(TENANT), any());
        // ② 订单状态**不得**被生产侧改写（producing 是 shipOrderIfApplicable 唯一的可流转前置）
        verify(orderMapper, never()).update(any(), any());
    }

    @Test
    @DisplayName("加工单非活跃（并发取消）→ 条件更新 0 行，order_completed=false，不复活已取消加工单")
    void completionIsAtomicAndSkipsNonActiveProcessingOrder() {
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(op("op-1", "外帘装袋", "1.00", true, "pending", "0.00", "1.00", "1.00"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "外帘装袋", "1.00", true, "done", "1.00", "1.00", "1.00")));
        when(processingOrderMapper.markCompletedIfActive(eq(PO_ID), eq(TENANT), any())).thenReturn(0);

        Map<String, Object> result = service.report(ORDER_ID, "op-1", reportBody("1", "1", "normal"), TENANT, null);

        assertThat(result.get("order_completed")).isEqualTo(false);
        verify(processingOrderMapper).markCompletedIfActive(eq(PO_ID), eq(TENANT), any());
        verify(orderMapper, never()).update(any(), any());
    }

    @Test
    @DisplayName("完工→发货贯通（#4117 红线）：必完全绿 → 加工单 completed → 发货守卫判据放行")
    void productionCompletionUnblocksShipGuard() {
        // 加工单状态用内存态驱动：发货守卫的判据是加工单 status='completed'（countCompletedByOrderId），
        // 只有真的把加工单置 completed，守卫才会放行 —— 这样断言会双向变化（不是恒真）。
        AtomicBoolean processingCompleted = new AtomicBoolean(false);
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(op("op-1", "外帘装袋", "1.00", true, "pending", "0.00", "1.00", "1.00"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "外帘装袋", "1.00", true, "done", "1.00", "1.00", "1.00")));
        when(processingOrderMapper.markCompletedIfActive(eq(PO_ID), eq(TENANT), any()))
                .thenAnswer(invocation -> {
                    processingCompleted.set(true);
                    return 1;
                });
        when(processingOrderMapper.countCompletedByOrderId(ORDER_ID, TENANT))
                .thenAnswer(invocation -> processingCompleted.get() ? 1L : 0L);

        // 前置：完工前守卫判据 = 0（含加工项订单会被 assertProcessingCompletedBeforeShip 拦截）
        assertThat(processingOrderMapper.countCompletedByOrderId(ORDER_ID, TENANT))
                .as("完工前：无 completed 加工单 ⇒ 发货守卫拦截")
                .isZero();

        Map<String, Object> result = service.report(ORDER_ID, "op-1", reportBody("1", "1", "normal"), TENANT, null);

        // 端到端判据（先断言，红证② 的判据就是它）：必完全绿后，守卫判据
        // （OrderService.assertProcessingCompletedBeforeShip 的 `countCompletedByOrderId(...) == 0`）
        // 不再成立 ⇒ 发货放行
        assertThat(processingOrderMapper.countCompletedByOrderId(ORDER_ID, TENANT))
                .as("完工后：加工单 status='completed' ⇒ 发货守卫放行")
                .isGreaterThan(0);
        assertThat(result.get("order_completed")).isEqualTo(true);
        // 订单留在 producing（shipOrderIfApplicable 只在 confirmed/producing 时流转）且从未被生产侧改写
        verify(orderMapper, never()).update(any(), any());
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

        assertThatThrownBy(() -> service.report(ORDER_ID, "op-1", reportBody("0", "0", "normal"), TENANT, null))
                .hasMessageContaining("qty");
        assertThatThrownBy(() -> service.report(ORDER_ID, "op-1", reportBody("1", "-1", "normal"), TENANT, null))
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

    @Test
    @DisplayName("#4222 路径参数为**加工单号**（JG-...）→ 解析到订单（工人端手输兜底路径）")
    void getOperationsResolvesByProcessingOrderNo() {
        String processingOrderNo = "JG-20260918-6914";
        when(orderMapper.selectById(processingOrderNo)).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(null);                       // ② order_no 未命中
        // 加工单表的两次解析：③ qr_token 未命中；④ processing_order_no 命中（本单新增的第四形态）
        when(processingOrderMapper.selectOne(any())).thenAnswer(inv -> {
            com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<?> wrapper = inv.getArgument(0);
            return wrapper.getSqlSegment().contains("processing_order_no") ? processingOrder() : null;
        });
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = service.getOperations(processingOrderNo, TENANT);

        assertThat(result.get("order_id")).isEqualTo(ORDER_ID);
    }

    // ══════════════════════════ §5 四项防呆（issue #4116 P0-3）══════════════════════════
    //
    // 病灶（逐项一次真实误报工的形态）：
    //   ① 重复报工：工人连点两次 / 网络重试 ⇒ 同一笔报工落两条明细、done_qty 翻倍（原代码
    //      `doneQty = doneQty.add(qualifiedQty)` 无条件累加，且前端无 in-flight 锁）；
    //   ② 越站：前道未完成也能报后续工序 ⇒ 工序顺序失控、必完判定提前全绿 ⇒ 假完工；
    //   ③ 超上限：报工数量无上界 ⇒ done_qty 可超过应做数量（进度百分比 >100、计件虚高）；
    //   ④ 非本部位：软删实例（工艺变更后重新实例化留下的旧行）仍可被报工 ⇒ 进度记到废弃实例上。
    //
    // 每条都有**独立**红证：把对应防呆拆掉后，下面那条断言必红（见 PR 证据表）。

    private static final String KEY = "req-key-1";

    @Test
    @DisplayName("§5-1 幂等：同键重复报工不重复累加 done_qty、不重复落明细，回放首次结果并标记 replayed")
    void reportIsIdempotentOnSameClientRequestId() {
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(positionOp("op-1", "布帘", 1, "精裁-布", "10.00", "0.00", "pending", true, 0));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());
        // 首次占位成功、第二次同键已被占用
        when(clientRequestIdService.claim(TENANT, KEY, ProductionService.ENDPOINT_REPORT))
                .thenReturn(true, false);

        Map<String, Object> first = service.report(ORDER_ID, "op-1", reportBody("4", "4", "normal"), TENANT, KEY);
        Map<String, Object> snapshot = new java.util.LinkedHashMap<>(first);
        when(clientRequestIdService.replay(TENANT, KEY, Map.class)).thenReturn(Optional.of(snapshot));
        Map<String, Object> second = service.report(ORDER_ID, "op-1", reportBody("4", "4", "normal"), TENANT, KEY);

        // 首次：4.00；重复：回放同一份快照 —— **不是** 8.00（无条件累加的形态）
        assertThat((BigDecimal) first.get("done_qty")).isEqualByComparingTo("4.00");
        assertThat((BigDecimal) second.get("done_qty"))
                .as("同键重复不得再累加（否则 done_qty 翻倍 = 计件虚高）")
                .isEqualByComparingTo("4.00");
        assertThat(second.get("replayed")).isEqualTo(Boolean.TRUE);
        // 效果层：报工明细只落一条（不是「调了两次但都失败」），原子推进只发生一次
        verify(workLogMapper, times(1)).insert(any(ProductionWorkLog.class));
        verify(positionOperationMapper, times(1))
                .advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any());
        verify(clientRequestIdService).complete(eq(TENANT), eq(KEY), any());
    }

    @Test
    @DisplayName("§5-1 负例（R2）：不同幂等键 ⇒ 两次都真的执行（合法追加报工不得被拦成重复）")
    void differentClientRequestIdsBothAdvance() {
        statefulOp("op-1", "10.00");
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());
        when(clientRequestIdService.claim(TENANT, "req-key-A", ProductionService.ENDPOINT_REPORT)).thenReturn(true);
        when(clientRequestIdService.claim(TENANT, "req-key-B", ProductionService.ENDPOINT_REPORT)).thenReturn(true);

        Map<String, Object> first = service.report(ORDER_ID, "op-1", reportBody("4", "4", "normal"), TENANT, "req-key-A");
        Map<String, Object> second = service.report(ORDER_ID, "op-1", reportBody("3", "3", "normal"), TENANT, "req-key-B");

        assertThat((BigDecimal) first.get("done_qty")).isEqualByComparingTo("4.00");
        assertThat((BigDecimal) second.get("done_qty")).isEqualByComparingTo("7.00");
        verify(workLogMapper, times(2)).insert(any(ProductionWorkLog.class));
        verify(clientRequestIdService, never()).replay(any(), any(), any());
    }

    @Test
    @DisplayName("§5-2 越站：同部位前道未完成 ⇒ 422 + 可行动 suggestion，不落明细、不推进")
    void reportRejectedWhenPredecessorOperationNotDone() {
        when(positionOperationMapper.selectById("op-2"))
                .thenReturn(positionOp("op-2", "布帘", 2, "布帘车被", "10.00", "0.00", "pending", false, 0));
        // 报工前快照：同部位 seq=1「精裁-布」只报了 4/10（未完成）
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                positionOp("op-1", "布帘", 1, "精裁-布", "10.00", "4.00", "done", true, 0),
                positionOp("op-2", "布帘", 2, "布帘车被", "10.00", "0.00", "pending", false, 0)));

        assertThatThrownBy(() -> report("op-2", reportBody("10", "10", "normal")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("精裁-布")
                .hasMessageContaining("尚未完成")
                .as("可行动 suggestion：先报工完成前道工序")
                .extracting(e -> ((BusinessException) e).getSuggestion())
                .asString()
                .contains("请先报工完成");

        verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
        verify(positionOperationMapper, never())
                .advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("§5-2 负例（R2）：合法顺序（前道已完成）不得被拦 —— 真报工推进到 10.00")
    void reportAllowedWhenPredecessorOperationDone() {
        when(positionOperationMapper.selectById("op-2"))
                .thenReturn(positionOp("op-2", "布帘", 2, "布帘车被", "10.00", "0.00", "pending", false, 0));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                positionOp("op-1", "布帘", 1, "精裁-布", "10.00", "10.00", "done", true, 0),
                positionOp("op-2", "布帘", 2, "布帘车被", "10.00", "0.00", "pending", false, 0)));

        Map<String, Object> result = report("op-2", reportBody("10", "10", "normal"));

        assertThat((BigDecimal) result.get("done_qty")).isEqualByComparingTo("10.00");
        assertThat(result.get("status")).isEqualTo("done");
        verify(workLogMapper).insert(any(ProductionWorkLog.class));
    }

    @Test
    @DisplayName("§5-2 返工/报废不受顺序门禁（如实记录现场不得被拦）")
    void reworkAndScrapAreNotBlockedBySequenceGate() {
        when(positionOperationMapper.selectById("op-2"))
                .thenReturn(positionOp("op-2", "布帘", 2, "布帘车被", "10.00", "0.00", "pending", false, 0));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                positionOp("op-1", "布帘", 1, "精裁-布", "10.00", "0.00", "pending", true, 0),
                positionOp("op-2", "布帘", 2, "布帘车被", "10.00", "0.00", "pending", false, 0)));

        Map<String, Object> result = service.report(ORDER_ID, "op-2",
                reportBody("2", "0", "scrap"), TENANT, null);

        assertThat(result.get("status")).isEqualTo("pending");
        verify(workLogMapper).insert(any(ProductionWorkLog.class));
    }

    @Test
    @DisplayName("§5-3 数量上限：done_qty + 本次 > qty ⇒ 422 + suggestion（不落库、不 clamp）")
    void reportRejectedWhenExceedingPlannedQty() {
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(positionOp("op-1", "布帘", 1, "外帘装袋", "10.00", "9.00", "done", false, 0));

        assertThatThrownBy(() -> report("op-1", reportBody("5", "5", "normal")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("超上限")
                .hasMessageContaining("10")
                .as("可行动 suggestion：本次最多可报剩余数量 / 先修正应做数量")
                .extracting(e -> ((BusinessException) e).getSuggestion())
                .asString()
                .contains("最多可报");

        verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
        verify(positionOperationMapper, never())
                .advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("§5-3 负例（R2）：恰好报满（9 + 1 = 10）不得被拦")
    void reportAllowedWhenExactlyReachingPlannedQty() {
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(positionOp("op-1", "布帘", 1, "外帘装袋", "10.00", "9.00", "done", false, 0));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = report("op-1", reportBody("1", "1", "normal"));

        assertThat((BigDecimal) result.get("done_qty")).isEqualByComparingTo("10.00");
        verify(workLogMapper).insert(any(ProductionWorkLog.class));
    }

    @Test
    @DisplayName("§5-4 非本部位：软删实例（含 deleted 为 NULL 的脏数据）⇒ 404，不落明细")
    void reportRejectedForDeletedOrNullFlaggedOperation() {
        for (Integer deleted : new Integer[]{1, null}) {
            org.mockito.Mockito.clearInvocations(positionOperationMapper);
            when(positionOperationMapper.selectById("op-gone"))
                    .thenReturn(positionOp("op-gone", "布帘", 1, "精裁-布", "10.00", "0.00", "pending", true, deleted));

            assertThatThrownBy(() -> report("op-gone", reportBody("1", "1", "normal")))
                    .as("deleted=%s 的实例不得被报工（fail-closed：NULL 也视为不可用）", deleted)
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("工序");
            verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
        }
    }

    @Test
    @DisplayName("§5-4 非本部位：跨租户实例 ⇒ 404（越租户报工不得发生）")
    void reportRejectedForForeignTenantOperation() {
        ProcessingPositionOperation foreign = positionOp("op-x", "布帘", 1, "精裁-布", "10.00", "0.00", "pending", true, 0);
        foreign.setTenantId(999L);
        when(positionOperationMapper.selectById("op-x")).thenReturn(foreign);

        assertThatThrownBy(() -> report("op-x", reportBody("1", "1", "normal")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("工序");
        verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
    }

    @Test
    @DisplayName("§5-1 并发（不同键）：CAS 影响 0 行 ⇒ fail-closed 409，绝不静默覆盖别人的报工")
    void concurrentAdvanceFailsClosedWhenCasMisses() {
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(positionOp("op-1", "布帘", 1, "精裁-布", "10.00", "0.00", "pending", true, 0));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any()))
                .thenReturn(0);

        assertThatThrownBy(() -> report("op-1", reportBody("1", "1", "normal")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("另一次报工");
    }

    @Test
    @DisplayName("§5-1 执行失败 ⇒ 释放幂等占位（否则该键被永久占死，工人重试永远进不来）")
    void failedReportReleasesIdempotencyPlaceholder() {
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(positionOp("op-1", "布帘", 1, "外帘装袋", "10.00", "9.00", "done", false, 0));

        assertThatThrownBy(() -> service.report(ORDER_ID, "op-1", reportBody("5", "5", "normal"), TENANT, KEY))
                .isInstanceOf(BusinessException.class);

        verify(clientRequestIdService).discard(TENANT, KEY);
        verify(clientRequestIdService, never()).complete(any(), any(), any());
    }

    @Test
    @DisplayName("§5-1 无幂等键 ⇒ 零幂等交互（向后兼容未升级的调用方）")
    void reportWithoutKeyKeepsLegacyPath() {
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(positionOp("op-1", "布帘", 1, "精裁-布", "10.00", "0.00", "pending", true, 0));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = report("op-1", reportBody("4", "4", "normal"));

        assertThat((BigDecimal) result.get("done_qty")).isEqualByComparingTo("4.00");
        verify(workLogMapper).insert(any(ProductionWorkLog.class));
        // 无键 ⇒ 绝不走「回放」分支（那会把合法的首次报工误判成重复）；
        // claim(null) / complete(null) 按既有契约是 no-op（返回 true / 不发 SQL），不构成本用例判据
        verify(clientRequestIdService, never()).replay(any(), any(), any());
    }
}
