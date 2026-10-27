// case_ids: PG-098, PG-099
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.entity.ReworkOrder;
import com.migao.admin.dto.ReworkOrderView;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import com.migao.admin.mapper.ReworkOrderMapper;
import com.migao.admin.worker.WorkerIdentity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 工人报返工（issue #7860）—— 只钉**账实**：改记的是哪一笔、回退多少、返工单怎么落。
 *
 * <p>用户 2026-10-26 逐字：「质检不能绑定死打包工序，需要允许任一工序工人报返工」
 * 「报返工的那个工序不能计件的，只报返工，生成返工单」；
 * 追问「刚自动记的那一笔怎么处理」⇒ 选了「把刚自动记的那一笔改记为返工（回退进度与计件）」。</p>
 *
 * <p>🔴 本文件钉六条（每条能单独变红）：</p>
 * <ol>
 *   <li>改记 + 回退的参数**逐值**正确（expectedDone / 新 done_qty / 新 status）—— 回退量错 = 工资与进度双错；</li>
 *   <li>没有可改记的 {@code normal} 报工 ⇒ 422 且**零写入**（不回落退、不开单）；</li>
 *   <li>原因必填 ⇒ 缺原因 422 且不进任何 mapper；</li>
 *   <li>CAS 落空（并发）⇒ 409 且不开返工单（不留半截账）；</li>
 *   <li>加工单已 {@code completed} ⇒ 重开为 {@code in_processing}（否则「完工单里工序没做满」）；</li>
 *   <li>幂等键重放 ⇒ 不重复改记、回放首次结果。</li>
 * </ol>
 */
@DisplayName("工人报返工：改记该笔 + 回退进度 + 生成返工单（#7860）")
class ProductionReworkServiceTest {

    private static final Long TENANT = 20L;
    private static final String SESSION = "ws-1";
    private static final WorkerIdentity ZHANG =
            new WorkerIdentity("worker-zhang", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, SESSION);

    private ProductionScanService scanService;
    private ProductionService productionService;
    private WorkerAdminService workerAdminService;
    private ProductionWorkLogMapper workLogMapper;
    private ProcessingPositionOperationMapper positionOperationMapper;
    private ProcessingOrderMapper processingOrderMapper;
    private ReworkOrderMapper reworkOrderMapper;
    private OrderMapper orderMapper;
    private ReworkOrderService reworkOrderService;
    private ClientRequestIdService clientRequestIdService;
    private ProductionReworkService service;

    @BeforeEach
    void setUp() {
        // MyBatis-Plus 的 LambdaQueryWrapper 需要实体元数据缓存（否则 `can not find lambda cache`）
        com.baomidou.mybatisplus.core.MybatisConfiguration configuration =
                new com.baomidou.mybatisplus.core.MybatisConfiguration();
        for (Class<?> entity : List.of(ProductionWorkLog.class, ProcessingPositionOperation.class,
                ProcessingOrder.class, Order.class, ReworkOrder.class)) {
            com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(
                    new org.apache.ibatis.builder.MapperBuilderAssistant(configuration, ""), entity);
        }
        scanService = Mockito.mock(ProductionScanService.class);
        productionService = Mockito.mock(ProductionService.class);
        workerAdminService = Mockito.mock(WorkerAdminService.class);
        workLogMapper = Mockito.mock(ProductionWorkLogMapper.class);
        positionOperationMapper = Mockito.mock(ProcessingPositionOperationMapper.class);
        processingOrderMapper = Mockito.mock(ProcessingOrderMapper.class);
        reworkOrderMapper = Mockito.mock(ReworkOrderMapper.class);
        orderMapper = Mockito.mock(OrderMapper.class);
        reworkOrderService = Mockito.mock(ReworkOrderService.class);
        clientRequestIdService = Mockito.mock(ClientRequestIdService.class);
        service = new ProductionReworkService(scanService, productionService, workerAdminService,
                workLogMapper, positionOperationMapper, processingOrderMapper, reworkOrderMapper,
                orderMapper, reworkOrderService, clientRequestIdService);

        when(clientRequestIdService.claim(anyLong(), any(), anyString())).thenReturn(true);
        when(workerAdminService.findOwnedWorker(anyString())).thenReturn(null);
        when(productionService.resolveOrder(anyString(), anyLong())).thenReturn(order());
        when(productionService.requireActiveProcessingOrder(any(), anyLong())).thenReturn(processingOrder("in_processing"));
        when(productionService.requireActiveOperation(anyString(), anyString(), anyLong()))
                .thenReturn(operation(new BigDecimal("10"), new BigDecimal("6"), "done"));
        when(scanService.resolve(anyString(), any(), any(), any(), anyLong(), any()))
                .thenReturn(scanView("op-1"));
        when(workLogMapper.selectList(any())).thenReturn(List.of(normalLog(new BigDecimal("4"))));
        when(positionOperationMapper.revertDoneQtyIfUnchanged(anyString(), anyLong(), any(), any(), any(), any(), any()))
                .thenReturn(1);
        when(workLogMapper.update(any(), any())).thenReturn(1);
        when(processingOrderMapper.reopenCompletedIfAny(anyString(), anyLong(), any())).thenReturn(1);
        when(reworkOrderService.createWorkerRework(anyLong(), any(), any(), any(), any(), any(), any(), any(), any(), any(),
                any(), any(), any(), any()))
                .thenReturn(ReworkOrderView.builder().reworkNo("RG202610260001")
                        .orderItemId("item-1").setId("set-1").setNo("JG-20261026-0001-001").positionName("布帘")
                        .build());
    }

    // ── 夹具 ────────────────────────────────────────────────────────────────
    private static Order order() {
        Order order = new Order();
        order.setId("o-1");
        order.setOrderNo("SO-20261026-0001");
        return order;
    }

    private static ProcessingOrder processingOrder(String status) {
        return ProcessingOrder.builder().id("po-1").tenantId(TENANT).orderId("o-1")
                .processingOrderNo("JG-20261026-0001").status(status).build();
    }

    private static ProcessingPositionOperation operation(BigDecimal qty, BigDecimal doneQty, String status) {
        return ProcessingPositionOperation.builder().id("op-1").processingOrderId("po-1")
                .operationName("车缝").qty(qty).doneQty(doneQty).status(status)
                // 件键（issue #7945）：套号 × 部位 = 一张水洗唛码
                .orderItemId("item-1").setId("set-1").setNo("JG-20261026-0001-001").positionName("布帘")
                .build();
    }

    private static ProductionWorkLog normalLog(BigDecimal qualifiedQty) {
        return ProductionWorkLog.builder().id("log-1").tenantId(TENANT).processingOrderId("po-1")
                .operationId("op-1").operationName("车缝").workerId("worker-zhang").workerName("张三")
                .qty(qualifiedQty).qualifiedQty(qualifiedQty).workType("normal")
                .createdAt(OffsetDateTime.parse("2026-10-26T10:00:00+08:00")).deleted(0).build();
    }

    private static Map<String, Object> scanView(String operationId) {
        Map<String, Object> op = new LinkedHashMap<>();
        op.put("operation_id", operationId);
        Map<String, Object> scan = new LinkedHashMap<>();
        scan.put("granularity", "set_position");
        scan.put("order_id", "o-1");
        scan.put("operation", op);
        return scan;
    }

    private static Map<String, Object> body(String reason) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("token", "tk-1");
        body.put("reason", reason);
        return body;
    }

    // ── 判据 ────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("① 改记 + 回退逐值正确：done 6→2、状态回 pending、返工单落 source=worker")
    void amendsAndRevertsExactly() {
        Map<String, Object> result = service.report(body("布面污渍"), TENANT, null, ZHANG);

        ArgumentCaptor<BigDecimal> expectedDone = ArgumentCaptor.forClass(BigDecimal.class);
        ArgumentCaptor<BigDecimal> newDone = ArgumentCaptor.forClass(BigDecimal.class);
        ArgumentCaptor<String> newStatus = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> expectedStatus = ArgumentCaptor.forClass(String.class);
        verify(positionOperationMapper).revertDoneQtyIfUnchanged(eq("op-1"), eq(TENANT),
                expectedDone.capture(), expectedStatus.capture(), newDone.capture(), newStatus.capture(), any());
        // 旧值 = 读到的 6 / done；回退量 = 该笔合格数 4 ⇒ 2，且 2 < 应做 10 ⇒ pending
        assertThat(expectedDone.getValue()).isEqualByComparingTo("6");
        assertThat(expectedStatus.getValue()).isEqualTo("done");
        assertThat(newDone.getValue()).isEqualByComparingTo("2");
        assertThat(newStatus.getValue()).isEqualTo("pending");

        // 报工明细改记为返工（CAS 只认还处在 normal 的那一笔）
        verify(workLogMapper).update(isNull(), any());
        // 返工单：工序 / 数量 / 原因 / 报工人 / 被改记的报工行 + **件键**（issue #7945）全部来自服务端
        verify(reworkOrderService).createWorkerRework(eq(TENANT), eq("o-1"), eq("po-1"), eq("op-1"),
                eq("车缝"), any(), eq("布面污渍"), eq("worker-zhang"), eq("张三"), eq("log-1"),
                eq("item-1"), eq("set-1"), eq("JG-20261026-0001-001"), eq("布帘"));

        assertThat(result).containsEntry("rework_no", "RG202610260001")
                .containsEntry("operation_name", "车缝")
                .containsEntry("status", "pending")
                .containsEntry("order_completed", false)
                .containsEntry("amended_work_log_id", "log-1")
                // 回执带上件键：界面据此确认「返的是哪一件」
                .containsEntry("order_item_id", "item-1")
                .containsEntry("set_no", "JG-20261026-0001-001")
                .containsEntry("position_name", "布帘");
        assertThat((BigDecimal) result.get("done_qty")).isEqualByComparingTo("2");
    }

    @Test
    @DisplayName("② 没有可改记的「正常」报工 ⇒ 422 且零写入（不回退、不开单）")
    void withoutNormalReportRejects() {
        when(workLogMapper.selectList(any())).thenReturn(List.of());

        assertThatThrownBy(() -> service.report(body("尺寸偏差"), TENANT, null, ZHANG))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("还没有可改记的报工");

        verify(positionOperationMapper, never())
                .revertDoneQtyIfUnchanged(anyString(), anyLong(), any(), any(), any(), any(), any());
        verify(workLogMapper, never()).update(any(), any());
        verifyNoInteractions(reworkOrderService);
    }

    @Test
    @DisplayName("③ 原因必填 ⇒ 缺原因 422 且不进任何 mapper")
    void reasonIsRequired() {
        assertThatThrownBy(() -> service.report(body("  "), TENANT, null, ZHANG))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("必须写明原因");

        verifyNoInteractions(scanService);
        verifyNoInteractions(positionOperationMapper);
        verifyNoInteractions(reworkOrderService);
    }

    @Test
    @DisplayName("④ CAS 落空（进度刚被别人改过）⇒ 409 且不开返工单（不留半截账）")
    void lostCasRejects() {
        when(positionOperationMapper.revertDoneQtyIfUnchanged(anyString(), anyLong(), any(), any(), any(), any(), any()))
                .thenReturn(0);

        assertThatThrownBy(() -> service.report(body("布面污渍"), TENANT, null, ZHANG))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("刚被另一次提交改过");
        verify(workLogMapper, never()).update(any(), any());
        verifyNoInteractions(reworkOrderService);
    }

    @Test
    @DisplayName("⑤ 加工单已 completed ⇒ 重开为 in_processing（同一事务里的补偿）")
    void completedProcessingOrderIsReopened() {
        when(productionService.requireActiveProcessingOrder(any(), anyLong()))
                .thenReturn(processingOrder("completed"));

        service.report(body("缝线开裂"), TENANT, null, ZHANG);

        verify(processingOrderMapper).reopenCompletedIfAny(eq("po-1"), eq(TENANT), any());
    }

    @Test
    @DisplayName("⑥ 幂等键重放 ⇒ 不重复改记，回放首次结果")
    void replayDoesNotAmendTwice() {
        when(clientRequestIdService.claim(anyLong(), any(), anyString())).thenReturn(false);
        when(productionService.replayFirstResult(eq(TENANT), eq("k-1")))
                .thenReturn(Map.of("rework_no", "RG-first"));

        Map<String, Object> result = service.report(body("布面污渍"), TENANT, "k-1", ZHANG);

        assertThat(result).containsEntry("rework_no", "RG-first");
        verifyNoInteractions(scanService);
        verifyNoInteractions(reworkOrderService);
    }

    @Test
    @DisplayName("⑦ 返工列表：按加工单聚合笔数/数量/工序，原因取最新一张车间返工单")
    void reworkOrdersAggregatesPerProcessingOrder() {
        ProductionWorkLog first = normalLog(new BigDecimal("2"));
        ProductionWorkLog second = ProductionWorkLog.builder().id("log-2").tenantId(TENANT)
                .processingOrderId("po-1").operationId("op-2").operationName("熨烫").workerId("worker-li")
                .qty(new BigDecimal("3")).workType("rework")
                .createdAt(OffsetDateTime.parse("2026-10-26T09:00:00+08:00")).deleted(0).build();
        when(workLogMapper.selectList(any())).thenReturn(List.of(first, second));
        when(processingOrderMapper.selectById("po-1")).thenReturn(processingOrder("in_processing"));
        when(orderMapper.selectById("o-1")).thenReturn(order());
        when(reworkOrderMapper.selectList(any())).thenReturn(List.of(ReworkOrder.builder()
                .id("rw-1").tenantId(TENANT).processingOrderId("po-1")
                .source(ReworkOrderService.SOURCE_WORKER).reason("布面污渍").build()));

        @SuppressWarnings("unchecked")
        Map<String, Object> data = service.reworkOrders(TENANT);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rows = (List<Map<String, Object>>) data.get("orders");

        assertThat(rows).hasSize(1);
        Map<String, Object> row = rows.get(0);
        assertThat(row).containsEntry("processing_order_no", "JG-20261026-0001")
                .containsEntry("order_no", "SO-20261026-0001")
                .containsEntry("rework_count", 2)
                .containsEntry("latest_reason", "布面污渍");
        assertThat((BigDecimal) row.get("rework_qty")).isEqualByComparingTo("5");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> operations = (List<Map<String, Object>>) row.get("operations");
        assertThat(operations).extracting(o -> o.get("operation_name")).containsExactly("车缝", "熨烫");
    }
}
