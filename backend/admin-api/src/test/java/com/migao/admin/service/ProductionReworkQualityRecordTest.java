// case_ids: PG-099
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.entity.QualityCheck;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import com.migao.admin.mapper.QualityCheckMapper;
import com.migao.admin.worker.WorkerIdentity;
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
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 返工报工 = 记录一次质检（issue #7919，用户 2026-10-27 裁定）。
 *
 * <p>用户逐字：「报工页面的质检和返工要合并成一个功能，现在是两个独立的，移除质检，保留返工，
 * 当前系统返工=质检」；同轮追问裁定：删掉质检区块后**返工报工要继续产生质检记录**
 * （{@code quality_inspections}），否则质检单 / 质量成本报表断档。</p>
 *
 * <p>🔴 本文件钉五条（每条都能单独变红）：</p>
 * <ol>
 *   <li><b>返工报工 ⇒ 恰好 1 行质检记录</b>，判定 / 检验人 / 原因 / 时刻 / 成品帘逐项断言；</li>
 *   <li><b>同幂等键重放 ⇒ 仍是 1 行</b>（回放路径根本到不了落库点，不新增列）；</li>
 *   <li><b>normal / scrap ⇒ 0 行</b>（只有「有问题」这件事才记质检）；</li>
 *   <li><b>计件 / 进度口径一字不动</b>：返工不推进 {@code done_qty}、计件归零，且**不**触发
 *       #7165 的「完成质检工序」联动（{@code DocumentOperationLinkage} 零交互）；</li>
 *   <li><b>没有成品帘就不猜件</b>：工序实例缺 {@code order_item_id}（V92 之前存量行）⇒ 不落质检记录，
 *       但报工本身照常成功（不让新逻辑挡住工人的账）。</li>
 * </ol>
 *
 * <p>装配说明：{@code QualityCheckService} 用**真实现**（落库行是真的 {@link QualityCheck}），
 * 只把 {@link QualityCheckMapper} 换成替身来逐字段断言落库内容 —— 若用 mock 替掉整个服务，
 * 断言就退化成「调没调」，判不出「落的是什么」。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("返工报工 = 记录一次质检（issue #7919）")
class ProductionReworkQualityRecordTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-1";
    private static final String PO_ID = "po-1";
    private static final String ITEM_ID = "item-1";
    private static final String WORKER_ID = "worker-zhang";
    private static final String WORKER_NAME = "张师傅";

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
    @Mock
    private QualityCheckMapper qualityCheckMapper;
    /** 生产装配下的形态（`ObjectProvider` 延迟解析，见 `ProductionService#qualityCheckServiceProvider`）。 */
    @Mock
    private ObjectProvider<QualityCheckService> qualityCheckServiceProvider;
    /** #7165 的联动点：**返工报工一次都不该碰它**。 */
    @Mock
    private DocumentOperationLinkage documentOperationLinkage;

    private ProductionService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        service = new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper,
                orderMapper, orderItemMapper, clientRequestIdService);
        QualityCheckService qualityCheckService = new QualityCheckService(qualityCheckMapper, orderItemMapper,
                processingOrderMapper, orderMapper, new ObjectMapper());
        ReflectionTestUtils.setField(qualityCheckService, "documentOperationLinkage", documentOperationLinkage);
        ReflectionTestUtils.setField(service, "qualityCheckServiceProvider", qualityCheckServiceProvider);
        when(qualityCheckServiceProvider.getIfAvailable()).thenReturn(qualityCheckService);
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any()))
                .thenReturn(1);
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(true);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ============================================================ 夹具

    private Order order() {
        Order o = new Order();
        o.setId(ORDER_ID);
        o.setTenantId(TENANT);
        o.setOrderNo("ORD-20261027-001");
        o.setStatus("producing");
        o.setDeleted(0);
        return o;
    }

    private ProcessingOrder processingOrder() {
        ProcessingOrder po = new ProcessingOrder();
        po.setId(PO_ID);
        po.setTenantId(TENANT);
        po.setOrderId(ORDER_ID);
        po.setStatus("in_processing");
        po.setProcessingOrderNo("PO-20261027-001");
        po.setQrToken("tok123");
        po.setDeleted(0);
        return po;
    }

    /** 工序实例：部位名 / 工序名（变体 `精裁-布`，逻辑名 `精裁`）/ 成品帘 `order_item_id`。 */
    private ProcessingPositionOperation op(String orderItemId) {
        return ProcessingPositionOperation.builder()
                .id("op-1").tenantId(TENANT).processingOrderId(PO_ID)
                .orderItemId(orderItemId).positionName("布帘")
                .seq(1).operationName("精裁-布").groupName("后道").unit("套")
                .qty(new BigDecimal("2")).unitPrice(new BigDecimal("1.50")).factor(BigDecimal.ONE)
                .isMustFinish(false).isStartMarker(false)
                .status("pending").doneQty(BigDecimal.ZERO).deleted(0)
                .build();
    }

    private WorkerIdentity identity() {
        return new WorkerIdentity(WORKER_ID, WORKER_NAME, WorkerIdentity.SOURCE_SERVER_SESSION, "sess-1");
    }

    /** 扫码完成那条真实入口（`ProductionScanCompleteService` 与它同一条记账实现）。 */
    private Map<String, Object> reportByScan(String workType, BigDecimal qualifiedQty, ProcessingPositionOperation op) {
        return service.applyScanComplete(order(), processingOrder(), op, new BigDecimal("2"), qualifiedQty,
                workType, identity(), TENANT, null);
    }

    private Map<String, Object> reworkBody() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("worker_name", WORKER_NAME);
        body.put("qty", new BigDecimal("2"));
        body.put("qualified_qty", BigDecimal.ZERO);
        body.put("work_type", "rework");
        return body;
    }

    private QualityCheck captureInspection() {
        ArgumentCaptor<QualityCheck> captor = ArgumentCaptor.forClass(QualityCheck.class);
        verify(qualityCheckMapper, times(1)).insert(captor.capture());
        return captor.getValue();
    }

    // ============================================================ 判据 1

    @Test
    @DisplayName("🔴 判据 1：返工报工 ⇒ quality_inspections 恰好 1 行（判定/检验人/原因/时刻逐项）")
    void reworkReportWritesExactlyOneQualityInspection() {
        Map<String, Object> result = reportByScan("rework", BigDecimal.ZERO, op(ITEM_ID));

        QualityCheck row = captureInspection();
        assertThat(row.getTenantId()).isEqualTo(TENANT);
        assertThat(row.getProcessingOrderId()).isEqualTo(PO_ID);
        assertThat(row.getOrderItemId()).isEqualTo(ITEM_ID);
        assertThat(row.getPositionName()).isEqualTo("布帘");
        assertThat(row.getInspectionResult()).isEqualTo(QualityCheckService.RESULT_REWORK);
        assertThat(row.getInspectorKind()).isEqualTo(QualityCheckService.INSPECTOR_WORKER);
        assertThat(row.getInspectorId()).isEqualTo(WORKER_ID);
        assertThat(row.getInspectorName()).isEqualTo(WORKER_NAME);
        // 原因 = 固定前缀 + **逻辑**工序名（`精裁-布` ⇒ `精裁`：同一份归并表，不在这里另抄一份）
        assertThat(row.getReason()).isEqualTo("返工报工：精裁");
        assertThat(row.getDeleted()).isZero();
        // 业务时钟单点：+08:00（不是 JVM 默认时区 —— 判据钉的是 offset 本身）
        assertThat(row.getInspectedAt()).isNotNull();
        assertThat(row.getInspectedAt().getOffset()).isEqualTo(ZoneOffset.ofHours(8));
        // 报工本身照常回执
        assertThat(result.get("operation_id")).isEqualTo("op-1");
        assertThat(result.get("order_completed")).isEqualTo(Boolean.FALSE);
    }

    // ============================================================ 判据 2

    @Test
    @DisplayName("🔴 判据 2：同一 X-Client-Request-Id 重放 ⇒ 仍是 1 行（回放路径到不了落库点）")
    void replayWithSameClientRequestIdDoesNotWriteSecondInspection() {
        when(clientRequestIdService.claim(TENANT, "req-1", ProductionService.ENDPOINT_REPORT)).thenReturn(false);
        Map<String, Object> first = new LinkedHashMap<>();
        first.put("operation_id", "op-1");
        first.put("done_qty", BigDecimal.ZERO);
        first.put("status", "pending");
        when(clientRequestIdService.replay(TENANT, "req-1", Map.class)).thenReturn(Optional.of(first));

        Map<String, Object> replayed = service.report(ORDER_ID, "op-1", reworkBody(), TENANT, "req-1", identity());

        assertThat(replayed.get(ProductionService.REPLAYED_KEY)).isEqualTo(Boolean.TRUE);
        verify(qualityCheckMapper, never()).insert(any(QualityCheck.class));
        // 回放不改任何账：报工明细也不写
        verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
    }

    // ============================================================ 判据 3

    @Test
    @DisplayName("🔴 判据 3：normal / scrap 报工 ⇒ 一条质检记录都不落")
    void normalAndScrapReportsWriteNoInspection() {
        reportByScan("normal", new BigDecimal("2"), op(ITEM_ID));
        reportByScan("scrap", BigDecimal.ZERO, op(ITEM_ID));

        verify(qualityCheckMapper, never()).insert(any(QualityCheck.class));
        // 对照：两笔报工都真的落库了（否则本用例会在「什么都没发生」时空转通过）
        verify(workLogMapper, times(2)).insert(any(ProductionWorkLog.class));
    }

    // ============================================================ 判据 4

    @Test
    @DisplayName("🔴 判据 4：返工不推进进度、不计件，也不触发 #7165 的「完成质检工序」联动")
    void reworkKeepsPieceworkSemanticsAndSkipsLinkage() {
        reportByScan("rework", BigDecimal.ZERO, op(ITEM_ID));

        ArgumentCaptor<ProductionWorkLog> logCaptor = ArgumentCaptor.forClass(ProductionWorkLog.class);
        verify(workLogMapper, times(1)).insert(logCaptor.capture());
        assertThat(logCaptor.getValue().getWorkType()).isEqualTo("rework");
        assertThat(logCaptor.getValue().getQualifiedQty()).isEqualByComparingTo("0");
        // 不计件 / 不推进度：CAS 一次都不该被调用
        verify(positionOperationMapper, never())
                .advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any());
        // 不联动：质检工序的「完成」只属于显式质检判定（返工意味着还要再检）
        verifyNoInteractions(documentOperationLinkage);
    }

    // ============================================================ 判据 5

    @Test
    @DisplayName("判据 5：工序实例缺 order_item_id（存量行）⇒ 不落质检记录，但报工照常成功")
    void reworkWithoutOrderItemSkipsInspectionButReportSucceeds() {
        Map<String, Object> result = reportByScan("rework", BigDecimal.ZERO, op(null));

        verify(qualityCheckMapper, never()).insert(any(QualityCheck.class));
        verify(workLogMapper, times(1)).insert(any(ProductionWorkLog.class));
        assertThat(result.get("operation_id")).isEqualTo("op-1");
        assertThat((BigDecimal) result.get("done_qty")).isEqualByComparingTo("0");
    }

    // ============================================================ 边界：未装配（单测/切片）

    @Test
    @DisplayName("边界：QualityCheckService 未装配（手工装配的单测/切片）⇒ 跳过而不 NPE，报工照常")
    void missingQualityServiceSkipsInsteadOfFailing() {
        ReflectionTestUtils.setField(service, "qualityCheckServiceProvider", null);

        Map<String, Object> result = reportByScan("rework", BigDecimal.ZERO, op(ITEM_ID));

        verify(qualityCheckMapper, never()).insert(any(QualityCheck.class));
        assertThat(result.get("operation_id")).isEqualTo("op-1");
    }
}
