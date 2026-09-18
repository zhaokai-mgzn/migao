package com.migao.admin.service;

// case_ids: PG-021

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
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
    private ClientRequestIdService clientRequestIdService;

    private ProductionService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        service = new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper,
                orderMapper, clientRequestIdService);
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

        // 10×0.40×1.00 + 5×0.40×1.70 = 4.00 + 3.40 = 7.40；返工 3 米不计件
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
    @DisplayName("实例已软删（不在活跃集）的报工不计价 —— 与 per-order 同一判据，两处同值")
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
}
