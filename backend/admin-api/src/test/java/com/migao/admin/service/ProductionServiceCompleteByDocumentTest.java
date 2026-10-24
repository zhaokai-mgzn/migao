// case_ids: PG-083
package com.migao.admin.service;

import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import com.migao.admin.worker.WorkerIdentity;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 单据联动完成工序的两条口径（issue #7165）。
 *
 * <p>对应用例：<b>PG-083</b>。</p>
 *
 * <p>🔴 用户 2026-10-17 裁定：「工人端记给发货工人；商家/生产端发货不计件」⇒</p>
 * <ul>
 *   <li>有工人身份 ⇒ 走既有报工（写 {@code production_work_logs}，计件）；</li>
 *   <li>无身份 ⇒ **不写报工**（不计件），只 CAS 推进 + 完工时刻 + 加工单完工判定。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("单据联动完成工序：工人计件 / 商家不计件")
class ProductionServiceCompleteByDocumentTest {

    private static final Long TENANT = 7L;

    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private ProductionWorkLogMapper workLogMapper;

    @InjectMocks
    private ProductionService productionService;

    private final Order order = Order.builder().id("o-1").tenantId(TENANT).orderNo("DD-1").build();
    private final ProcessingOrder po = ProcessingOrder.builder()
            .id("po-1").tenantId(TENANT).processingOrderNo("JG-1").build();

    private static ProcessingPositionOperation op() {
        return ProcessingPositionOperation.builder()
                .id("op-1").tenantId(TENANT).processingOrderId("po-1")
                .operationName("外帘发货").qty(new BigDecimal("2"))
                .doneQty(BigDecimal.ZERO).status("pending").unitPrice(new BigDecimal("1.00")).deleted(0)
                .build();
    }

    private void allDone() {
        ProcessingPositionOperation done = op();
        done.setDoneQty(new BigDecimal("2"));
        done.setStatus("done");
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(done));
    }

    @Test
    @DisplayName("🔴 商家/生产端（identity = null）⇒ 推进工序但**不写报工**（不计件）")
    void merchantPathAdvancesWithoutPiecework() {
        ProcessingPositionOperation op = op();
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(
                eq("op-1"), eq(TENANT), any(), anyString(), any(), any(OffsetDateTime.class))).thenReturn(1);
        allDone();

        int completed = productionService.completeByDocument(order, po, op, null, TENANT);

        assertThat(completed).isEqualTo(1);
        verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
        verify(processingOrderMapper).markCompletedIfActive(eq("po-1"), eq(TENANT), any(OffsetDateTime.class));
    }

    @Test
    @DisplayName("🔴 工人端（identity 非空）⇒ 走既有报工口径，写一行报工（计件记给该工人）")
    void workerPathWritesPieceworkLog() {
        ProcessingPositionOperation op = op();
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(
                eq("op-1"), eq(TENANT), any(), anyString(), any(), any(OffsetDateTime.class))).thenReturn(1);
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(op)); // 尚有其它未完工序
        WorkerIdentity worker = new WorkerIdentity(
                "worker-1", "张师傅", WorkerIdentity.SOURCE_SERVER_SESSION, "ws-1");

        int completed = productionService.completeByDocument(order, po, op, worker, TENANT);

        assertThat(completed).isEqualTo(1);
        verify(workLogMapper).insert(any(ProductionWorkLog.class));
    }

    @Test
    @DisplayName("已做满（剩余 ≤ 0）⇒ 0，且不动任何写面（幂等）")
    void alreadyFullIsNoOp() {
        ProcessingPositionOperation op = op();
        op.setDoneQty(new BigDecimal("2"));

        assertThat(productionService.completeByDocument(order, po, op, null, TENANT)).isZero();
        verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
        verify(positionOperationMapper, never()).advanceDoneQtyIfUnchanged(
                anyString(), eq(TENANT), any(), anyString(), any(), any(OffsetDateTime.class));
    }
}
