// case_ids: PG-021
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.mapper.OrderItemMapper;
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
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * <b>未定价在计件面必须可见，且不得静默按 0 计件</b>（issue #4696，P1）。
 *
 * <h2>缺陷原形</h2>
 * 实例化侧把「矩阵价 NULL」折成 0 元落库（见 {@code UnpricedNotZeroTest}）⇒
 * 报工快照也是 0 ⇒ 报表合计里那笔活是 <b>¥0.00</b>，与「定价为 0 的工序」**长得一模一样**、
 * 与「该工序还没做过」也长得一样 ⇒ <b>工人白干且无人知道</b>。
 *
 * <h2>判据（每条独立、注入式可红）</h2>
 * <ol>
 *   <li><b>红证②</b>：未定价工序的报工 ⇒ 响应带 {@code unpriced} 块（qty + 工序清单 + 可行动
 *       hint），且那笔数量 <b>不计入</b> 金额 —— 改前该键根本不存在（静默不可见）；</li>
 *   <li><b>反向护栏</b>：<b>价 0</b> 的工序照常计入合计（金额 0.00）但**不进** {@code unpriced}
 *       块 —— 「未定价」与「价本来就是 0」必须可区分（两者同形 ⇒ 必红）；</li>
 *   <li><b>同口径</b>：per-order 汇总与期间报表**同一份聚合** ⇒ 两处的 {@code unpriced} 块一致
 *       （只有一处接线 ⇒ 红）；</li>
 *   <li><b>报工快照</b>：未定价实例上报工 ⇒ 快照单价为 {@code null} + {@code price_state='unpriced'}，
 *       且报工**照常推进进度**（不因未定价而拒绝工人报工）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("未定价在计件面可见且不按 0 计件（issue #4696）")
class UnpricedPieceworkReportTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "dc4e2c1be65482fd7c570f0bed7cb10c";
    private static final String PO_ID = "po-fabric";

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

    private ProductionService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        service = new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper,
                orderMapper, orderItemMapper, clientRequestIdService);
        Order order = new Order();
        order.setId(ORDER_ID);
        order.setTenantId(TENANT);
        order.setOrderNo("20260920201530002");
        order.setStatus("producing");
        order.setDeleted(0);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order);
        ProcessingOrder po = new ProcessingOrder();
        po.setId(PO_ID);
        po.setTenantId(TENANT);
        po.setOrderId(ORDER_ID);
        po.setProcessingOrderNo("JG-20260920-0001");
        po.setStatus("generated");
        po.setDeleted(0);
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(po);
        when(processingOrderMapper.selectById(PO_ID)).thenReturn(po);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    /** 一道工序实例：{@code unitPrice} 为 {@code null} = 未定价（V90 起可空）。 */
    private ProcessingPositionOperation op(String id, String name, BigDecimal unitPrice) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("布料").seq(1).operationName(name).groupName("后道").unit("米")
                .qty(new BigDecimal("10.00")).unitPrice(unitPrice).factor(BigDecimal.ONE)
                .isMustFinish(false).isStartMarker(false)
                .status("done").doneQty(new BigDecimal("3")).deleted(0).build();
    }

    /** 一条报工：{@code unitPrice} 为 {@code null} = 报工那一刻该工序未定价（快照固化）。 */
    private ProductionWorkLog log(String opId, String name, String qty, BigDecimal unitPrice,
                                  String priceState) {
        return ProductionWorkLog.builder()
                .tenantId(TENANT).processingOrderId(PO_ID).operationId(opId).operationName(name)
                .workerId("w-1").workerName("张三").qty(new BigDecimal(qty))
                .qualifiedQty(new BigDecimal(qty)).unitPrice(unitPrice).priceState(priceState)
                .workType("normal").workDate(LocalDate.of(2026, 9, 20))
                .deleted(0).build();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> unpricedBlock(Map<String, Object> report) {
        Object block = report.get("unpriced");
        assertThat(block)
                .as("响应必须带 `unpriced` 块 —— 缺它 = 未定价在计件面**不可见**（改前的静默形态）")
                .isInstanceOf(Map.class);
        return (Map<String, Object>) block;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> unpricedOperations(Map<String, Object> report) {
        return (List<Map<String, Object>>) unpricedBlock(report).get("operations");
    }

    // ══════════════════════ 红证②：未定价可见且不计 0 ══════════════════════

    @Test
    @DisplayName("🔴 红证②：未定价工序的报工 ⇒ 报表带 unpriced 块（qty + 工序 + hint），**不计入合计**")
    void unpricedWorkIsVisibleAndExcludedFromTheTotal() {
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-unpriced", "配料", null),
                op("op-priced", "打包", new BigDecimal("1.00"))));
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                log("op-unpriced", "配料", "3", null, "unpriced"),
                log("op-priced", "打包", "2", new BigDecimal("1.00"), "priced")));

        Map<String, Object> report = service.piecework(ORDER_ID, TENANT);

        // ① 合计只含**已定价**那笔（3 × 未定价 不得按 0 计入，2 × ¥1.00 = ¥2.00）
        assertThat((java.math.BigDecimal) report.get("total")).isEqualByComparingTo("2.00");
        // ② 未定价那笔**必须可见**：数量 + 工序名 + 可行动 hint
        assertThat((java.math.BigDecimal) unpricedBlock(report).get("qty")).isEqualByComparingTo("3");
        assertThat(unpricedOperations(report))
                .as("未定价工序必须逐条列出（否则商家无从知道该给哪道工序定价）")
                .hasSize(1);
        assertThat(unpricedOperations(report).get(0))
                .containsEntry("operation", "配料");
        assertThat(String.valueOf(unpricedBlock(report).get("hint")))
                .as("hint 必须**可行动**：指向定价入口")
                .contains("/production/routings")
                .contains("未定价");
    }

    @Test
    @DisplayName("🔴 红证②（期间报表）：pieceworkSummary 同样可见未定价（不能只在 per-order 面）")
    void unpricedIsVisibleInThePeriodReportToo() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                log("op-unpriced", "配料", "3", null, "unpriced")));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-unpriced", "配料", null)));

        Map<String, Object> report = service.pieceworkSummary("2026-09", null, TENANT);

        assertThat((java.math.BigDecimal) report.get("total")).isEqualByComparingTo("0.00");
        assertThat((java.math.BigDecimal) unpricedBlock(report).get("qty")).isEqualByComparingTo("3");
        assertThat(unpricedOperations(report)).hasSize(1);
    }

    @Test
    @DisplayName("🔴 同口径：per-order 汇总与期间报表的 unpriced 块**一致**（只有一处接线 ⇒ 红）")
    void bothPieceworkSurfacesReportTheSameUnpricedRows() {
        List<ProcessingPositionOperation> ops = List.of(op("op-unpriced", "配料", null));
        List<ProductionWorkLog> logs = List.of(log("op-unpriced", "配料", "3", null, "unpriced"));
        when(positionOperationMapper.selectList(any())).thenReturn(ops);
        when(workLogMapper.selectList(any())).thenReturn(logs);

        Map<String, Object> perOrder = service.piecework(ORDER_ID, TENANT);
        Map<String, Object> period = service.pieceworkSummary("2026-09", null, TENANT);

        assertThat(perOrder.get("unpriced")).as("两套端点必须同口径").isEqualTo(period.get("unpriced"));
    }

    // ══════════════════════ 反向护栏：价 0 ≠ 未定价 ══════════════════════

    @Test
    @DisplayName("反向护栏：**价 0** 的工序照常计入合计，且**不进** unpriced 块（两者可区分）")
    void zeroPricedWorkIsCountedAndNotListedAsUnpriced() {
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-zero", "配料", BigDecimal.ZERO),
                op("op-unpriced", "打包", null)));
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                log("op-zero", "配料", "3", BigDecimal.ZERO, "priced"),
                log("op-unpriced", "打包", "5", null, "unpriced")));

        Map<String, Object> report = service.piecework(ORDER_ID, TENANT);

        assertThat(unpricedOperations(report))
                .as("「定价 0 元」是**有价** ⇒ 绝不进 unpriced 清单（两者同形 ⇒ 红）")
                .extracting(row -> row.get("operation"))
                .containsExactly("打包");
        assertThat((java.math.BigDecimal) unpricedBlock(report).get("qty")).isEqualByComparingTo("5");
        // 价 0 那笔照常进 per_operation（金额 0.00）—— 它是一笔**已定价**的账
        assertThat((List<Map<String, Object>>) report.get("per_operation"))
                .as("已定价（含价 0）的工序必须在 per_operation 里，而不是在 unpriced 清单里")
                .extracting(row -> row.get("operation"))
                .contains("配料");
    }

    @Test
    @DisplayName("反向护栏（存量行不受影响）：price_state 为 NULL 的**历史**报工仍按快照计价，不进 unpriced")
    void legacyRowsWithoutPriceStateKeepTheirHistoricalAmount() {
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-legacy", "精裁", new BigDecimal("0.40"))));
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                log("op-legacy", "精裁", "3", new BigDecimal("0.40"), null)));

        Map<String, Object> report = service.piecework(ORDER_ID, TENANT);

        assertThat((java.math.BigDecimal) report.get("total")).as("历史计件值一字不动").isEqualByComparingTo("1.20");
        assertThat((java.math.BigDecimal) unpricedBlock(report).get("qty")).isEqualByComparingTo("0");
        assertThat(unpricedOperations(report)).isEmpty();
    }

    // ══════════════════════ 报工快照：未定价固化，且不挡工人 ══════════════════════

    @Test
    @DisplayName("🔴 报工：未定价实例 ⇒ 快照单价 null + price_state=unpriced，且进度**照常推进**")
    void reportingOnAnUnpricedOperationSnapshotsUnpricedAndStillAdvancesProgress() {
        ProcessingPositionOperation unpriced = op("op-1", "配料", null);
        unpriced.setStatus("pending");
        unpriced.setDoneQty(BigDecimal.ZERO);
        when(positionOperationMapper.selectById("op-1")).thenReturn(unpriced);
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(unpriced));
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(true);
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any()))
                .thenReturn(1);

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("qty", new BigDecimal("3"));
        body.put("qualified_qty", new BigDecimal("3"));
        body.put("worker_name", "张三");
        body.put("work_type", "normal");

        Map<String, Object> result = service.report(ORDER_ID, "op-1", body, TENANT, null);

        ArgumentCaptor<ProductionWorkLog> captor = ArgumentCaptor.forClass(ProductionWorkLog.class);
        verify(workLogMapper).insert(captor.capture());
        assertThat(captor.getValue().getUnitPrice())
                .as("未定价 ⇒ 快照 null（写 0 = 把「未定价」永久固化成「0 元工资」）")
                .isNull();
        assertThat(captor.getValue().getPriceState()).isEqualTo("unpriced");
        assertThat(result.get("status"))
                .as("未定价**不得**挡住工人报工（挡住 = 进度推不动、活干了却报不上）")
                .isEqualTo("done");
    }
}
