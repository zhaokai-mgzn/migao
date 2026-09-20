package com.migao.admin.service;

// case_ids: PG-021

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
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

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 计件工资报表语义测试（issue #4205，P1）
 *
 * <p>真值源 §4：「工资报表 = 报工事件聚合（按人/按期/按单下钻）」+「计件工资 = Σ(报工数量 × 工序单价)」。
 * 走查实测数据（2026-09-18，SHA d5bca241）：加工单 JG-20260918-6914 有 1 条报工
 * （「走查工人」精裁-布 3 米 × ¥0.40 = ¥1.20）。</p>
 *
 * <p>本测试守四条（每条都有独立红证）：① 按期取 work_date 落在当月的报工；② 返工/报废不计件；
 * ③ **口径一致性** —— 同一批报工下「per-order 合计 == 报表 total」（两套端点禁止两套算法）；
 * ④ 实例缺失（软删）的报工不计价 —— 与 per-order **同一判据**，否则同一笔报工在两处数值不等。</p>
 *
 * <p>⑤（issue #4351，P0）：**金额在报工那一刻固化** —— 带快照的报工在实例软删（重新实例化）后
 * 金额**不变**；④ 只对「既无快照、实例又真的不存在」的真·脏数据成立。</p>
 *
 * <p>⑥（issue #4604，用户裁定 B **不追溯**）：读时用**当时快照**的系数 —— 历史报工（快照
 * {@code factor=1.70}，如「一分二」）金额**一字不变**；新报工（#4589 起不再写 {@code factor}）
 * 快照恒 {@code NULL} ⇒ 系数取 1 ⇒ 以后不乘。⚠️ #4589 把聚合改成「读时不算系数」时，
 * 效果恰恰是**回溯**（落库数据没动，但呈现/结算值从 1.7× 掉到 1×）——「落库不动」≠「历史不回溯」。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductionService 计件工资报表（#4205）")
class ProductionPieceworkSummaryTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "dc4e2c1be65482fd7c570f0bed7cb10c";
    private static final String PO_ID = "po-walkthrough";

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

    private ProductionService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        service = new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper,
                orderMapper, orderItemMapper, clientRequestIdService);
        Order order = new Order();
        order.setId(ORDER_ID);
        order.setTenantId(TENANT);
        order.setOrderNo("20260918201530002");
        order.setStatus("producing");
        order.setDeleted(0);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order);
        ProcessingOrder po = new ProcessingOrder();
        po.setId(PO_ID);
        po.setTenantId(TENANT);
        po.setOrderId(ORDER_ID);
        po.setProcessingOrderNo("JG-20260918-6914");
        po.setStatus("generated");
        po.setDeleted(0);
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(po);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private ProcessingPositionOperation op(String id, String name, String unitPrice, String factor) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("布艺遮光帘A 米白").seq(1).operationName(name).groupName("裁剪").unit("米")
                .qty(new BigDecimal("12.30")).unitPrice(new BigDecimal(unitPrice))
                .factor(new BigDecimal(factor)).isMustFinish(false).isStartMarker(true)
                .status("done").doneQty(new BigDecimal("3")).deleted(0).build();
    }

    private ProductionWorkLog log(String opId, String name, String worker, String qualifiedQty,
                                  String workType, LocalDate workDate) {
        return ProductionWorkLog.builder()
                .tenantId(TENANT).processingOrderId(PO_ID).operationId(opId).operationName(name)
                .workerId("w-1").workerName(worker).qty(new BigDecimal(qualifiedQty))
                .qualifiedQty(new BigDecimal(qualifiedQty)).workType(workType).workDate(workDate)
                .deleted(0).build();
    }

    /** 带**单价/系数快照**的报工（issue #4351 起：金额在报工那一刻固化，聚合只读它）。 */
    private ProductionWorkLog snapshotLog(String opId, String name, String worker, String qualifiedQty,
                                          String unitPrice, String factor, LocalDate workDate) {
        ProductionWorkLog log = log(opId, name, worker, qualifiedQty, "normal", workDate);
        log.setUnitPrice(new BigDecimal(unitPrice));
        log.setFactor(new BigDecimal(factor));
        return log;
    }

    /**
     * **新报工**形态（#4589 起）：只有单价快照、{@code factor} 留 {@code NULL}。
     *
     * <p>反向护栏（issue #4604）：系数**不得**被加回新单 —— 有单价快照时不许回落到实例的
     * {@code factor}（实例上可能仍是历史值 1.70）。</p>
     */
    private ProductionWorkLog newStyleLog(String opId, String name, String worker, String qualifiedQty,
                                          String unitPrice, LocalDate workDate) {
        ProductionWorkLog log = log(opId, name, worker, qualifiedQty, "normal", workDate);
        log.setUnitPrice(new BigDecimal(unitPrice));
        return log; // factor 保持 NULL = 新报工形态
    }

    /**
     * 带**帘种**（`position_kind`）的工序实例夹具（issue #4621）：`per_operation` 的 `position`
     * 从实例带出 —— 报工快照（`production_work_logs`）**没有部位列**，只能按 `operationId` join。
     */
    private ProcessingPositionOperation opWithPositionKind(String id, String name, String positionKind) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("布艺遮光帘A 米白").positionKind(positionKind).seq(1).operationName(name)
                .groupName("裁剪").unit("米")
                .qty(new BigDecimal("12.30")).unitPrice(new BigDecimal("0.40"))
                .factor(BigDecimal.ONE).isMustFinish(false).isStartMarker(true)
                .status("done").doneQty(new BigDecimal("3")).deleted(0).build();
    }

    // ── 工序显示名统一（issue #4621）：`per_operation` 补 `logical_name` + `position` ──
    // 口径：显示名 = 逻辑工序名（既有映射读时派生）+ 帘种；既有 `operation` 键 = 工人端快照名
    // ⇒ **一字不动**；**web 界面不得渲染该键**。分组口径不变（仍是「每个工序实例一行」）。

    @Test
    @DisplayName("#4621 per_operation 补 logical_name + position（帘种从实例带出；部位无关工序给空）")
    void perOperationAddsDisplayKeys() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                log("op-1", "精裁-布", "张三", "10", "normal", LocalDate.of(2026, 9, 18)),
                log("op-2", "外帘装袋", "张三", "5", "normal", LocalDate.of(2026, 9, 18))));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                opWithPositionKind("op-1", "精裁-布", "布帘"),
                opWithPositionKind("op-2", "外帘装袋", "布帘")));

        Map<String, Object> report = service.pieceworkSummary("2026-09", null, TENANT);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> perOperation = (List<Map<String, Object>>) report.get("per_operation");
        assertThat(perOperation)
                .as("分组口径不变：每个工序实例一行（`精裁 · 布帘` / `外帘装袋` 各一行）")
                .hasSize(2);
        assertThat(perOperation).anySatisfy(row -> assertThat(row)
                .containsEntry("operation", "精裁-布")
                .containsEntry("logical_name", "精裁")
                .containsEntry("position", "布帘"));
        assertThat(perOperation).anySatisfy(row -> assertThat(row)
                .containsEntry("operation", "外帘装袋")
                .containsEntry("logical_name", "外帘装袋")
                .containsEntry("position", null));
    }

    @Test
    @DisplayName("走查实测单可复现：精裁-布 3 米 × ¥0.40 ⇒ per_worker 金额 1.20")
    void walkthroughOrderIsReproducible() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                log("op-1", "精裁-布", "走查工人", "3", "normal", LocalDate.of(2026, 9, 18))));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(op("op-1", "精裁-布", "0.40", "1.00")));

        Map<String, Object> report = service.pieceworkSummary("2026-09", null, TENANT);

        assertThat(report.get("period")).isEqualTo("2026-09");
        assertThat((BigDecimal) report.get("total")).isEqualByComparingTo("1.20");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> perWorker = (List<Map<String, Object>>) report.get("per_worker");
        assertThat(perWorker).hasSize(1);
        assertThat(perWorker.get(0).get("worker_name")).isEqualTo("走查工人");
        assertThat((BigDecimal) perWorker.get(0).get("amount")).isEqualByComparingTo("1.20");
        assertThat((BigDecimal) perWorker.get(0).get("qty")).isEqualByComparingTo("3");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> perOperation = (List<Map<String, Object>>) report.get("per_operation");
        assertThat(perOperation.get(0).get("operation")).isEqualTo("精裁-布");
        assertThat((BigDecimal) perOperation.get(0).get("amount")).isEqualByComparingTo("1.20");
        assertThat((BigDecimal) perOperation.get(0).get("qty")).isEqualByComparingTo("3");
    }

    @Test
    @DisplayName("#4604 历史面：报工快照 factor=1.70 ⇒ 金额 = 数量 × 单价 × 1.70（用户裁定 B 不追溯）")
    void historicalSnapshotFactorStillApplies() {
        // 历史报工（「一分二」时代）：4 合格 × ¥0.40 × 快照 1.70 = ¥2.72
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                snapshotLog("op-1", "韩褶-布", "张三", "4", "0.40", "1.70", LocalDate.of(2026, 9, 18))));
        // 实例现值已不是 1.70 ⇒ 必须读**报工自己的快照**（读实例会得到 1.60，判别力在此）
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "韩褶-布", "0.40", "1.00")));

        Map<String, Object> report = service.pieceworkSummary("2026-09", null, TENANT);

        assertThat((BigDecimal) report.get("total"))
                .as("历史报工按「当时快照」的系数继续算 ⇒ 金额一字不变（issue #4604；main 上曾是 1.60）")
                .isEqualByComparingTo("2.72");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> perWorker = (List<Map<String, Object>>) report.get("per_worker");
        assertThat((BigDecimal) perWorker.get(0).get("amount")).isEqualByComparingTo("2.72");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> perOperation = (List<Map<String, Object>>) report.get("per_operation");
        assertThat((BigDecimal) perOperation.get(0).get("amount")).isEqualByComparingTo("2.72");
    }

    @Test
    @DisplayName("#4604 新报工面（反向护栏）：factor 快照为 NULL ⇒ 金额 = 数量 × 单价，不乘实例系数")
    void newReportWithoutFactorSnapshotIsNotMultiplied() {
        // #4589 起新报工只写单价快照、不写 factor
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                newStyleLog("op-1", "韩褶-布", "张三", "10", "0.40", LocalDate.of(2026, 9, 18))));
        // 实例上仍是历史快照 1.70：有单价快照时**不得**回落到实例系数
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "韩褶-布", "0.40", "1.70")));

        Map<String, Object> report = service.pieceworkSummary("2026-09", null, TENANT);

        assertThat((BigDecimal) report.get("total"))
                .as("factor 快照为 NULL ⇒ 取 1（防「系数又被加回新单」，issue #4604）")
                .isEqualByComparingTo("4.00");
    }

    @Test
    @DisplayName("口径一致性（#4205 红证判据）：同一批报工下，per-order 合计 == 报表 total")
    void summaryTotalEqualsPerOrderTotal() {
        List<ProductionWorkLog> logs = List.of(
                log("op-1", "精裁-布", "张三", "10", "normal", LocalDate.of(2026, 9, 18)),
                log("op-2", "韩褶-布", "张三", "5", "normal", LocalDate.of(2026, 9, 19)),
                log("op-1", "精裁-布", "李四", "3", "rework", LocalDate.of(2026, 9, 20)));
        List<ProcessingPositionOperation> ops = List.of(
                op("op-1", "精裁-布", "0.40", "1.00"),
                op("op-2", "韩褶-布", "0.40", "1.70"));
        when(workLogMapper.selectList(any())).thenReturn(logs);
        when(positionOperationMapper.selectList(any())).thenReturn(ops);

        Map<String, Object> perOrder = service.piecework(ORDER_ID, TENANT);
        Map<String, Object> report = service.pieceworkSummary("2026-09", null, TENANT);

        // 10×0.40×1.00 + 5×0.40×**1.70** = 4.00 + 3.40 = 7.40（#4604：报工无单价快照 ⇒ 回落到实例的
        // 单价**与系数**；返工 3 米不计件）
        assertThat((BigDecimal) perOrder.get("total")).isEqualByComparingTo("7.40");
        assertThat((BigDecimal) report.get("total")).isEqualByComparingTo("7.40");
        assertThat((BigDecimal) report.get("total"))
                .as("两套端点必须共用同一份聚合（禁止复制第二套算法）")
                .isEqualByComparingTo((BigDecimal) perOrder.get("total"));

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> perWorker = (List<Map<String, Object>>) report.get("per_worker");
        assertThat(perWorker).extracting(row -> row.get("worker_name")).containsExactly("张三");
        @SuppressWarnings("unchecked")
        Map<String, BigDecimal> perOrderWorker = (Map<String, BigDecimal>) perOrder.get("per_worker");
        assertThat((BigDecimal) perWorker.get(0).get("amount"))
                .isEqualByComparingTo(perOrderWorker.get("张三"));
    }

    @Test
    @DisplayName("实例已软删且**无快照**的报工不计价 —— 真·脏数据（issue #4351 的兜底，两处同值）")
    void softDeletedInstanceIsNotCountedInEitherEndpoint() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                log("op-gone", "精裁-布", "张三", "10", "normal", LocalDate.of(2026, 9, 18))));
        when(positionOperationMapper.selectList(any())).thenReturn(new ArrayList<>());   // 活跃实例为空

        assertThat((BigDecimal) service.piecework(ORDER_ID, TENANT).get("total")).isEqualByComparingTo("0.00");
        Map<String, Object> report = service.pieceworkSummary("2026-09", null, TENANT);
        assertThat((BigDecimal) report.get("total")).isEqualByComparingTo("0.00");
        assertThat((List<?>) report.get("per_worker")).isEmpty();
    }

    @Test
    @DisplayName("#4351 红证：重新实例化（旧实例软删）后，期间报表里同一笔报工的金额不变")
    void snapshotSurvivesReInstantiationInSummary() {
        // 报工时固化：10 合格 × ¥0.12 × 1.00 = ¥1.20
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                snapshotLog("op-1", "精裁-布", "张三", "10", "0.12", "1.00", LocalDate.of(2026, 9, 18))));
        // 重新实例化：旧实例 op-1 软删并重插新实例 op-2 ⇒ 活跃实例集里没有 op-1
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(op("op-2", "精裁-布", "0.12", "1.00")));

        Map<String, Object> report = service.pieceworkSummary("2026-09", null, TENANT);

        assertThat((BigDecimal) report.get("total"))
                .as("金额在报工那一刻固化 ⇒ 旧实例软删不得让这笔钱从期间报表里消失（issue #4351）")
                .isEqualByComparingTo("1.20");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> perOperation = (List<Map<String, Object>>) report.get("per_operation");
        assertThat(perOperation).singleElement()
                .satisfies(row -> assertThat(row.get("operation")).isEqualTo("精裁-布"));
    }

    @Test
    @DisplayName("#4351 实例缺失时工序名取报工自身的快照字段（operation_name 在报工时已落库）")
    void operationNameFallsBackToWorkLogWhenInstanceGone() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                snapshotLog("op-1", "精裁-布", "张三", "10", "0.12", "1.00", LocalDate.of(2026, 9, 18))));
        when(positionOperationMapper.selectList(any())).thenReturn(new ArrayList<>());

        Map<String, Object> report = service.pieceworkSummary("2026-09", null, TENANT);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> perOperation = (List<Map<String, Object>>) report.get("per_operation");
        assertThat(perOperation).singleElement()
                .satisfies(row -> assertThat(row.get("operation")).isEqualTo("精裁-布"));
        assertThat((BigDecimal) report.get("total")).isEqualByComparingTo("1.20");
    }

    @Test
    @DisplayName("期间边界压在 SQL（当月首末含端点）+ worker_name 可选下钻")
    void periodBoundaryAndOptionalWorkerFilter() {
        when(workLogMapper.selectList(any())).thenReturn(List.of());

        service.pieceworkSummary("2026-09", "张三", TENANT);

        ArgumentCaptor<QueryWrapper<ProductionWorkLog>> captor =
                ArgumentCaptor.forClass(QueryWrapper.class);
        verify(workLogMapper).selectList(captor.capture());
        assertThat(captor.getValue().getSqlSegment()).contains("work_date").contains("worker_name");
        assertThat(captor.getValue().getParamNameValuePairs().values())
                .as("期间边界取当月首末（含端点）")
                .contains(LocalDate.of(2026, 9, 1), LocalDate.of(2026, 9, 30));
    }

    @Test
    @DisplayName("period 缺失/非法 ⇒ 422（报表必须按期，不静默返回空报表）")
    void periodIsRequiredAndValidated() {
        assertThatThrownBy(() -> service.pieceworkSummary(null, null, TENANT))
                .isInstanceOf(BusinessException.class).hasMessageContaining("period");
        assertThatThrownBy(() -> service.pieceworkSummary("  ", null, TENANT))
                .isInstanceOf(BusinessException.class).hasMessageContaining("period");
        assertThatThrownBy(() -> service.pieceworkSummary("2026-9", null, TENANT))
                .isInstanceOf(BusinessException.class).hasMessageContaining("period");
        assertThatThrownBy(() -> service.pieceworkSummary("2026-13", null, TENANT))
                .isInstanceOf(BusinessException.class).hasMessageContaining("period");
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 下钻维度（部位 / 套）—— 真值源 §4 的下钻链：报工 → 工序实例 → 部位 → 套 → 加工单 → 订单
    // ══════════════════════════════════════════════════════════════════════════════════

    /**
     * 带**部位与套定位键**的工序实例（V69 / issue #4388：`(order_item_id, position_kind)` 是主定位键）。
     *
     * <p>下钻维度只从**工序实例**取（`position_name` / `order_item_id`），
     * **不改 `production_work_logs`**（P2b 明列「不做」；V61 快照口径已冻结）。</p>
     */
    private ProcessingPositionOperation opAt(String id, String operationName, String positionName,
                                             String orderItemId, String unitPrice) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName(positionName).orderItemId(orderItemId).positionKind("布帘")
                .seq(1).operationName(operationName).groupName("裁剪").unit("米")
                .qty(new BigDecimal("12.30")).unitPrice(new BigDecimal(unitPrice))
                .factor(BigDecimal.ONE).isMustFinish(false).isStartMarker(true)
                .status("done").doneQty(new BigDecimal("3")).deleted(0).build();
    }

    /** 带 **V92 套号快照**（`processing_position_operations.set_no`）的工序实例。 */
    private ProcessingPositionOperation opAtWithSet(String id, String operationName, String positionName,
                                                    String orderItemId, String setNo, String unitPrice) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName(positionName).orderItemId(orderItemId).positionKind("布帘").setNo(setNo)
                .seq(1).operationName(operationName).groupName("裁剪").unit("米")
                .qty(new BigDecimal("12.30")).unitPrice(new BigDecimal(unitPrice))
                .factor(BigDecimal.ONE).isMustFinish(false).isStartMarker(true)
                .status("done").doneQty(new BigDecimal("3")).deleted(0).build();
    }

    /**
     * 订单明细行 —— 樘窗组键的唯一载体 = `processing_info.craftLineId`。
     *
     * <p>组键口径与 `ProcessingOrderService.craftGroupKey` / V92 回填**同一份**：
     * `craftLineId` 优先，缺省 ⇒ 本行 `itemId`（各行自成一组）。</p>
     */
    private static OrderItem orderItem(String id, String craftLineId) {
        Map<String, Object> info = new java.util.LinkedHashMap<>();
        if (craftLineId != null) {
            info.put("craftLineId", craftLineId);
        }
        OrderItem item = new OrderItem();
        item.setId(id);
        item.setTenantId(TENANT);
        item.setOrderId(ORDER_ID);
        item.setProcessingInfo(info);
        item.setDeleted(0);
        return item;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> rowsOf(Map<String, Object> report, String key) {
        return (List<Map<String, Object>>) report.get(key);
    }

    private static BigDecimal sumAmount(List<Map<String, Object>> rows) {
        return rows.stream()
                .map(row -> (BigDecimal) row.get("amount"))
                .reduce(BigDecimal.ZERO, BigDecimal::add);
    }

    @Test
    @DisplayName("下钻：报表带 per_position / per_set 两维，且**各维合计 === 总额**（可核对判据）")
    void drillDownByPositionAndSetSumsToTotal() {
        // 两个部位（布帘 / 纱帘），两个套（行 A / 行 B）
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                snapshotLog("op-b", "精裁-布", "张三", "10", "0.40", "1.00", LocalDate.of(2026, 9, 18)),
                snapshotLog("op-s", "精裁-纱", "李四", "5", "0.40", "1.00", LocalDate.of(2026, 9, 19)),
                snapshotLog("op-b2", "韩褶-布", "张三", "4", "0.40", "1.70", LocalDate.of(2026, 9, 20))));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                opAt("op-b", "精裁-布", "布艺遮光帘A 米白", "item-A", "0.40"),
                opAt("op-s", "精裁-纱", "纱帘B 本白", "item-B", "0.40"),
                opAt("op-b2", "韩褶-布", "布艺遮光帘A 米白", "item-A", "0.40")));

        Map<String, Object> report = service.pieceworkSummary("2026-09", null, TENANT);

        // 10×0.40×1.00 + 5×0.40×1.00 + 4×0.40×**1.70** = 4.00 + 2.00 + 2.72 = 8.72
        // （#4604：逐笔按**当时快照**的系数算；第 3 笔快照 1.70）
        BigDecimal total = (BigDecimal) report.get("total");
        assertThat(total).isEqualByComparingTo("8.72");

        List<Map<String, Object>> perPosition = rowsOf(report, "per_position");
        List<Map<String, Object>> perSet = rowsOf(report, "per_set");
        assertThat(perPosition).as("部位维必须在场").isNotEmpty();
        assertThat(perSet).as("套维必须在场").isNotEmpty();

        assertThat(sumAmount(perPosition))
                .as("下钻合计必须 === 总额（否则「可核对」不成立）")
                .isEqualByComparingTo(total);
        assertThat(sumAmount(perSet))
                .as("下钻合计必须 === 总额（否则「可核对」不成立）")
                .isEqualByComparingTo(total);

        // 部位维逐值：布帘 = 4.00 + 2.72 = 6.72；纱帘 = 2.00
        assertThat(perPosition).extracting(row -> row.get("position_name"))
                .containsExactlyInAnyOrder("布艺遮光帘A 米白", "纱帘B 本白");
        BigDecimal cloth = perPosition.stream()
                .filter(row -> "布艺遮光帘A 米白".equals(row.get("position_name")))
                .map(row -> (BigDecimal) row.get("amount")).findFirst().orElseThrow();
        assertThat(cloth).isEqualByComparingTo("6.72");

        // 套维逐值：item-A = 6.72；item-B = 2.00
        // （#4725：无 `craftLineId` 的两行 ⇒ **各自成樘窗** ⇒ 套键回落本行 itemId，逐值与改前相同）
        BigDecimal setA = perSet.stream()
                .filter(row -> "item-A".equals(row.get("set_no")))
                .map(row -> (BigDecimal) row.get("amount")).findFirst().orElseThrow();
        assertThat(setA).isEqualByComparingTo("6.72");
    }

    @Test
    @DisplayName("下钻红证：实例已软删的报工归「未知部位/未知套」，**不跳过**（跳过会让合计 ≠ 总额）")
    void drillDownKeepsUnlocatableRowsInsteadOfDroppingThem() {
        // 带快照 ⇒ 可计价；但活跃实例集为空 ⇒ 拿不到部位/套
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                snapshotLog("op-gone", "精裁-布", "张三", "10", "0.12", "1.00", LocalDate.of(2026, 9, 18))));
        when(positionOperationMapper.selectList(any())).thenReturn(new ArrayList<>());

        Map<String, Object> report = service.pieceworkSummary("2026-09", null, TENANT);

        BigDecimal total = (BigDecimal) report.get("total");
        assertThat(total).isEqualByComparingTo("1.20");
        assertThat(rowsOf(report, "per_position")).singleElement()
                .satisfies(row -> {
                    assertThat(row.get("position_name")).isEqualTo("未知部位");
                    assertThat((BigDecimal) row.get("amount")).isEqualByComparingTo("1.20");
                });
        assertThat(rowsOf(report, "per_set")).singleElement()
                .satisfies(row -> assertThat(row.get("set_no")).isEqualTo("未知套"));
        assertThat(sumAmount(rowsOf(report, "per_position")))
                .as("定位不到的报工也必须计入下钻合计 —— 否则合计 < 总额")
                .isEqualByComparingTo(total);
    }

    @Test
    @DisplayName("per-order 端点同样带下钻两维（与期间报表共用同一份聚合 ⇒ 不会两套口径）")
    void perOrderEndpointCarriesDrillDown() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                snapshotLog("op-b", "精裁-布", "张三", "10", "0.40", "1.00", LocalDate.of(2026, 9, 18))));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                opAt("op-b", "精裁-布", "布艺遮光帘A 米白", "item-A", "0.40")));

        Map<String, Object> perOrder = service.piecework(ORDER_ID, TENANT);

        assertThat((BigDecimal) perOrder.get("total")).isEqualByComparingTo("4.00");
        assertThat(rowsOf(perOrder, "per_position")).singleElement()
                .satisfies(row -> assertThat(row.get("position_name")).isEqualTo("布艺遮光帘A 米白"));
        assertThat(rowsOf(perOrder, "per_set")).singleElement()
                .satisfies(row -> assertThat(row.get("set_no")).isEqualTo("item-A"));
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // #4725（用户裁定「一樘窗 = 一套」）：套维度 = **樘窗组**，不是订单行
    // ══════════════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("#4725 一樘窗（布帘 + 纱帘 + 帘头，同 craftLineId）= **1 套**（改前 = 3 行「套」）")
    void oneWindowWithAllPartsIsExactlyOneSet() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                snapshotLog("op-1", "精裁-布", "张三", "10", "0.40", "1.00", LocalDate.of(2026, 9, 18)),
                snapshotLog("op-2", "精裁-纱", "张三", "5", "0.40", "1.00", LocalDate.of(2026, 9, 18)),
                snapshotLog("op-3", "精裁-帘头", "张三", "2", "0.40", "1.00", LocalDate.of(2026, 9, 18))));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                opAt("op-1", "精裁-布", "布艺遮光帘A 米白", "item-1", "0.40"),
                opAt("op-2", "精裁-纱", "纱帘B 本白", "item-2", "0.40"),
                opAt("op-3", "精裁-帘头", "帘头C 米白", "item-3", "0.40")));
        // 三条明细行同 `craftLineId = win-1` ⇒ **一个樘窗**（V92 回填同口径）
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                orderItem("item-1", "win-1"), orderItem("item-2", "win-1"), orderItem("item-3", "win-1")));

        Map<String, Object> report = service.pieceworkSummary("2026-09", null, TENANT);

        // 红证（改前）：套维 = 3 行（item-1 / item-2 / item-3）⇒ 下面两条断言必红
        assertThat(rowsOf(report, "per_set"))
                .as("一樘窗 = 一套 ⇒ 套维只能有 1 行（旧口径 = 3 行）").singleElement()
                .satisfies(row -> assertThat(row.get("set_no")).isEqualTo("win-1"));
        assertThat(sumAmount(rowsOf(report, "per_set")))
                .as("套维合计仍必须 === 总额（口径变了，可核对性不变）")
                .isEqualByComparingTo((BigDecimal) report.get("total"));
    }

    @Test
    @DisplayName("#4725 两樘窗（各含布 + 纱）= **2 套**（不把不同樘窗并成一套）")
    void twoWindowsAreTwoSets() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                snapshotLog("op-1", "精裁-布", "张三", "10", "0.40", "1.00", LocalDate.of(2026, 9, 18)),
                snapshotLog("op-2", "精裁-纱", "张三", "5", "0.40", "1.00", LocalDate.of(2026, 9, 18))));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                opAt("op-1", "精裁-布", "布艺遮光帘A 米白", "item-1", "0.40"),
                opAt("op-2", "精裁-纱", "纱帘B 本白", "item-2", "0.40")));
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                orderItem("item-1", "win-1"), orderItem("item-2", "win-2")));

        Map<String, Object> report = service.pieceworkSummary("2026-09", null, TENANT);

        assertThat(rowsOf(report, "per_set")).extracting(row -> row.get("set_no"))
                .containsExactlyInAnyOrder("win-1", "win-2");
    }

    @Test
    @DisplayName("#4725 V92 套号优先：实例带 `set_no` ⇒ 套维显示**落库套号**（不是组键）")
    void storedSetNoWinsOverWindowGroupKey() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                snapshotLog("op-1", "精裁-布", "张三", "10", "0.40", "1.00", LocalDate.of(2026, 9, 18))));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                opAtWithSet("op-1", "精裁-布", "布艺遮光帘A 米白", "item-1",
                        "JG-20260918-6914-001", "0.40")));

        Map<String, Object> report = service.pieceworkSummary("2026-09", null, TENANT);

        assertThat(rowsOf(report, "per_set")).singleElement()
                .satisfies(row -> assertThat(row.get("set_no")).isEqualTo("JG-20260918-6914-001"));
    }

    @Test
    @DisplayName("空态也带齐下钻键（键的在场性恒定 ⇒ 前端不必为「有没有这个键」写分支）")
    void emptyPieceworkCarriesDrillDownKeys() {
        when(workLogMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> report = service.pieceworkSummary("2026-09", null, TENANT);

        assertThat(report).containsKeys("per_position", "per_set");
        assertThat(rowsOf(report, "per_position")).isEmpty();
        assertThat(rowsOf(report, "per_set")).isEmpty();
    }
}
