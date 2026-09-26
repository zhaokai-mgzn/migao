// case_ids: PG-018, PG-057, PG-060, CH-039, CH-040
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
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
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

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
    private com.migao.admin.mapper.OrderItemMapper orderItemMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    /** 批次消耗台账（V116 / #5145 阶段 1）：工人端「去哪个批次裁多少米」的只读真值源 */
    @Mock
    private StockBatchConsumptionService stockBatchConsumptionService;

    private ProductionService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        service = new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper,
                orderMapper, orderItemMapper, clientRequestIdService);
        // 批次台账（V116 / #5145）是**字段注入**（不在构造签名里，见其字段注释）⇒ 显式装配
        org.springframework.test.util.ReflectionTestUtils.setField(
                service, "stockBatchConsumptionService", stockBatchConsumptionService);
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
        return op(id, name, qty, mustFinish, status, doneQty, unitPrice, factor, false);
    }

    /** 同 {@link #op} 的九参形态：`isStartMarker`（首工序标记，issue #4695 / D13 的触发器）显式传入。 */
    private ProcessingPositionOperation op(String id, String name, String qty, boolean mustFinish,
                                          String status, String doneQty, String unitPrice, String factor,
                                          boolean startMarker) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("布帘").seq(1).operationName(name).groupName("后道").unit("套")
                .qty(new BigDecimal(qty)).unitPrice(new BigDecimal(unitPrice)).factor(new BigDecimal(factor))
                .isMustFinish(mustFinish).isStartMarker(startMarker)
                .status(status).doneQty(new BigDecimal(doneQty)).deleted(0)
                .build();
    }

    // ============================================================ D13 夹具（issue #4695）

    /**
     * 加工单那一行的**内存态替身**（只模拟本单用到的写面语义）。
     *
     * <p>为什么需要它：`verify(mapper)` 只证明「调了哪个方法」，证明不了「状态真的变了没有、
     * 开工时刻有没有被重复报工改写」—— 而 #4695 的两条判据恰恰是后者。</p>
     */
    private static final class PoRow {
        final AtomicReference<String> status = new AtomicReference<>("issued");
        /** 每次**真的**落笔的 `in_processing_at`（`COALESCE` 语义 ⇒ 只应有第一次那笔）。 */
        final List<OffsetDateTime> inProcessingStamps = new ArrayList<>();
    }

    /**
     * D13 夹具：`issued` 的加工单 + 写面替身。
     *
     * <p>替身逐条模拟 `ProcessingOrderMapper.markInProcessingIfFrom` 的 SQL 语义：
     * ① 谓词 `status = #{fromStatus}`（不成立 ⇒ 0 行 = 不转态，并发/重复报工在这里被挡掉）；
     * ② `COALESCE(in_processing_at, …)`（只有第一次落笔）；
     * ③ 读面 `selectActiveByOrderId` 跟着这行状态走（不是固定夹具值）。</p>
     */
    private PoRow stubIssuedProcessingOrder() {
        PoRow row = new PoRow();
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenAnswer(invocation -> {
            ProcessingOrder po = processingOrder();
            po.setStatus(row.status.get());
            return po;
        });
        when(processingOrderMapper.markInProcessingIfFrom(eq(PO_ID), eq(TENANT), any(), any()))
                .thenAnswer(invocation -> {
                    if (!Objects.equals(invocation.getArgument(2), row.status.get())) {
                        return 0;
                    }
                    row.status.set("in_processing");
                    row.inProcessingStamps.add(invocation.getArgument(3));
                    return 1;
                });
        return row;
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

    /**
     * 🔴 <b>#4961 判别性红证</b>：完工口径换成「**全部**活跃工序实例都完成（{@code done_qty ≥ qty}）」。
     *
     * <p>夹具 = 两道工序：`外帘装袋`（**必完**，本次报满）+ `精裁-布`（**非**必完，未报工）。
     * 旧口径（{@code is_must_finish} 集合全绿）只看必完那道 ⇒ 判**完工**（{@code order_completed=true}）；
     * 新口径（用户裁定 2026-09-21「完工 = 全部工序全绿」）⇒ 必须 {@code false}。</p>
     *
     * <p>红证（改前实测）：同一夹具下 {@code order_completed} 为 {@code true} ⇒ 本用例逐值红
     * （错误信息 `expected: false but was: true`）。绿 ⇒ 判定真的换体了。</p>
     */
    @Test
    @DisplayName("#4961 非必完工序未完成 ⇒ 不完工（改前：必完全绿即置 completed ⇒ order_completed=true）")
    void unfinishedNonMustFinishOperationBlocksCompletion() {
        when(positionOperationMapper.selectById("op-2"))
                .thenReturn(op("op-2", "外帘装袋", "1.00", true, "pending", "0.00", "1.00", "1.00"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-2", "外帘装袋", "1.00", true, "done", "1.00", "1.00", "1.00"),
                op("op-1", "精裁-布", "12.30", false, "pending", "0.00", "0.40", "1.00")));
        when(processingOrderMapper.markCompletedIfActive(eq(PO_ID), eq(TENANT), any())).thenReturn(1);

        Map<String, Object> result = service.report(ORDER_ID, "op-2", reportBody("1", "1", "normal"), TENANT, null);

        assertThat(result.get("order_completed"))
                .as("非必完的「精裁-布」还没做完 ⇒ 整单不算完工（旧口径在这里判 true）")
                .isEqualTo(false);
        verify(processingOrderMapper, never()).markCompletedIfActive(any(), any(), any());
        // 冻结键仍在（只是值变了）；#4117 红线不变：订单表一字不写
        assertThat(result).containsKey("order_completed");
        verify(orderMapper, never()).update(any(), any());
    }

    /** #4961 反向判据：**全部**实例完成 ⇒ 才置加工单 completed（新口径的下界）。 */
    @Test
    @DisplayName("#4961 全部活跃实例完成 ⇒ 加工单置 completed（新口径的绿侧）")
    void allInstancesDoneStillCompletesTheProcessingOrder() {
        when(positionOperationMapper.selectById("op-2"))
                .thenReturn(op("op-2", "外帘装袋", "1.00", true, "pending", "0.00", "1.00", "1.00"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-2", "外帘装袋", "1.00", true, "done", "1.00", "1.00", "1.00"),
                op("op-1", "精裁-布", "12.30", false, "done", "12.30", "0.40", "1.00")));
        when(processingOrderMapper.markCompletedIfActive(eq(PO_ID), eq(TENANT), any())).thenReturn(1);

        Map<String, Object> result = service.report(ORDER_ID, "op-2", reportBody("1", "1", "normal"), TENANT, null);

        assertThat(result.get("order_completed")).isEqualTo(true);
        verify(processingOrderMapper).markCompletedIfActive(eq(PO_ID), eq(TENANT), any());
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

    // ── 计件金额在报工那一刻固化（issue #4351，P0：重新实例化后历史报工的钱凭空消失）──
    //
    // 病根：`aggregate` 用 `operationLookup.apply(log.getOperationId())` **回查实例**算金额；
    // 而 `ProcessingOrderService.instantiate` 在重新实例化（`POST /production/orders/{orderId}/instantiate`，
    // #4202 给存量单补工序的入口）时会**软删旧实例并重插** ⇒ 旧报工指向已软删实例 ⇒ 被 `continue`
    // 跳过 ⇒ **工人已做的活的钱从合计里消失，且不报错**（报表照常返回一个偏小的合计）。
    // 真值源 §4 要的是「逐笔可追溯」⇒ 金额必须在报工那一刻固化，聚合只读报工自己的快照。
    // 本组四条：① 红证（金额不变）② 快照真的落库 ③ 快照优先于实例现值 ④ 兜底负例（真·脏数据仍跳过）。

    @Test
    @DisplayName("#4351 红证：重新实例化软删旧实例后，同一笔报工的计件金额不变（钱不消失）")
    void pieceworkAmountSurvivesReInstantiation() {
        ProcessingPositionOperation live =
                op("op-1", "精裁-布", "10.00", false, "pending", "0.00", "0.12", "1.00");
        when(positionOperationMapper.selectById("op-1")).thenReturn(live);
        // 报工前 / 报工中的实例快照（listOperations 走同一个 selectList 桩）
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(live));
        ArgumentCaptor<ProductionWorkLog> inserted = ArgumentCaptor.forClass(ProductionWorkLog.class);

        service.report(ORDER_ID, "op-1", reportBody("10", "10", "normal"), TENANT, null);
        verify(workLogMapper).insert(inserted.capture());
        ProductionWorkLog log = inserted.getValue();

        // 报工时的计件合计（10 合格 × ¥0.12 × 1.00 = ¥1.20）
        when(workLogMapper.selectList(any())).thenReturn(List.of(log));
        BigDecimal before = (BigDecimal) service.piecework(ORDER_ID, TENANT).get("total");
        assertThat(before).isEqualByComparingTo("1.20");

        // 触发重新实例化：旧实例软删并重插新实例（新 id）⇒ 活跃实例集里再也没有 op-1
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-2", "精裁-布", "10.00", false, "pending", "0.00", "0.12", "1.00")));

        Map<String, Object> after = service.piecework(ORDER_ID, TENANT);

        assertThat((BigDecimal) after.get("total"))
                .as("报工那一刻的金额已固化 ⇒ 旧实例软删不得让这笔钱从合计里消失（issue #4351）")
                .isEqualByComparingTo("1.20");
        @SuppressWarnings("unchecked")
        Map<String, BigDecimal> perWorker = (Map<String, BigDecimal>) after.get("per_worker");
        assertThat(perWorker.get("蒋雪云")).isEqualByComparingTo("1.20");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> perOperation = (List<Map<String, Object>>) after.get("per_operation");
        assertThat(perOperation).singleElement()
                .satisfies(row -> assertThat(row.get("operation")).isEqualTo("精裁-布"));
    }

    @Test
    @DisplayName("#4589/#4604 报工快照只固化单价（factor 仍不写）；读时按快照的系数算 —— 新报工恒 1")
    void reportSnapshotsUnitPriceWithoutFactor() {
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(op("op-1", "韩褶-布", "10.00", false, "pending", "0.00", "0.40", "1.70"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "韩褶-布", "10.00", false, "pending", "0.00", "0.40", "1.70")));
        ArgumentCaptor<ProductionWorkLog> inserted = ArgumentCaptor.forClass(ProductionWorkLog.class);

        service.report(ORDER_ID, "op-1", reportBody("2", "2", "normal"), TENANT, null);

        verify(workLogMapper).insert(inserted.capture());
        assertThat(inserted.getValue().getUnitPrice())
                .as("单价快照（报工时从工序实例写入）—— 聚合不得再回查实例")
                .isEqualByComparingTo("0.40");
        // 判别力：实例上的 factor = 1.70，而报工快照**必须不再固化它**（改前这里等于 1.70）
        assertThat(inserted.getValue().getFactor())
                .as("系数快照已退场（#4589）：报工不再写 factor")
                .isNull();
        // #4604 读面同口径：新报工快照 factor = NULL ⇒ 系数取 1 ⇒ 2 × 0.40 = 0.80
        // （反向护栏：不得因为实例上仍是 1.70 就把系数加回新单）
        when(workLogMapper.selectList(any())).thenReturn(List.of(inserted.getValue()));
        assertThat((BigDecimal) service.piecework(ORDER_ID, TENANT).get("total"))
                .as("新报工 factor 快照为 NULL ⇒ 读时取 1，不乘（issue #4604）")
                .isEqualByComparingTo("0.80");
    }

    @Test
    @DisplayName("#4351 聚合读报工自己的快照：实例现值被改价也不得改写历史报工（真值源 §4 逐笔可追溯）")
    void pieceworkReadsOwnSnapshotNotLiveInstance() {
        ProductionWorkLog log = ProductionWorkLog.builder()
                .tenantId(TENANT).processingOrderId(PO_ID).operationId("op-1").operationName("精裁-布")
                .workerName("蒋雪云").qty(new BigDecimal("10")).qualifiedQty(new BigDecimal("10"))
                .workType("normal").unitPrice(new BigDecimal("0.12")).factor(new BigDecimal("1.00"))
                .deleted(0).build();
        when(workLogMapper.selectList(any())).thenReturn(List.of(log));
        // 实例还在，但**改价了**（0.12 → 9.99）：历史报工必须按当时价
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "精裁-布", "10.00", false, "done", "10.00", "9.99", "1.00")));

        Map<String, Object> result = service.piecework(ORDER_ID, TENANT);

        assertThat((BigDecimal) result.get("total"))
                .as("金额 = 报工快照（0.12），不是实例现值（9.99）—— 调价只影响新报工")
                .isEqualByComparingTo("1.20");
    }

    @Test
    @DisplayName("#4351 兜底不得删：实例 id 确实不存在（脏数据）的报工跳过而不抛错")
    void pieceworkSkipsMissingOperationInstance() {
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                ProductionWorkLog.builder().tenantId(TENANT).processingOrderId(PO_ID).operationId("op-gone")
                        .operationName("精裁-布").workerName("张三").qty(new BigDecimal("10"))
                        .qualifiedQty(new BigDecimal("10")).workType("normal").deleted(0).build()));
        when(positionOperationMapper.selectById("op-gone")).thenReturn(null);

        Map<String, Object> result = service.piecework(ORDER_ID, TENANT);

        assertThat((BigDecimal) result.get("total"))
                .as("既无快照、实例又真的不存在 ⇒ 该笔不可计价，跳过而不是抛错（整张报表不得中断）")
                .isEqualByComparingTo("0.00");
        assertThat((Map<?, ?>) result.get("per_worker")).isEmpty();
    }

    @Test
    @DisplayName("#4351 存量报工（迁移前、无快照）仍按实例回查计价 —— 快照引入不得让历史工资归零")
    void legacyLogWithoutSnapshotFallsBackToInstanceLookup() {
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "精裁-布", "10.00", false, "done", "10.00", "0.12", "1.00")));
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                ProductionWorkLog.builder().tenantId(TENANT).processingOrderId(PO_ID).operationId("op-1")
                        .operationName("精裁-布").workerName("蒋雪云").qty(new BigDecimal("10"))
                        .qualifiedQty(new BigDecimal("10")).workType("normal").deleted(0).build()));

        Map<String, Object> result = service.piecework(ORDER_ID, TENANT);

        assertThat((BigDecimal) result.get("total")).isEqualByComparingTo("1.20");
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
        // issue #4643：无当前工序 ⇒ 追加的两键都是 null（键在、值空 —— 不凭空造名）
        assertThat(result).containsKey("logical_name");
        assertThat(result.get("logical_name")).isNull();
        assertThat(result).containsKey("position");
        assertThat(result.get("position")).isNull();
    }

    @Test
    @DisplayName("订单进度：追加 logical_name/position（读时派生；current_operation 快照名一字不动，issue #4643）")
    void progressCarriesLogicalNameAndPositionForWebDisplay() {
        when(orderMapper.selectOne(any())).thenReturn(order("producing"));
        ProcessingPositionOperation variant =
                op("op-1", "精裁-布", "10.00", false, "pending", "0.00", "0.40", "1.00");
        variant.setPositionKind("布帘");
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(variant));

        Map<String, Object> result = service.progress("ORD-20260917-001", TENANT);

        assertThat(result.get("current_operation")).isEqualTo("精裁-布");
        assertThat(result.get("logical_name")).isEqualTo("精裁");
        assertThat(result.get("position")).isEqualTo("布帘");
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

    // ── 过程明细（issue #4201）：工序实例 × 报工明细 × 数量聚合 ──────────────────────
    //
    // 缺口：agent 读不到「加工单 × 工序实例 × 报工明细」（谁在做、合格/返工/报废各多少、
    // 下料=裁剪组做到哪一步）。本组锁该只读投影的三条不变式：
    //   ① 数量按**报工三态**归集（合格 = normal 的合格数；返工/报废取报工数量）；
    //   ② **不新增第二份计价口径** —— 金额走既有 `aggregate`（与 /piecework 同一份）；
    //   ③ 租户隔离与四形态订单解析沿用 `resolveOrder`（不得只认 order_no）。

    private ProcessingPositionOperation cuttingOp(String id, String name, String qty, String doneQty,
                                                 String unitPrice) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("布艺遮光帘A 米白").positionKind("布帘").seq(1)
                .operationName(name).groupName("裁剪").unit("米")
                .qty(new BigDecimal(qty)).unitPrice(new BigDecimal(unitPrice))
                .factor(BigDecimal.ONE).isMustFinish(false).isStartMarker(false)
                .status("done").doneQty(new BigDecimal(doneQty)).deleted(0)
                .build();
    }

    private ProductionWorkLog workLog(String opId, String name, String worker, String qty,
                                     String qualified, String type, String date) {
        return ProductionWorkLog.builder()
                .tenantId(TENANT).processingOrderId(PO_ID).operationId(opId).operationName(name)
                .workerName(worker).qty(new BigDecimal(qty)).qualifiedQty(new BigDecimal(qualified))
                .workType(type).workDate(LocalDate.parse(date)).deleted(0).build();
    }

    @Test
    @DisplayName("过程明细：下料（裁剪）做到哪 → 应做/合格/返工/报废 + 报工人 + 分组（#4201）")
    void worklogAggregatesByWorkTypeAndWorkers() {
        when(orderMapper.selectOne(any())).thenReturn(order("producing"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                cuttingOp("op-1", "精裁-布", "12.00", "10.00", "0.40"),
                op("op-2", "外帘装袋", "1.00", true, "pending", "0.00", "1.00", "1.00")));
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                workLog("op-1", "精裁-布", "王师傅", "10.00", "10.00", "normal", "2026-09-19"),
                workLog("op-1", "精裁-布", "王师傅", "2.00", "0.00", "rework", "2026-09-20"),
                workLog("op-2", "外帘装袋", "李四", "1.00", "0.00", "scrap", "2026-09-20")));

        Map<String, Object> result = service.worklog("ORD-20260917-001", TENANT);

        assertThat(result.get("order_no")).isEqualTo("ORD-20260917-001");
        assertThat(result.get("processing_order_no")).isNull();   // 夹具加工单无单号 ⇒ 如实 null
        assertThat(result.get("processing_status")).isEqualTo("in_processing");

        List<Map<String, Object>> operations = operationsOf(result);
        assertThat(operations).hasSize(2);
        Map<String, Object> cutting = operations.get(0);
        assertThat(cutting.get("operation_name")).isEqualTo("精裁-布");
        assertThat(cutting.get("logical_name")).isEqualTo("精裁");     // 读时派生的逻辑名
        assertThat(cutting.get("position")).isEqualTo("布帘");         // 帘种（position_kind）
        assertThat(cutting.get("group_name")).isEqualTo("裁剪");       // 下料 = 裁剪组
        assertThat(cutting.get("status")).isEqualTo("done");
        assertThat((BigDecimal) cutting.get("required_qty")).isEqualByComparingTo("12.00");
        assertThat((BigDecimal) cutting.get("qualified_qty")).isEqualByComparingTo("10.00");
        assertThat((BigDecimal) cutting.get("rework_qty")).isEqualByComparingTo("2.00");
        assertThat((BigDecimal) cutting.get("scrap_qty")).isEqualByComparingTo("0.00");
        assertThat(cutting.get("last_work_date")).isEqualTo("2026-09-20");
        // 「谁报的」只算**正常报工**的报工人（返工/报废不计入 —— 与既有 workersByOperation 同口径）
        assertThat(cutting.get("workers")).isEqualTo(List.of("王师傅"));

        Map<String, Object> packing = operations.get(1);
        assertThat(packing.get("operation_name")).isEqualTo("外帘装袋");
        assertThat((BigDecimal) packing.get("scrap_qty")).isEqualByComparingTo("1.00");
        // 🔴 #4961：worklog 读面的 `is_must_finish` 键**保留**（冻结键集，工人端/agent 的既有消费者）
        // 但值**恒 false** —— 改前这一行断言 `true`。真实完工口径 = 全部活跃实例完成（allInstancesDone）。
        assertThat(packing.get("is_must_finish")).isEqualTo(false);
        assertThat(packing.get("workers")).isEqualTo(List.of());          // 只有报废 ⇒ 无正常报工人
        assertThat(packing.get("last_work_date")).isEqualTo("2026-09-20");

        @SuppressWarnings("unchecked")
        Map<String, Object> totals = (Map<String, Object>) result.get("totals");
        assertThat((BigDecimal) totals.get("qualified_qty")).isEqualByComparingTo("10.00");
        assertThat((BigDecimal) totals.get("rework_qty")).isEqualByComparingTo("2.00");
        assertThat((BigDecimal) totals.get("scrap_qty")).isEqualByComparingTo("1.00");

        // 报工明细**倒序**（最近在前）：scrap(op-2) → rework → normal
        List<Map<String, Object>> logs = logsOf(result);
        assertThat(logs).hasSize(3);
        assertThat(logs.get(0).get("work_type")).isEqualTo("scrap");
        assertThat(logs.get(2).get("work_type")).isEqualTo("normal");
        assertThat(logs.get(2).get("worker_name")).isEqualTo("王师傅");
        assertThat(logs.get(2).get("work_date")).isEqualTo("2026-09-19");
    }

    @Test
    @DisplayName("过程明细：计件金额与 /piecework 走**同一份**聚合（禁第二份计价口径，#4201）")
    void worklogPieceworkAmountSharesSingleAggregate() {
        when(orderMapper.selectOne(any())).thenReturn(order("producing"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                cuttingOp("op-1", "精裁-布", "12.00", "10.00", "0.40"),
                op("op-2", "韩褶-布", "5.00", false, "done", "5.00", "0.40", "1.70")));
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                workLog("op-1", "精裁-布", "王师傅", "10.00", "10.00", "normal", "2026-09-19"),
                workLog("op-2", "韩褶-布", "王师傅", "5.00", "5.00", "normal", "2026-09-19"),
                workLog("op-1", "精裁-布", "王师傅", "2.00", "2.00", "rework", "2026-09-20")));

        Map<String, Object> detail = service.worklog("ORD-20260917-001", TENANT);
        @SuppressWarnings("unchecked")
        Map<String, Object> totals = (Map<String, Object>) detail.get("totals");
        Map<String, Object> piecework = service.piecework(ORDER_ID, TENANT);

        // 10×0.40 + 5×0.40×1.70 = 4.00 + 3.40 = 7.40（返工不计件）—— 两处**恒等**
        assertThat((BigDecimal) totals.get("piecework_amount")).isEqualByComparingTo("7.40");
        assertThat((BigDecimal) totals.get("piecework_amount"))
                .as("过程明细的金额必须等于 /piecework 的 total（同一份 aggregate）")
                .isEqualByComparingTo((BigDecimal) piecework.get("total"));
    }

    @Test
    @DisplayName("过程明细：无加工单 → 空明细 + 零合计（未开始态，不是错误态，#4201）")
    void worklogWithoutProcessingOrderIsEmptyNotError() {
        when(orderMapper.selectOne(any())).thenReturn(order("confirmed"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(null);

        Map<String, Object> result = service.worklog("ORD-20260917-001", TENANT);

        assertThat(operationsOf(result)).isEmpty();
        assertThat(logsOf(result)).isEmpty();
        assertThat(result.get("processing_order_no")).isNull();
        assertThat(result.get("processing_status")).isNull();
        @SuppressWarnings("unchecked")
        Map<String, Object> totals = (Map<String, Object>) result.get("totals");
        assertThat((BigDecimal) totals.get("qualified_qty")).isEqualByComparingTo("0");
        assertThat((BigDecimal) totals.get("piecework_amount")).isEqualByComparingTo("0.00");
    }

    @Test
    @DisplayName("过程明细：缺 order_no → 422；跨租户/不存在 → 404（租户隔离，#4201）")
    void worklogValidatesAndIsolatesTenant() {
        assertThatThrownBy(() -> service.worklog("  ", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("order_no");

        // 同名订单号但属于别的租户 ⇒ resolveOrder 不认（fail-closed）
        Order other = order("producing");
        other.setTenantId(999L);
        when(orderMapper.selectById("ORD-20260917-001")).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(null);
        when(processingOrderMapper.selectOne(any())).thenReturn(null);

        assertThatThrownBy(() -> service.worklog("ORD-20260917-001", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("订单");

        // 跨租户订单**不得**读取该单的工序/报工（连查都不查）
        verify(positionOperationMapper, never()).selectList(any());
        verify(workLogMapper, never()).selectList(any());
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> operationsOf(Map<String, Object> result) {
        return (List<Map<String, Object>>) result.get("operations");
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> logsOf(Map<String, Object> result) {
        return (List<Map<String, Object>>) result.get("work_logs");
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

    // ── 报工人列（issue #4309：跟进人 = 只加「报工人」，零新字段，读报工记录）──────────
    //
    // 口径：报工人 = 该工序实例下报过工的人，取自 production_work_logs.worker_name；
    // **去重**、按**首次报工时间**升序（listWorkLogs 已按 created_at 升序 ⇒ 按遇到顺序去重即为
    // 首次报工序，故这里刻意让「先报工的人」与「姓名排序在前的人」不同，防实现按姓名/哈希排序）；
    // **只取 work_type='normal'**（与「已完成数量 / 计件」同源：返工/报废既不推进进度也不计件，
    // 混进本列会让相邻两列不同口径）；worker_name 空/blank ⇒ 「未署名」；无 normal 报工 ⇒ 空数组。
    // ⑤ 的红证：work logs 必须**一次取回**再内存分组 —— 按工序逐个查就是 N+1（#4304 同族病灶）。

    /** 报工记录夹具（时间用固定偏移，保证「首次报工」可判定）。 */
    private ProductionWorkLog workLog(String operationId, String workerName, String workType, String createdAt) {
        return ProductionWorkLog.builder()
                .id("log-" + operationId + "-" + workerName + "-" + workType + "-" + createdAt)
                .tenantId(TENANT).processingOrderId(PO_ID).operationId(operationId)
                .workerName(workerName).workType(workType)
                .qty(new BigDecimal("1.00")).qualifiedQty(new BigDecimal("1.00"))
                .createdAt(OffsetDateTime.parse(createdAt)).deleted(0)
                .build();
    }

    // ── 工序显示名统一（issue #4621）：工序实例 / 报工流水读面补 `logical_name` + `position` ──
    //
    // 口径（冻结）：显示名 = 逻辑工序名（既有映射**读时派生**）+ 部位（帘种 `position_kind`，如 `布帘`）。
    // 既有 `operation` / `operation_name` 是**工人端快照名**（变体名 `精裁-布`）⇒ **一字不动**
    // （历史数据与其它消费者仍要读它），但 **web 界面不得渲染该键**；派生**不写库**。

    /** 带**帘种**（`position_kind`）的工序实例夹具：`positionKind` 为空 = 存量行（V69 之前没有该列）。 */
    private ProcessingPositionOperation opWithPositionKind(String id, String name, String positionKind) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("布帘").positionKind(positionKind).seq(1).operationName(name)
                .groupName("后道").unit("套")
                .qty(new BigDecimal("10.00")).unitPrice(new BigDecimal("1.00")).factor(BigDecimal.ONE)
                .isMustFinish(false).isStartMarker(false)
                .status("pending").doneQty(BigDecimal.ZERO).deleted(0)
                .build();
    }

    /** 带**工序名快照**的报工记录（报工面显示名的来源；`operation_name` = 工人端快照名）。 */
    private ProductionWorkLog workLogNamed(String id, String operationId, String operationName) {
        return ProductionWorkLog.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID).operationId(operationId)
                .operationName(operationName).workerName("张三").workType("normal")
                .qty(new BigDecimal("1.00")).qualifiedQty(new BigDecimal("1.00"))
                .createdAt(OffsetDateTime.parse("2026-09-18T02:00:00Z")).deleted(0)
                .build();
    }

    /** 从 getOperations 响应里取某工序实例的视图（positions → operations）。 */
    @SuppressWarnings("unchecked")
    private Map<String, Object> operationViewOf(Map<String, Object> result, String operationId) {
        for (Map<String, Object> position : (List<Map<String, Object>>) result.get("positions")) {
            for (Map<String, Object> view : (List<Map<String, Object>>) position.get("operations")) {
                if (operationId.equals(view.get("id"))) {
                    return view;
                }
            }
        }
        throw new AssertionError("工序实例未出现在响应里: " + operationId);
    }

    @Test
    @DisplayName("#4621 工序实例读面补 logical_name + position（operation = 工人端快照名，一字不动）")
    void operationViewAddsDisplayKeys() {
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                opWithPositionKind("op-1", "精裁-布", "布帘"),
                opWithPositionKind("op-2", "外帘装袋", "布帘"),
                opWithPositionKind("op-3", "精裁-布", null)));
        when(workLogMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = service.getOperations(ORDER_ID, TENANT);

        assertThat(operationViewOf(result, "op-1"))
                .as("历史实例（快照名 = 变体名 `精裁-布`）⇒ 显示名读时派生为 `精裁` + `布帘`")
                .containsEntry("operation", "精裁-布")
                .containsEntry("logical_name", "精裁")
                .containsEntry("position", "布帘");
        assertThat(operationViewOf(result, "op-2"))
                .as("部位无关工序（名字里没编部位）⇒ position 为空，界面只显示逻辑名")
                .containsEntry("operation", "外帘装袋")
                .containsEntry("logical_name", "外帘装袋")
                .containsEntry("position", null);
        assertThat(operationViewOf(result, "op-3"))
                .as("存量行（V69 之前没有 position_kind）⇒ position 为空，logical_name 仍派生")
                .containsEntry("operation", "精裁-布")
                .containsEntry("logical_name", "精裁")
                .containsEntry("position", null);
    }

    @Test
    @DisplayName("#4621 报工流水读面补 logical_name + position（部位按 operationId 关联实例，不从名字猜）")
    void workLogViewsAddDisplayKeys() {
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                opWithPositionKind("op-1", "精裁-布", "布帘")));
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                workLogNamed("log-1", "op-1", "精裁-布")));

        Map<String, Object> result = service.getOperations(ORDER_ID, TENANT);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> logs = (List<Map<String, Object>>) result.get("work_logs");
        assertThat(logs).singleElement()
                .as("`operation_name` 是工人端快照名（一字不动）；界面渲染 logical_name + position")
                .satisfies(row -> assertThat(row)
                        .containsEntry("operation_name", "精裁-布")
                        .containsEntry("logical_name", "精裁")
                        .containsEntry("position", "布帘"));
    }

    /** 从 getOperations 响应里取某工序实例的 workers（positions → operations → workers）。 */
    @SuppressWarnings("unchecked")
    private List<String> workersOf(Map<String, Object> result, String operationId) {
        for (Map<String, Object> position : (List<Map<String, Object>>) result.get("positions")) {
            for (Map<String, Object> view : (List<Map<String, Object>>) position.get("operations")) {
                if (operationId.equals(view.get("id"))) {
                    return (List<String>) view.get("workers");
                }
            }
        }
        throw new AssertionError("工序实例未出现在响应里: " + operationId);
    }

    private void twoOperations() {
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "精裁-布", "10.00", false, "pending", "0.00", "1.00", "1.00"),
                op("op-2", "外帘装袋", "10.00", false, "pending", "0.00", "1.00", "1.00")));
    }

    @Test
    @DisplayName("报工人：同一工序两人先后报工 → 两人且按**首次报工时间**升序（非姓名序）")
    void workersOrderedByFirstReportTime() {
        twoOperations();
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                // 首次报工 = 李四（09:00）；张三 09:30 补报 ⇒ 期望 [李四, 张三]（按姓名排会得到 [张三, 李四]）
                workLog("op-1", "李四", "normal", "2026-09-18T09:00:00+08:00"),
                workLog("op-2", "王五", "normal", "2026-09-18T09:10:00+08:00"),
                workLog("op-1", "张三", "normal", "2026-09-18T09:30:00+08:00")));

        Map<String, Object> result = service.getOperations(ORDER_ID, TENANT);

        assertThat(workersOf(result, "op-1")).containsExactly("李四", "张三");
        // 分组不串号：op-2 只有王五
        assertThat(workersOf(result, "op-2")).containsExactly("王五");
    }

    @Test
    @DisplayName("报工人：同一人报两次 → 只出现一次（去重）")
    void workersDeduplicatedPerOperation() {
        twoOperations();
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                workLog("op-1", "张三", "normal", "2026-09-18T09:00:00+08:00"),
                workLog("op-1", "张三", "normal", "2026-09-18T09:05:00+08:00")));

        Map<String, Object> result = service.getOperations(ORDER_ID, TENANT);

        assertThat(workersOf(result, "op-1")).containsExactly("张三");
    }

    @Test
    @DisplayName("报工人：只有返工/报废报工 → 空数组（与「已完成数量/计件」同源，只认 normal）")
    void workersExcludeReworkAndScrap() {
        twoOperations();
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                workLog("op-1", "张三", "rework", "2026-09-18T09:00:00+08:00"),
                workLog("op-1", "李四", "scrap", "2026-09-18T09:10:00+08:00")));

        Map<String, Object> result = service.getOperations(ORDER_ID, TENANT);

        assertThat(workersOf(result, "op-1")).isEmpty();
    }

    @Test
    @DisplayName("报工人：无任何报工 → 空数组（前端渲染「—」，不是 null/缺键）")
    void workersEmptyWhenNoWorkLog() {
        twoOperations();
        when(workLogMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = service.getOperations(ORDER_ID, TENANT);

        assertThat(workersOf(result, "op-1")).isEmpty();
        assertThat(workersOf(result, "op-2")).isEmpty();
    }

    @Test
    @DisplayName("报工人：worker_name 空/blank → 「未署名」（与工人端报工明细同文案）")
    void workersBlankNameShowsUnsigned() {
        twoOperations();
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                workLog("op-1", null, "normal", "2026-09-18T09:00:00+08:00"),
                workLog("op-1", "   ", "normal", "2026-09-18T09:10:00+08:00")));

        Map<String, Object> result = service.getOperations(ORDER_ID, TENANT);

        assertThat(workersOf(result, "op-1")).containsExactly("未署名");
    }

    @Test
    @DisplayName("报工人：work logs **只查一次**（按工序逐个查 = N+1，#4304 同族）")
    void workLogsQueriedOnceForAllOperations() {
        twoOperations();
        when(workLogMapper.selectList(any())).thenReturn(List.of());

        service.getOperations(ORDER_ID, TENANT);

        verify(workLogMapper, times(1)).selectList(any());
    }

    // ══════════════════════════ §5 防呆（issue #4116 P0-3；② 越站已于 #4694 删除）══════════════════════════
    //
    // 病灶（逐项一次真实误报工的形态）：
    //   ① 重复报工：工人连点两次 / 网络重试 ⇒ 同一笔报工落两条明细、done_qty 翻倍（原代码
    //      `doneQty = doneQty.add(qualifiedQty)` 无条件累加，且前端无 in-flight 锁）；
    //   ② 越站（**已删除**，issue #4694，用户逐字裁定「这个不需要管理，因为现实生产过程中工人
    //      会自动推进，系统就无需管理生产顺序」）：原为「前道未完成不得报后续工序 ⇒ 422」，
    //      现改为**顺序不拦**（跳站按实际工序正常记账）。⚠️ 删的是**顺序闸门**，不是**工序确定性**：
    //      「这次扫的是哪道工序必须确定」仍是硬约束（无 operationId ⇒ 拒，见下方 #4694 专测）。
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
    @DisplayName("§5-2 越站闸门已删除（#4694 用户裁定）：同部位前道未完成 ⇒ 跳站报后续工序**正常记账**（不再 422）")
    void reportAllowedWhenPredecessorOperationNotDone() {
        when(positionOperationMapper.selectById("op-2"))
                .thenReturn(positionOp("op-2", "布帘", 2, "布帘车被", "10.00", "0.00", "pending", false, 0));
        // 报工前快照：同部位 seq=1「精裁-布」只报了 4/10（未完成）—— **这条夹具是红证的关键**：
        // 改前它让本用例 422（OPERATION_SEQUENCE_VIOLATION），改后必须放行；
        // 删闸门后 selectList 只被「必完判定」消费（本桩不再参与拦截，但保留了「前道未完成」的现场）。
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                positionOp("op-1", "布帘", 1, "精裁-布", "10.00", "4.00", "done", true, 0),
                positionOp("op-2", "布帘", 2, "布帘车被", "10.00", "0.00", "pending", false, 0)));

        Map<String, Object> result = report("op-2", reportBody("10", "10", "normal"));

        // 改钉（**≠ 放宽**）：改前这条期望 422 +「请先报工完成前道工序」suggestion；改后期望「正常记账」——
        // 判据对象是同一条行为（前道未完成时报后续工序），只是**用户裁定**把期望从「拦」改成「放行」；
        // 断言强度不降（仍逐项钉住落明细 / 推进 / 按实际工序记账 / 快照单价）。
        assertThat((BigDecimal) result.get("done_qty")).isEqualByComparingTo("10.00");
        assertThat(result.get("status")).isEqualTo("done");
        ArgumentCaptor<ProductionWorkLog> logCaptor = ArgumentCaptor.forClass(ProductionWorkLog.class);
        verify(workLogMapper).insert(logCaptor.capture());
        verify(positionOperationMapper).advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any());
        // 按**实际做的工序**记账（不是「被拦掉」也不是「记到前道」）
        assertThat(logCaptor.getValue().getOperationId()).isEqualTo("op-2");
        assertThat(logCaptor.getValue().getOperationName()).isEqualTo("布帘车被");
        // 计件口径不受顺序影响：合格数量 × 报工那刻的单价快照（10 × 0.40）
        assertThat(logCaptor.getValue().getQualifiedQty()).isEqualByComparingTo("10.00");
        assertThat(logCaptor.getValue().getUnitPrice()).isEqualByComparingTo("0.40");
    }

    @Test
    @DisplayName("§5-5 工序必须确定（#4694 硬约束）：operationId 缺失/空白 ⇒ 拒绝记账，不落明细、不推进")
    void reportRejectedWhenOperationNotDetermined() {
        for (String undetermined : new String[]{null, "", "   "}) {
            org.mockito.Mockito.clearInvocations(workLogMapper, positionOperationMapper);
            assertThatThrownBy(() -> report(undetermined, reportBody("1", "1", "normal")))
                    .isInstanceOf(BusinessException.class)
                    .as("工序未确定却记账 = 计件记错工序 ⇒ 发错工资（用户裁定②-2 的硬约束）")
                    .hasMessageContaining("工序未确定");
            verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
            verify(positionOperationMapper, never())
                    .advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any());
        }
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
    @DisplayName("§5-2 返工/报废只记账不推进（#4694 后顺序已无门禁，本行为不变）")
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

    // ══════════════════════════════════════════════════════════════════════════════════
    // 工人端规格可见面（issue #4459 §3.1）—— 扫码后要能核对「做的是哪一件」
    // ══════════════════════════════════════════════════════════════════════════════════

    /** 订单行夹具：宽高 + 工艺规格列（V63）+ 算料输出（processing_info）。 */
    private OrderItem orderItem(String id, String productName, String width, String height) {
        OrderItem item = new OrderItem();
        item.setId(id);
        item.setTenantId(TENANT);
        item.setOrderId(ORDER_ID);
        item.setProductName(productName);
        item.setWidth(new BigDecimal(width));
        item.setHeight(new BigDecimal(height));
        item.setCurtainType("布帘");
        item.setCraft("韩褶");
        item.setOpenCount(4);
        item.setCuttingMode("定高买宽");
        item.setIsShaped(true);
        item.setFullness(new BigDecimal("2.00"));
        item.setDeleted(0);
        java.util.Map<String, Object> pi = new java.util.LinkedHashMap<>();
        pi.put("fabric_meters", new BigDecimal("12.3"));
        pi.put("processingMeters", new BigDecimal("12.3"));
        item.setProcessingInfo(pi);
        return item;
    }

    @Test
    @DisplayName("工人端规格可见面：扫码后部位带出 宽/高/工艺/加工类型/开数/褶倍/定型/用料（issue #4459 §3.1）")
    void getOperationsCarriesOrderLineSpec() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        ProcessingPositionOperation op = ProcessingPositionOperation.builder()
                .id("op-1").tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("布艺遮光帘A 米白").orderItemId("item-A").positionKind("布帘")
                .seq(1).operationName("精裁-布").groupName("裁剪").unit("米")
                .qty(new BigDecimal("12.30")).unitPrice(new BigDecimal("0.40")).factor(BigDecimal.ONE)
                .isMustFinish(false).isStartMarker(true).status("pending").doneQty(BigDecimal.ZERO)
                .deleted(0).build();
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(op));
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItem("item-A", "布艺遮光帘A", "6.6", "2.92")));

        Map<String, Object> result = service.getOperations(ORDER_ID, TENANT);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> positions = (List<Map<String, Object>>) result.get("positions");
        assertThat(positions).hasSize(1);
        Map<String, Object> position = positions.get(0);
        // 既有键不变（向后兼容）
        assertThat(position.get("position_name")).isEqualTo("布艺遮光帘A 米白");
        assertThat(position.get("order_item_id")).isEqualTo("item-A");
        // 新增规格键：工人核对「做的是哪一件」的唯一依据
        assertThat(position.get("width")).isEqualTo(new BigDecimal("6.6"));
        assertThat(position.get("height")).isEqualTo(new BigDecimal("2.92"));
        assertThat(position.get("craft")).isEqualTo("韩褶");
        assertThat(position.get("curtainType")).isEqualTo("布帘");
        assertThat(position.get("openCount")).isEqualTo(4);
        assertThat(position.get("cuttingMode")).isEqualTo("定高买宽");
        assertThat(position.get("isShaped")).isEqualTo(true);
        assertThat(position.get("fullness")).isEqualTo(new BigDecimal("2.00"));
        // 用料 = 算料输出（单一真值 = ai-agent 引擎，Java 侧不重算）
        assertThat(position.get("fabric_meters")).isEqualTo(new BigDecimal("12.3"));
    }

    @Test
    @DisplayName("操作记录：扫码响应带**服务端**全单报工流水（倒序 + 人/工序/数量/时刻）")
    void getOperationsCarriesServerWorkLogs() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                positionOp("op-1", "布帘", 1, "精裁-布", "10.00", "10.00", "done", true, 0)));
        when(orderItemMapper.selectList(any())).thenReturn(List.of());
        ProductionWorkLog first = ProductionWorkLog.builder()
                .id("w-1").tenantId(TENANT).processingOrderId(PO_ID).operationId("op-1")
                .operationName("精裁-布").workerName("蒋雪云").qualifiedQty(new BigDecimal("11"))
                .workType("normal").createdAt(OffsetDateTime.parse("2026-09-19T02:00:00Z")).deleted(0).build();
        ProductionWorkLog second = ProductionWorkLog.builder()
                .id("w-2").tenantId(TENANT).processingOrderId(PO_ID).operationId("op-1")
                .operationName("定型-布").workerName("李红梅").qualifiedQty(new BigDecimal("3"))
                .workType("rework").createdAt(OffsetDateTime.parse("2026-09-19T03:00:00Z")).deleted(0).build();
        when(workLogMapper.selectList(any())).thenReturn(List.of(first, second));

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> logs =
                (List<Map<String, Object>>) service.getOperations(ORDER_ID, TENANT).get("work_logs");

        assertThat(logs).hasSize(2);
        // 倒序：最近的在最上面（工人关心「我刚报的进去了没有」）
        assertThat(logs.get(0).get("worker_name")).isEqualTo("李红梅");
        assertThat(logs.get(0).get("operation_name")).isEqualTo("定型-布");
        assertThat(logs.get(0).get("work_type")).isEqualTo("rework");
        assertThat(logs.get(1).get("worker_name")).isEqualTo("蒋雪云");
        assertThat((BigDecimal) logs.get(1).get("qualified_qty")).isEqualByComparingTo("11");
        assertThat(logs.get(1).get("created_at")).isEqualTo("2026-09-19T02:00:00Z");
    }

    @Test
    @DisplayName("操作记录红证：无加工单 ⇒ work_logs 是**空数组**（键在场，不是 null）")
    void getOperationsWorkLogsEmptyWhenNoProcessingOrder() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(null);

        Map<String, Object> result = service.getOperations(ORDER_ID, TENANT);

        assertThat(result).containsKey("work_logs");
        assertThat((List<?>) result.get("work_logs")).isEmpty();
    }

    @Test
    @DisplayName("规格红证：订单行已不存在（脏数据）⇒ **不加任何规格键**，绝不补默认值冒充已知")
    void getOperationsOmitsSpecWhenOrderLineGone() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        ProcessingPositionOperation op = ProcessingPositionOperation.builder()
                .id("op-1").tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("布帘").orderItemId("item-gone").positionKind("布帘")
                .seq(1).operationName("精裁-布").groupName("裁剪").unit("米")
                .qty(new BigDecimal("1.00")).unitPrice(new BigDecimal("0.40")).factor(BigDecimal.ONE)
                .isMustFinish(false).isStartMarker(false).status("pending").doneQty(BigDecimal.ZERO)
                .deleted(0).build();
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(op));
        when(orderItemMapper.selectList(any())).thenReturn(List.of());

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> positions =
                (List<Map<String, Object>>) service.getOperations(ORDER_ID, TENANT).get("positions");

        assertThat(positions).hasSize(1);
        assertThat(positions.get(0))
                .as("订单行取不到 ⇒ 一个规格键都不加（缺键就缺，不补默认值）")
                .doesNotContainKeys("width", "height", "craft", "fabric_meters");
    }

    // ── 派工批次可见面（V116 / issue #5145 阶段 1）──────────────────────────────

    /** 带加工单号 + 部位行标识的桩（批次可见面用：两者缺一就走不到追加那一段）。 */
    private void stubPositionsForBatchView() {
        ProcessingOrder po = processingOrder();
        po.setProcessingOrderNo("JG-20260923-0001");
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(po);
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                ProcessingPositionOperation.builder()
                        .id("op-1").tenantId(TENANT).processingOrderId(PO_ID)
                        .positionName("布帘").orderItemId("item-A").positionKind("布帘")
                        .seq(1).operationName("精裁-布").groupName("裁剪").unit("米")
                        .qty(new BigDecimal("10.00")).unitPrice(new BigDecimal("0.40")).factor(BigDecimal.ONE)
                        .isMustFinish(false).isStartMarker(true).status("pending").doneQty(BigDecimal.ZERO)
                        .deleted(0).build()));
        when(orderItemMapper.selectList(any()))
                .thenReturn(List.of(orderItem("item-A", "布艺遮光帘A", "6.6", "2.92")));
    }

    @Test
    @DisplayName("PG-060 工人端批次可见面：服务端指派过批次 ⇒ 部位上追加 batch_no + batch_meters")
    void getOperationsStampsBatchAssignment() {
        stubPositionsForBatchView();
        // 真值源 = 批次消耗台账（不是订单侧 processing_info.batchNo —— 那是面料批号，V111 明令不得混用）
        when(stockBatchConsumptionService.assignmentsOf(TENANT, "JG-20260923-0001"))
                .thenReturn(Map.of("item-A",
                        new StockBatchConsumptionService.BatchAssignment("PC-20260923-0001", new BigDecimal("2.7"))));

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> positions =
                (List<Map<String, Object>>) service.getOperations(ORDER_ID, TENANT).get("positions");

        assertThat(positions.get(0)).containsEntry("batch_no", "PC-20260923-0001")
                .containsEntry("batch_meters", new BigDecimal("2.7"));
    }

    @Test
    @DisplayName("PG-060 工人端批次红证：未指派批次 ⇒ 两键都不加（缺键就缺，不补默认值）")
    void getOperationsOmitsBatchKeysWhenNotAssigned() {
        stubPositionsForBatchView();
        when(stockBatchConsumptionService.assignmentsOf(TENANT, "JG-20260923-0001")).thenReturn(Map.of());

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> positions =
                (List<Map<String, Object>>) service.getOperations(ORDER_ID, TENANT).get("positions");

        assertThat(positions.get(0))
                .as("未指派 ⇒ 不显示批次行（与规格可见面同一条「缺键就缺」口径）")
                .doesNotContainKeys("batch_no", "batch_meters");
    }

    // ============================================================ D13：首工序报满 ⇒ 加工单进生产中
    //                                                              （issue #4695；状态机联动）
    //
    // 病灶：`is_start_marker`（工序库的「标记生产开始」开关）落到实例上、读面也带得出来，
    // 但**没有任何消费者** —— 首工序报满之后加工单仍是 `issued`，在产单被当成「未开工」。
    // 目标态（用户裁定「落 D13」）= 首工序报满 ⇒ 加工单 `issued → in_processing` + 落
    // `in_processing_at`；且**走状态机**（合法性取自 `ProcessingOrderService` 的
    // `STATUS_TRANSITIONS`，不裸 UPDATE 绕过）、**幂等**（重复/并发只转一次、不改写开工时刻）。

    @Test
    @DisplayName("D13 红证①（#4695）：首工序（is_start_marker）报满 ⇒ 加工单 issued → in_processing + 落 in_processing_at")
    void firstOperationReportedDoneStartsProduction() {
        PoRow row = stubIssuedProcessingOrder();
        when(positionOperationMapper.selectById("op-s"))
                .thenReturn(op("op-s", "精裁-布", "1.00", false, "pending", "0.00", "0.40", "1.00", true));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-s", "精裁-布", "1.00", false, "done", "1.00", "0.40", "1.00", true)));

        service.report(ORDER_ID, "op-s", reportBody("1", "1", "normal"), TENANT, null);

        assertThat(row.status.get())
                .as("首工序报满 ⇒ 加工单进入生产中（改前恒为 issued = 在产单被当成未开工）")
                .isEqualTo("in_processing");
        assertThat(row.inProcessingStamps).as("开工时刻必须落笔（且只有一笔）").hasSize(1);
        // 起始态由**状态机**给出（issued 是该迁移的唯一合法起点），不是裸 UPDATE
        verify(processingOrderMapper).markInProcessingIfFrom(eq(PO_ID), eq(TENANT), eq("issued"), any());
        // #4117 红线一字不动：订单表仍一字不写（生产侧不得直写订单状态）
        verify(orderMapper, never()).update(any(), any());
    }

    @Test
    @DisplayName("D13 顺序判据：单工序加工单 ⇒ 先进 in_processing 再 completed（开工时刻不得被完工判定跳过）")
    void singleOperationOrderEntersProductionBeforeCompletion() {
        PoRow row = stubIssuedProcessingOrder();
        // 完工写面替身：把「完工那一刻加工单是什么状态」记下来 —— 顺序错了这里会看到 issued
        List<String> statusSeenAtCompletion = new ArrayList<>();
        when(processingOrderMapper.markCompletedIfActive(eq(PO_ID), eq(TENANT), any()))
                .thenAnswer(invocation -> {
                    statusSeenAtCompletion.add(row.status.get());
                    row.status.set("completed");
                    return 1;
                });
        when(positionOperationMapper.selectById("op-s"))
                .thenReturn(op("op-s", "精裁-布", "1.00", false, "pending", "0.00", "0.40", "1.00", true));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-s", "精裁-布", "1.00", false, "done", "1.00", "0.40", "1.00", true)));

        Map<String, Object> result =
                service.report(ORDER_ID, "op-s", reportBody("1", "1", "normal"), TENANT, null);

        assertThat(statusSeenAtCompletion)
                .as("完工判定跑之前，加工单必须已经进过 in_processing（否则 in_processing_at 永远为空）")
                .containsExactly("in_processing");
        assertThat(row.status.get()).isEqualTo("completed");
        assertThat(result.get("order_completed")).isEqualTo(true);
        assertThat(row.inProcessingStamps).as("进了生产中又完工 ⇒ 开工时刻仍在").hasSize(1);
    }

    @Test
    @DisplayName("D13 幂等红证（#4695）：重复报工 ⇒ 状态只转一次、写面只被触碰一次")
    void repeatedReportTransitionsOnlyOnce() {
        PoRow row = stubIssuedProcessingOrder();
        when(positionOperationMapper.selectById("op-s"))
                .thenReturn(op("op-s", "精裁-布", "1.00", false, "pending", "0.00", "0.40", "1.00", true));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-s", "精裁-布", "1.00", false, "done", "1.00", "0.40", "1.00", true)));

        service.report(ORDER_ID, "op-s", reportBody("1", "1", "normal"), TENANT, null);
        // 第二次：不同幂等键 ⇒ 真的执行（不是被幂等回放挡掉），但状态机已不许 in_processing → in_processing
        service.report(ORDER_ID, "op-s", reportBody("1", "1", "normal"), TENANT, null);

        assertThat(row.status.get()).isEqualTo("in_processing");
        assertThat(row.inProcessingStamps).as("开工时刻只有第一次那笔").hasSize(1);
        verify(processingOrderMapper, times(1))
                .markInProcessingIfFrom(eq(PO_ID), eq(TENANT), eq("issued"), any());
    }

    @Test
    @DisplayName("D13 并发红证（#4695）：状态已被别处推进（读到的仍是旧状态）⇒ 写面 0 行，状态与开工时刻都不动")
    void staleReadDoesNotDoubleTransitionNorMoveStamp() {
        OffsetDateTime firstStamp = OffsetDateTime.parse("2026-09-26T09:00:00+08:00");
        PoRow row = stubIssuedProcessingOrder();
        // 模拟并发：库里已经转过（in_processing + 首笔开工时刻），而本次报工读到的是**旧**状态 issued
        row.status.set("in_processing");
        row.inProcessingStamps.add(firstStamp);
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenAnswer(invocation -> {
            ProcessingOrder stale = processingOrder();
            stale.setStatus("issued");
            return stale;
        });
        when(positionOperationMapper.selectById("op-s"))
                .thenReturn(op("op-s", "精裁-布", "1.00", false, "pending", "0.00", "0.40", "1.00", true));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-s", "精裁-布", "1.00", false, "done", "1.00", "0.40", "1.00", true)));

        service.report(ORDER_ID, "op-s", reportBody("1", "1", "normal"), TENANT, null);

        assertThat(row.status.get()).as("不得二次转态").isEqualTo("in_processing");
        assertThat(row.inProcessingStamps)
                .as("不得改写首次开工时刻（CAS 谓词不成立 ⇒ 0 行）")
                .containsExactly(firstStamp);
        // 尝试过写、但被 SQL 谓词挡下（0 行）—— 断言写面被调用次数 = 1，证明「只转一次」不是靠不调用
        verify(processingOrderMapper, times(1))
                .markInProcessingIfFrom(eq(PO_ID), eq(TENANT), eq("issued"), any());
    }

    @Test
    @DisplayName("D13/A6 保守读法：加工单还是 generated（未发加工）⇒ 首工序报满**不动它**（不绕过状态机直达）")
    void generatedProcessingOrderDoesNotJumpIntoProduction() {
        PoRow row = stubIssuedProcessingOrder();
        row.status.set("generated");
        when(positionOperationMapper.selectById("op-s"))
                .thenReturn(op("op-s", "精裁-布", "1.00", false, "pending", "0.00", "0.40", "1.00", true));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-s", "精裁-布", "1.00", false, "done", "1.00", "0.40", "1.00", true)));

        service.report(ORDER_ID, "op-s", reportBody("1", "1", "normal"), TENANT, null);

        assertThat(row.status.get())
                .as("generated 不能直达 in_processing（A6 未裁定 ⇒ 保守不动，仍需先「发加工」）")
                .isEqualTo("generated");
        verify(processingOrderMapper, never()).markInProcessingIfFrom(any(), any(), any(), any());
    }

    @Test
    @DisplayName("D13 负例：**非**首工序（is_start_marker=false）报满 ⇒ 不触发（触发器是那道标记工序）")
    void nonStartMarkerOperationDoneDoesNotStartProduction() {
        PoRow row = stubIssuedProcessingOrder();
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(op("op-1", "外帘装袋", "1.00", true, "pending", "0.00", "1.00", "1.00"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "外帘装袋", "1.00", true, "done", "1.00", "1.00", "1.00")));

        service.report(ORDER_ID, "op-1", reportBody("1", "1", "normal"), TENANT, null);

        assertThat(row.status.get()).isEqualTo("issued");
        verify(processingOrderMapper, never()).markInProcessingIfFrom(any(), any(), any(), any());
    }

    @Test
    @DisplayName("D13 负例：首工序**部分**报工（4/10 米）⇒ 不触发（触发点是「报满」，不是认领）")
    void partialReportOnStartMarkerDoesNotStartProduction() {
        PoRow row = stubIssuedProcessingOrder();
        when(positionOperationMapper.selectById("op-s"))
                .thenReturn(op("op-s", "精裁-布", "10.00", false, "pending", "0.00", "0.40", "1.00", true));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-s", "精裁-布", "10.00", false, "done", "4.00", "0.40", "1.00", true)));

        service.report(ORDER_ID, "op-s", reportBody("4", "4", "normal"), TENANT, null);

        assertThat(row.status.get()).as("4/10 米不是「报满」").isEqualTo("issued");
        verify(processingOrderMapper, never()).markInProcessingIfFrom(any(), any(), any(), any());
    }
}
