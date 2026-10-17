// case_ids: PG-077, PG-083
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.QualityCheck;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.QualityCheckMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.springframework.test.util.ReflectionTestUtils;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 质检记录（**成品帘级**）语义测试 —— issue #5652 的第一刀。
 *
 * <p>对应用例：<b>PG-077</b>（.github/cases/processing-order.yml）。</p>
 *
 * <p>🔴 <b>判据逐条（每条都能红）</b>：
 * ① <b>落库且逐字段可读</b>：捕获真落库的行，<b>逐值断言</b>判定/原因/检验人/时刻/成品帘/加工单
 * （不是「非空」）；
 * ② <b>判定 ≠ 合格 ⇒ 原因必填</b>：缺原因 ⇒ 具名 422，<b>零写入</b>（不许静默存）；
 * ③ <b>颗粒度 = 成品帘</b>：落库行的 {@code orderItemId} 逐字等于入参，且实体<b>没有</b> operationId
 * 面（结构面，见 {@code QualityCheckMetaGuardTest}）；
 * ④ <b>跨租户 = 404</b>，且与「不存在」逐字同一形态（不泄露存在性）；
 * ⑤ <b>读面不制造第二份聚合</b>：多条记录逐条给出（同件返工后重检是正常业务），不替客户端挑「当前判定」。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("QualityCheckService 质检记录（成品帘级）语义")
class QualityCheckServiceTest {

    private static final Long TENANT = 1L;
    private static final String ITEM_ID = "item-curtain-1";
    private static final String ORDER_ID = "order-1";
    private static final String PO_ID = "po-1";
    private static final String INSPECTOR_ID = "user-inspector-1";
    private static final String INSPECTOR_NAME = "质检员小李";
    private static final OffsetDateTime AT = OffsetDateTime.parse("2026-10-16T10:30:00+08:00");

    @Mock
    private QualityCheckMapper qualityInspectionMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private OrderMapper orderMapper;

    private QualityCheckService service;

    @BeforeEach
    void setUp() {
        service = new QualityCheckService(qualityInspectionMapper, orderItemMapper, processingOrderMapper,
                orderMapper, new com.fasterxml.jackson.databind.ObjectMapper());
        TenantContext.setTenantId(TENANT);
        when(orderItemMapper.selectById(ITEM_ID)).thenReturn(OrderItem.builder()
                .id(ITEM_ID)
                .tenantId(TENANT)
                .orderId(ORDER_ID)
                .productName("布艺遮光帘A 米白")
                .deleted(0)
                .build());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT))
                .thenReturn(ProcessingOrder.builder().id(PO_ID).tenantId(TENANT).orderId(ORDER_ID).build());
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("① 合格判定：落库且**逐字段**可读（判定/原因/检验人/时刻/成品帘/加工单）")
    void passRecordIsPersistedAndReadableFieldByField() {
        Map<String, Object> view = service.create(TENANT, ITEM_ID, "pass", null,
                INSPECTOR_ID, INSPECTOR_NAME, AT);

        QualityCheck row = capturedRow();
        // 逐值断言（不是「非空」）：这些值就是「谁/何时/哪件成品帘/判了什么」
        assertThat(row.getTenantId()).isEqualTo(TENANT);
        assertThat(row.getOrderItemId()).isEqualTo(ITEM_ID);
        assertThat(row.getProcessingOrderId()).isEqualTo(PO_ID);
        assertThat(row.getInspectionResult()).isEqualTo("pass");
        assertThat(row.getReason()).isNull();
        assertThat(row.getInspectorId()).isEqualTo(INSPECTOR_ID);
        assertThat(row.getInspectorName()).isEqualTo(INSPECTOR_NAME);
        assertThat(row.getInspectedAt()).isEqualTo(AT);
        assertThat(row.getDeleted()).isEqualTo(0);
        assertThat(row.getPositionName()).isEqualTo("布艺遮光帘A 米白");

        // 回执逐值同源（读面口径 = 落库口径，不另算一份）
        assertThat(view).containsEntry("order_item_id", ITEM_ID)
                .containsEntry("result", "pass")
                .containsEntry("result_label", "合格")
                .containsEntry("inspector_id", INSPECTOR_ID)
                .containsEntry("inspector_name", INSPECTOR_NAME)
                .containsEntry("inspected_at", AT)
                .containsEntry("processing_order_id", PO_ID)
                .containsEntry("position_name", "布艺遮光帘A 米白");
        assertThat(view.get("reason")).isNull();
    }

    @Test
    @DisplayName("① 返工 / 报废判定：判定与原因逐值落库（含去首尾空白），中文标签逐字")
    void reworkAndScrapArePersistedWithReason() {
        service.create(TENANT, ITEM_ID, "rework", "  缝线开裂  ", INSPECTOR_ID, INSPECTOR_NAME, AT);
        Map<String, Object> scrapView = service.create(TENANT, ITEM_ID, "scrap", "布面污渍无法清洗",
                INSPECTOR_ID, INSPECTOR_NAME, AT);

        ArgumentCaptor<QualityCheck> captor = ArgumentCaptor.forClass(QualityCheck.class);
        verify(qualityInspectionMapper, org.mockito.Mockito.times(2)).<QualityCheck>insert(captor.capture());
        List<QualityCheck> rows = captor.getAllValues();

        assertThat(rows.get(0).getInspectionResult()).isEqualTo("rework");
        assertThat(rows.get(0).getReason()).isEqualTo("缝线开裂");
        assertThat(rows.get(1).getInspectionResult()).isEqualTo("scrap");
        assertThat(rows.get(1).getReason()).isEqualTo("布面污渍无法清洗");
        assertThat(scrapView).containsEntry("result_label", "报废")
                .containsEntry("reason", "布面污渍无法清洗");
    }

    @Test
    @DisplayName("② 反例：判定≠合格但原因缺失/空白 ⇒ 具名 422，且**零写入**（不许静默存）")
    void nonPassWithoutReasonIsRejectedWithNamedErrorAndZeroWrite() {
        for (String blank : new String[]{null, "", "   "}) {
            assertThatThrownBy(() -> service.create(TENANT, ITEM_ID, "scrap", blank,
                    INSPECTOR_ID, INSPECTOR_NAME, AT))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> {
                        BusinessException be = (BusinessException) e;
                        assertThat(be.getCode()).isEqualTo("VALIDATION_ERROR");
                        assertThat(be.getHttpStatus()).isEqualTo(422);
                        // 具名：说出是哪一档判定缺原因（不是一句泛泛的「参数错误」）
                        assertThat(be.getMessage()).contains("报废").contains("必须填写不合格原因");
                    });
        }
        verify(qualityInspectionMapper, never()).insert(any(QualityCheck.class));
    }

    @Test
    @DisplayName("② 未知判定 ⇒ 422 具名（取值域只有 pass/rework/scrap）且零写入")
    void unknownResultIsRejectedAndListsTheLegalValues() {
        assertThatThrownBy(() -> service.create(TENANT, ITEM_ID, "ok", "因为", INSPECTOR_ID, INSPECTOR_NAME, AT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getMessage())
                        .contains("pass/rework/scrap").contains("ok"));
        verify(qualityInspectionMapper, never()).insert(any(QualityCheck.class));
    }

    @Test
    @DisplayName("④ 跨租户的成品帘 ⇒ 404，且与「不存在」逐字同一形态（不泄露存在性）")
    void crossTenantItemIsNotFoundWithTheSameShapeAsMissing() {
        OrderItem foreign = OrderItem.builder()
                .id("item-of-tenant-2").tenantId(2L).orderId(ORDER_ID).deleted(0).build();
        when(orderItemMapper.selectById("item-of-tenant-2")).thenReturn(foreign);

        BusinessException crossTenant = (BusinessException) org.assertj.core.api.Assertions
                .catchThrowable(() -> service.create(TENANT, "item-of-tenant-2", "pass", null,
                        INSPECTOR_ID, INSPECTOR_NAME, AT));
        BusinessException missing = (BusinessException) org.assertj.core.api.Assertions
                .catchThrowable(() -> service.create(TENANT, "item-does-not-exist", "pass", null,
                        INSPECTOR_ID, INSPECTOR_NAME, AT));

        assertThat(crossTenant.getCode()).isEqualTo("NOT_FOUND");
        assertThat(crossTenant.getHttpStatus()).isEqualTo(404);
        assertThat(crossTenant.getMessage()).isEqualTo("成品帘不存在");
        // 逐字同一形态（跨租户不给出比「不存在」更多的信息）
        assertThat(crossTenant.getCode()).isEqualTo(missing.getCode());
        assertThat(crossTenant.getHttpStatus()).isEqualTo(missing.getHttpStatus());
        assertThat(crossTenant.getMessage()).isEqualTo(missing.getMessage());
        verify(qualityInspectionMapper, never()).insert(any(QualityCheck.class));
    }

    @Test
    @DisplayName("④ 缺 order_item_id ⇒ 422（颗粒度是成品帘，缺它落不了记录）")
    void missingOrderItemIdIsRejected() {
        assertThatThrownBy(() -> service.create(TENANT, "  ", "pass", null, INSPECTOR_ID, INSPECTOR_NAME, AT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getMessage()).contains("成品帘"));
    }

    @Test
    @DisplayName("⑤ 读面：同件多条**逐条**给出（时间倒序口径由 SQL 承担），不替客户端挑「当前判定」")
    void listReturnsEveryRecordVerbatim() {
        QualityCheck first = QualityCheck.builder()
                .id("qi-1").tenantId(TENANT).processingOrderId(PO_ID).orderItemId(ITEM_ID)
                .positionName("布艺遮光帘A 米白").inspectorId(INSPECTOR_ID).inspectorName(INSPECTOR_NAME)
                .inspectionResult("scrap").reason("布面污渍").inspectedAt(AT).deleted(0).build();
        QualityCheck second = QualityCheck.builder()
                .id("qi-2").tenantId(TENANT).processingOrderId(PO_ID).orderItemId(ITEM_ID)
                .inspectorId(INSPECTOR_ID).inspectorName(INSPECTOR_NAME)
                .inspectionResult("pass").inspectedAt(AT.plusDays(1)).deleted(0).build();
        when(qualityInspectionMapper.selectList(any())).thenReturn(List.of(second, first));

        List<Map<String, Object>> rows = service.list(TENANT, PO_ID, ITEM_ID);

        assertThat(rows).hasSize(2);
        assertThat(rows.get(0)).containsEntry("id", "qi-2").containsEntry("result", "pass");
        assertThat(rows.get(0).get("reason")).isNull();
        assertThat(rows.get(1)).containsEntry("id", "qi-1").containsEntry("result", "scrap")
                .containsEntry("reason", "布面污渍");
    }

    @Test
    @DisplayName("④ 订单没有活跃加工单 ⇒ 422（质检对象必须是加工中的成品帘），零写入")
    void itemWhoseOrderHasNoActiveProcessingOrderIsRejected() {
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(null);

        assertThatThrownBy(() -> service.create(TENANT, ITEM_ID, "pass", null, INSPECTOR_ID, INSPECTOR_NAME, AT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getHttpStatus()).isEqualTo(422);
                    assertThat(be.getMessage()).contains("尚无活跃加工单");
                });
        verify(qualityInspectionMapper, never()).insert(any(QualityCheck.class));
    }

    @Test
    @DisplayName("⑦ 🔴 合格 ⇒ 联动完成质检工序（issue #7165）；返工/报废不联动（还要再检）")
    void passLinksQualityOperationButReworkDoesNot() {
        DocumentOperationLinkage linkage = org.mockito.Mockito.mock(DocumentOperationLinkage.class);
        ReflectionTestUtils.setField(service, "documentOperationLinkage", linkage);
        when(linkage.completeQualityOperation(any(), anyString(), any(), any())).thenReturn(1);

        service.create(TENANT, ITEM_ID, "pass", null, INSPECTOR_ID, INSPECTOR_NAME,
                QualityCheckService.INSPECTOR_EMPLOYEE, AT);

        // 观星台员工录 ⇒ actor = null（不计件）；只对「这一件」的质检工序
        verify(linkage).completeQualityOperation(eq(ORDER_ID), eq(ITEM_ID), isNull(), eq(TENANT));

        org.mockito.Mockito.clearInvocations(linkage);
        service.create(TENANT, ITEM_ID, "rework", "缝线开裂", INSPECTOR_ID, INSPECTOR_NAME,
                QualityCheckService.INSPECTOR_EMPLOYEE, AT);
        verify(linkage, never()).completeQualityOperation(any(), anyString(), any(), any());
    }

    @Test
    @DisplayName("⑦ 工人端录判定 ⇒ 把工人身份交给联动服务（计件记给该工人）")
    void workerPassCarriesActorIdentity() {
        DocumentOperationLinkage linkage = org.mockito.Mockito.mock(DocumentOperationLinkage.class);
        ReflectionTestUtils.setField(service, "documentOperationLinkage", linkage);
        com.migao.admin.worker.WorkerIdentity me = new com.migao.admin.worker.WorkerIdentity(
                "worker-1", "张师傅", com.migao.admin.worker.WorkerIdentity.SOURCE_SERVER_SESSION, "ws-1");

        service.create(TENANT, ITEM_ID, "pass", null, "worker-1", "张师傅",
                QualityCheckService.INSPECTOR_WORKER, AT, me);

        verify(linkage).completeQualityOperation(eq(ORDER_ID), eq(ITEM_ID), eq(me), eq(TENANT));
    }

    @Test
    @DisplayName("⑥ 工人端身份（issue #7162）：inspector_kind=worker 落库，读面带出")
    void workerInspectorKindIsPersistedAndReadable() {
        Map<String, Object> view = service.create(TENANT, ITEM_ID, "pass", null,
                "worker-user-1", "张师傅", QualityCheckService.INSPECTOR_WORKER, AT);

        QualityCheck row = capturedRow();
        assertThat(row.getInspectorKind()).isEqualTo(QualityCheckService.INSPECTOR_WORKER);
        assertThat(row.getInspectorId()).isEqualTo("worker-user-1");
        assertThat(view).containsEntry("inspector_kind", QualityCheckService.INSPECTOR_WORKER);
    }

    @Test
    @DisplayName("⑥ 未知 inspector_kind ⇒ 422（不静默落成员工 / 工人），零写入")
    void unknownInspectorKindIsRejected() {
        assertThatThrownBy(() -> service.create(TENANT, ITEM_ID, "pass", null,
                INSPECTOR_ID, INSPECTOR_NAME, "robot", AT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getMessage()).contains("inspector_kind"));
        verify(qualityInspectionMapper, never()).insert(any(QualityCheck.class));
    }

    @Test
    @DisplayName("⑥ 最新判定读面：无记录 ⇒ null（未检 ≠ 合格）；有记录 ⇒ 带出身份类别")
    void latestReturnsNewestOrNull() {
        when(qualityInspectionMapper.selectLatestByOrderItemIds(List.of(ITEM_ID))).thenReturn(List.of());
        assertThat(service.latest(TENANT, ITEM_ID)).isNull();

        QualityCheck row = QualityCheck.builder()
                .id("qi-9").tenantId(TENANT).processingOrderId(PO_ID).orderItemId(ITEM_ID)
                .inspectorId("worker-user-1").inspectorName("张师傅")
                .inspectorKind(QualityCheckService.INSPECTOR_WORKER)
                .inspectionResult("rework").reason("缝线开裂").inspectedAt(AT).deleted(0).build();
        when(qualityInspectionMapper.selectLatestByOrderItemIds(List.of(ITEM_ID))).thenReturn(List.of(row));

        assertThat(service.latest(TENANT, ITEM_ID))
                .containsEntry("result", "rework")
                .containsEntry("inspector_kind", QualityCheckService.INSPECTOR_WORKER);
    }

    /** 捕获这次真落库的那一行（逐值断言的取样点）。 */
    private QualityCheck capturedRow() {
        ArgumentCaptor<QualityCheck> captor = ArgumentCaptor.forClass(QualityCheck.class);
        verify(qualityInspectionMapper).<QualityCheck>insert(captor.capture());
        return captor.getValue();
    }
}
