// case_ids: PG-086
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import com.migao.admin.worker.WorkerIdentity;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 「质检」工序**没有报工动作**（issue #7186）。
 *
 * <p>用户 2026-10-18 逐字：「质检员不需要报工这个动作，只需要有一个质检动作，完成判定后自动报工，
 * 然后自动生成质检流水」。</p>
 *
 * <p>🔴 本文件钉两条（每条能单独变红）：</p>
 * <ol>
 *   <li><b>质检工序走逐道报工 ⇒ 422 具名拒绝，且零写入</b>（不落 {@code production_work_logs}、
 *       不 CAS 推进 {@code done_qty}）—— 摘掉 {@code DocumentOperationLinkage#rejectManualReport}
 *       的调用 ⇒ 本断言红（报工照常成功）；</li>
 *   <li><b>对照：非质检工序照常成功</b> —— 守卫按工序名匹配，**不得**误伤其它工序
 *       （把匹配写宽成「包含质检」/「所有工序」⇒ 本断言红）。</li>
 * </ol>
 *
 * <p>扫码闭环那条入口（{@code ProductionScanCompleteService}）的同款判据在
 * {@code ProductionScanCompleteServiceTest#qualityOperationIsNotReportable}（同一份
 * {@code rejectManualReport}，不复制第二套文案）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("质检工序没有报工动作：判定即报工（issue #7186）")
class ProductionReportQualityGuardTest {

    private static final Long TENANT = 7L;
    private static final String ORDER_ID = "order-1";
    private static final String PO_ID = "po-1";
    private static final String OP_ID = "op-1";
    private static final String ITEM_ID = "oi-1";
    private static final WorkerIdentity WORKER =
            new WorkerIdentity("w-1", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, "sess-1");

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

    private ProductionService productionService;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        productionService = new ProductionService(processingOrderMapper, positionOperationMapper,
                workLogMapper, orderMapper, orderItemMapper, clientRequestIdService);
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(true);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(
                Order.builder().id(ORDER_ID).tenantId(TENANT).orderNo("DD-1").build());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(
                ProcessingOrder.builder().id(PO_ID).tenantId(TENANT)
                        .processingOrderNo("JG-1").status("issued").build());
        when(workLogMapper.insert(any(ProductionWorkLog.class))).thenReturn(1);
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(
                any(), any(), any(), any(), any(), any())).thenReturn(1);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private static ProcessingPositionOperation op(String operationName) {
        return ProcessingPositionOperation.builder()
                .id(OP_ID).tenantId(TENANT).processingOrderId(PO_ID).orderItemId(ITEM_ID)
                .operationName(operationName)
                .qty(new BigDecimal("1")).doneQty(BigDecimal.ZERO).status("pending")
                .unitPrice(new BigDecimal("2.00")).deleted(0)
                .build();
    }

    private static Map<String, Object> body() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("qty", new BigDecimal("1"));
        return body;
    }

    @Test
    @DisplayName("🔴 质检工序走报工 ⇒ 422 具名拒绝（指向质检判定），且零写入")
    void reportingQualityOperationIsRejected() {
        when(positionOperationMapper.selectById(OP_ID)).thenReturn(op("质检"));

        assertThatThrownBy(() -> productionService.report(
                ORDER_ID, OP_ID, body(), TENANT, "key-1", WORKER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("质检")
                .hasMessageContaining("判定")
                .hasFieldOrPropertyWithValue("code", "VALIDATION_ERROR")
                .hasFieldOrPropertyWithValue("httpStatus", 422);

        // 零写入：既不落报工明细（计件凭证），也不推进工序
        verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
        verify(positionOperationMapper, never()).advanceDoneQtyIfUnchanged(
                any(), any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("对照：非质检工序报工照常成功（守卫不得误伤）")
    void reportingNormalOperationStillWorks() {
        ProcessingPositionOperation target = op("精裁-布");
        when(positionOperationMapper.selectById(OP_ID)).thenReturn(target);
        // 完工判定读的是「本单全部活跃工序」：给一条已完成的行 ⇒ 加工单完工判定照常走
        ProcessingPositionOperation done = op("精裁-布");
        done.setDoneQty(new BigDecimal("1"));
        done.setStatus("done");
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(done));

        Map<String, Object> result = productionService.report(
                ORDER_ID, OP_ID, body(), TENANT, "key-1", WORKER);

        assertThat(result.get("status")).isEqualTo("done");
        assertThat(result.get("done_qty")).isEqualTo(new BigDecimal("1"));
        verify(workLogMapper).insert(any(ProductionWorkLog.class));
    }
}
