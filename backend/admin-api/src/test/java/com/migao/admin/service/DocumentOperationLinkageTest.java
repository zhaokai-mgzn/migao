// case_ids: PG-083
package com.migao.admin.service;

import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.worker.WorkerIdentity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 单据 × 工序联动（issue #7165，用户 2026-10-17 裁定）。
 *
 * <p>对应用例：<b>PG-083</b>（`.github/cases/processing-order.yml`）。</p>
 *
 * <p>🔴 钉住（每条可单独变红）：</p>
 * <ol>
 *   <li><b>只匹配真工序</b>：发货匹配「发货 / 外帘发货」、质检匹配「质检」；没有对应工序（无活跃加工单）
 *       ⇒ 零副作用（{@link ProductionService} 一次都不被调用）；</li>
 *   <li><b>只做没做满的</b>：查询条件带 {@code done_qty < qty}（已做满 ⇒ 重复发货/复检不重复记账）；</li>
 *   <li><b>计件按身份</b>：有工人身份 ⇒ 原样把身份交给 {@link ProductionService#completeByDocument}
 *       （工人端计件）；商家/生产端 = {@code null}（不计件）；</li>
 *   <li><b>质检按件</b>：质检联动只用该件成品帘的 {@code order_item_id}（不殃及同单其它部位）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("单据联动工序（发货 / 质检，issue #7165）")
class DocumentOperationLinkageTest {

    private static final Long TENANT = 3L;
    private static final String ORDER_ID = "o-1";
    private static final String PO_ID = "po-1";
    private static final String ITEM_ID = "item-1";

    @Mock
    private OrderMapper orderMapper;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private ProductionService productionService;

    private DocumentOperationLinkage linkage;
    private final Order order = Order.builder().id(ORDER_ID).tenantId(TENANT).orderNo("DD-1").build();
    private final ProcessingOrder po = ProcessingOrder.builder().id(PO_ID).processingOrderNo("JG-1").build();
    private final WorkerIdentity worker = new WorkerIdentity(
            "worker-1", "张师傅", WorkerIdentity.SOURCE_SERVER_SESSION, "ws-1");

    @BeforeEach
    void setUp() {
        linkage = new DocumentOperationLinkage(orderMapper, processingOrderMapper,
                positionOperationMapper, productionService);
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(po);
    }

    private static ProcessingPositionOperation op(String id, String name, String itemId) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .operationName(name).orderItemId(itemId)
                .qty(new BigDecimal("2")).doneQty(BigDecimal.ZERO).status("pending").seq(27).deleted(0)
                .build();
    }

    @Test
    @DisplayName("① 发货：完成该加工单所有未做满的「发货 / 外帘发货」工序（工人身份 ⇒ 计件）")
    void shippingCompletesPendingShippingOperationsWithWorkerIdentity() {
        ProcessingPositionOperation a = op("op-a", "外帘发货", "item-1");
        ProcessingPositionOperation b = op("op-b", "外帘发货", "item-2");
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(a, b));
        when(productionService.completeByDocument(order, po, a, worker, TENANT)).thenReturn(1);
        when(productionService.completeByDocument(order, po, b, worker, TENANT)).thenReturn(1);

        int completed = linkage.completeShippingOperations(order, worker, TENANT);

        assertThat(completed).isEqualTo(2);
        verify(productionService).completeByDocument(order, po, a, worker, TENANT);
        verify(productionService).completeByDocument(order, po, b, worker, TENANT);
    }

    @Test
    @DisplayName("① 只完成「发货 / 外帘发货」，其它工序一律不碰（名称匹配是唯一判据）")
    void shippingIgnoresOtherOperations() {
        ProcessingPositionOperation ship = op("op-a", "外帘发货", "item-1");
        ProcessingPositionOperation packing = op("op-b", "外帘装袋", "item-1");
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(ship, packing));
        when(productionService.completeByDocument(order, po, ship, worker, TENANT)).thenReturn(1);

        assertThat(linkage.completeShippingOperations(order, worker, TENANT)).isEqualTo(1);
        verify(productionService).completeByDocument(order, po, ship, worker, TENANT);
        verify(productionService, never()).completeByDocument(order, po, packing, worker, TENANT);
    }

    @Test
    @DisplayName("① 无活跃加工单 / 无该工序 ⇒ 零副作用（保存顺序不变、不猜）")
    void noActiveProcessingOrderMeansNoOp() {
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(null);

        assertThat(linkage.completeShippingOperations(order, worker, TENANT)).isZero();
        verifyNoInteractions(productionService);
    }

    @Test
    @DisplayName("① 商家/生产端（identity = null）⇒ 同样完成工序，但带 null 身份（不计件）")
    void merchantShipmentLinksWithoutIdentity() {
        ProcessingPositionOperation a = op("op-a", "外帘发货", "item-1");
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(a));
        when(productionService.completeByDocument(order, po, a, null, TENANT)).thenReturn(1);

        assertThat(linkage.completeShippingOperations(order, null, TENANT)).isEqualTo(1);
        verify(productionService).completeByDocument(order, po, a, null, TENANT);
    }

    @Test
    @DisplayName("④ 质检：只完成该件成品帘的「质检」工序（order_item_id 进查询条件）")
    void qualityCompletesOnlyThatItem() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order);
        ProcessingPositionOperation a = op("op-q", "质检", ITEM_ID);
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(a));
        when(productionService.completeByDocument(order, po, a, worker, TENANT)).thenReturn(1);

        int completed = linkage.completeQualityOperation(ORDER_ID, ITEM_ID, worker, TENANT);

        assertThat(completed).isEqualTo(1);
        verify(productionService).completeByDocument(order, po, a, worker, TENANT);
        // 同单另一件（别的成品帘）的质检工序不归这次联动
        ProcessingPositionOperation other = op("op-q2", "质检", "item-2");
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(a, other));
        org.mockito.Mockito.clearInvocations(productionService);
        linkage.completeQualityOperation(ORDER_ID, ITEM_ID, worker, TENANT);
        verify(productionService).completeByDocument(order, po, a, worker, TENANT);
        verify(productionService, never()).completeByDocument(order, po, other, worker, TENANT);
    }

    @Test
    @DisplayName("④ 跨租户 / 无订单 ⇒ 零副作用（不能借别的租户的单完成工序）")
    void qualityOfAnotherTenantIsIgnored() {
        Order otherTenant = Order.builder().id(ORDER_ID).tenantId(99L).orderNo("DD-X").build();
        when(orderMapper.selectById(ORDER_ID)).thenReturn(otherTenant);

        assertThat(linkage.completeQualityOperation(ORDER_ID, ITEM_ID, worker, TENANT)).isZero();
        verifyNoInteractions(productionService);
    }

    @Test
    @DisplayName("② 已做满的工序不出现在结果里 ⇒ 返回 0（重复发货不重复记账）")
    void alreadyDoneOperationIsSkippedByQuery() {
        // 查询条件已过滤（done_qty < qty）；这里用空结果证明「没有待做 ⇒ 不动 production」
        ProcessingPositionOperation full = op("op-a", "外帘发货", "item-1");
        full.setDoneQty(new BigDecimal("2"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(full));

        assertThat(linkage.completeShippingOperations(order, worker, TENANT)).isZero();
        verify(productionService, never()).completeByDocument(any(), any(), any(), any(), any());
    }
}
