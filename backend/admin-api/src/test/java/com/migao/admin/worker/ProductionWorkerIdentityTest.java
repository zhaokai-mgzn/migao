// case_ids: PG-018, PG-020, BM-006
package com.migao.admin.worker;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.entity.WorkerReportAudit;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import com.migao.admin.mapper.WorkerReportAuditMapper;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ProductionService;
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
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 🔴 本单**最核心**的红证（issue #4733 / 设计 #4716 **W1**）：报工身份**由服务端解**，
 * body 里的 {@code worker_id}/{@code worker_name} **一律忽略**。
 *
 * <p><b>改前形态（红）</b>：{@code ProductionService.doReport} 逐字
 * {@code .workerId(str(body.get("worker_id"))).workerName(str(body.get("worker_name")))} ⇒
 * body 传别人的 id 就记成别人（冒领）。本测试注入「body 传**别人**的 worker_id」，
 * 断言落库的 {@code worker_id} **必须**是登录者 —— 在改前的实现上这条**必红**
 * （实测：落库 = body 里的人）。</p>
 *
 * <p>反向护栏（同文件，防「顺手放宽」）：</p>
 * <ul>
 *   <li>商家侧报工（无工人 session）**既有行为不变** —— 仍按 body 口径记，但
 *       {@code identity_source} 必须被**显式标注**为 {@code client_body}（不静默）；</li>
 *   <li>{@code unit_price}/{@code factor} 一字不动（报工快照仍取工序实例的价）。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("报工身份：服务端解身份（忽略 body）+ 冒领红证")
class ProductionWorkerIdentityTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-1";
    private static final String PO_ID = "po-1";
    private static final String OP_ID = "op-1";

    /** 登录者（服务端 session 解出的工人）。 */
    private static final String SESSION_WORKER_ID = "worker-zhang";
    private static final String SESSION_WORKER_NAME = "张三";
    /** body 里冒充的别人。 */
    private static final String IMPERSONATED_ID = "worker-li";
    private static final String IMPERSONATED_NAME = "李四";

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
    private WorkerReportAuditMapper workerReportAuditMapper;

    private ProductionService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        service = new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper,
                orderMapper, orderItemMapper, clientRequestIdService);
        // 旁路账 mapper 是字段注入（可选）：手工装配后显式灌入，才能断言「账也记对了」
        ReflectionTestUtils.setField(service, "workerReportAuditMapper", workerReportAuditMapper);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        when(positionOperationMapper.selectById(OP_ID)).thenReturn(operation());
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(true);
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any()))
                .thenReturn(1);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ============================================================ ① 冒领红证（本单最核心）

    @Test
    @DisplayName("🔴 红证：body 传**别人的** worker_id/worker_name ⇒ 必须记成**登录者**（改前记成 body 里的人）")
    void reportIgnoresBodyWorkerIdentityWhenWorkerSessionPresent() {
        Map<String, Object> body = new HashMap<>();
        body.put("qty", new BigDecimal("4"));
        body.put("qualified_qty", new BigDecimal("4"));
        body.put("work_type", "normal");
        // 冒领：body 声称是「李四」
        body.put("worker_id", IMPERSONATED_ID);
        body.put("worker_name", IMPERSONATED_NAME);

        Map<String, Object> result = service.report(ORDER_ID, OP_ID, body, TENANT, null,
                new WorkerIdentity(SESSION_WORKER_ID, SESSION_WORKER_NAME,
                        WorkerIdentity.SOURCE_SERVER_SESSION, "sess-1"));

        // ① 落库的报工行必须是**登录者**（工资凭证）
        ArgumentCaptor<ProductionWorkLog> logCaptor = ArgumentCaptor.forClass(ProductionWorkLog.class);
        verify(workLogMapper).insert(logCaptor.capture());
        ProductionWorkLog written = logCaptor.getValue();
        assertThat(written.getWorkerId())
                .as("body 传了别人的 worker_id ⇒ 落库仍必须是登录者（否则就是冒领）")
                .isEqualTo(SESSION_WORKER_ID);
        assertThat(written.getWorkerName()).isEqualTo(SESSION_WORKER_NAME);
        assertThat(written.getWorkerId()).isNotEqualTo(IMPERSONATED_ID);

        // ② 响应把「记到谁头上」显式回给前端（页头「已记到：张三」的数据来源）
        assertThat(result.get("worker_id")).isEqualTo(SESSION_WORKER_ID);
        assertThat(result.get("worker_name")).isEqualTo(SESSION_WORKER_NAME);
        assertThat(result.get("identity_source")).isEqualTo(WorkerIdentity.SOURCE_SERVER_SESSION);
    }

    @Test
    @DisplayName("每笔计件留身份快照（W4）：工序实例写同源 worker_id/worker_name + 旁路账 1:1 带 session 与来源")
    void reportSnapshotsWorkerIdentityOnOperationAndAuditLedger() {
        Map<String, Object> body = new HashMap<>();
        body.put("qty", new BigDecimal("1"));
        body.put("qualified_qty", new BigDecimal("1"));
        body.put("work_type", "normal");

        service.report(ORDER_ID, OP_ID, body, TENANT, null,
                new WorkerIdentity(SESSION_WORKER_ID, SESSION_WORKER_NAME,
                        WorkerIdentity.SOURCE_SERVER_SESSION, "sess-9"));

        // 工序实例（V92 预留列）与报工行同源
        verify(positionOperationMapper).recordReporter(
                org.mockito.ArgumentMatchers.eq(OP_ID), org.mockito.ArgumentMatchers.eq(TENANT),
                org.mockito.ArgumentMatchers.eq(SESSION_WORKER_ID),
                org.mockito.ArgumentMatchers.eq(SESSION_WORKER_NAME), any());

        ArgumentCaptor<WorkerReportAudit> auditCaptor = ArgumentCaptor.forClass(WorkerReportAudit.class);
        verify(workerReportAuditMapper).insert(auditCaptor.capture());
        WorkerReportAudit audit = auditCaptor.getValue();
        assertThat(audit.getWorkerId()).isEqualTo(SESSION_WORKER_ID);
        assertThat(audit.getWorkerSessionId()).as("由哪个设备会话报的").isEqualTo("sess-9");
        assertThat(audit.getIdentitySource()).isEqualTo(WorkerIdentity.SOURCE_SERVER_SESSION);
        assertThat(audit.getOperationId()).as("旁路账挂在同一道工序上").isEqualTo(OP_ID);
    }

    // ============================================================ ② 反向护栏：商家侧既有行为不变

    @Test
    @DisplayName("商家侧报工（无工人 session）既有行为**逐条不变**：仍按 body 记，但来源被显式标注 client_body")
    void merchantReportKeepsLegacyBodyIdentityButLabelsSource() {
        Map<String, Object> body = new HashMap<>();
        body.put("qty", new BigDecimal("2"));
        body.put("qualified_qty", new BigDecimal("2"));
        body.put("work_type", "normal");
        body.put("worker_id", "staff-1");
        body.put("worker_name", "王师傅");

        // 兼容重载 = 商家侧口径（既有调用方逐字不变）
        Map<String, Object> result = service.report(ORDER_ID, OP_ID, body, TENANT, null);

        ArgumentCaptor<ProductionWorkLog> logCaptor = ArgumentCaptor.forClass(ProductionWorkLog.class);
        verify(workLogMapper).insert(logCaptor.capture());
        assertThat(logCaptor.getValue().getWorkerId()).as("既有口径不变：仍取 body").isEqualTo("staff-1");
        assertThat(logCaptor.getValue().getWorkerName()).isEqualTo("王师傅");
        // 但「谁都能填」从此**可见**（不静默）
        assertThat(result.get("identity_source")).isEqualTo(WorkerIdentity.SOURCE_CLIENT_BODY);

        ArgumentCaptor<WorkerReportAudit> auditCaptor = ArgumentCaptor.forClass(WorkerReportAudit.class);
        verify(workerReportAuditMapper).insert(auditCaptor.capture());
        assertThat(auditCaptor.getValue().getIdentitySource()).isEqualTo(WorkerIdentity.SOURCE_CLIENT_BODY);
        assertThat(auditCaptor.getValue().getWorkerSessionId()).isNull();
    }

    @Test
    @DisplayName("反向护栏：计件单价快照仍取工序实例（unit_price 一字不动；报工只写不读 body 的价）")
    void reportStillSnapshotsUnitPriceFromOperation() {
        Map<String, Object> body = new HashMap<>();
        body.put("qty", new BigDecimal("3"));
        body.put("qualified_qty", new BigDecimal("3"));
        body.put("work_type", "normal");
        // body 试图塞单价（历史漏洞形态）：必须被忽略
        body.put("unit_price", new BigDecimal("999.99"));
        body.put("factor", new BigDecimal("9.99"));

        service.report(ORDER_ID, OP_ID, body, TENANT, null,
                new WorkerIdentity(SESSION_WORKER_ID, SESSION_WORKER_NAME,
                        WorkerIdentity.SOURCE_SERVER_SESSION, "sess-1"));

        ArgumentCaptor<ProductionWorkLog> logCaptor = ArgumentCaptor.forClass(ProductionWorkLog.class);
        verify(workLogMapper).insert(logCaptor.capture());
        assertThat(logCaptor.getValue().getUnitPrice())
                .as("单价快照 = 工序实例的价（body 里的 unit_price 不得生效）")
                .isEqualByComparingTo("1.50");
    }

    // ============================================================ ③ 无 session 的工人路径必须拒绝

    @Test
    @DisplayName("反向护栏：工人身份缺失 ⇒ 不得静默落成「未署名」（调用方必须显式拒绝，本层不兜底）")
    void reportWithoutAnyIdentityDoesNotInventAWorker() {
        Map<String, Object> body = new HashMap<>();
        body.put("qty", new BigDecimal("1"));
        body.put("qualified_qty", new BigDecimal("1"));
        body.put("work_type", "normal");

        Map<String, Object> result = service.report(ORDER_ID, OP_ID, body, TENANT, null,
                WorkerIdentity.fromClientBody(null, null));

        ArgumentCaptor<ProductionWorkLog> logCaptor = ArgumentCaptor.forClass(ProductionWorkLog.class);
        verify(workLogMapper).insert(logCaptor.capture());
        assertThat(logCaptor.getValue().getWorkerId()).isNull();
        assertThat(result.get("identity_source")).isEqualTo(WorkerIdentity.SOURCE_CLIENT_BODY);
        // 服务层**不**发明工人（「未署名」是读面展示文案，不是身份）
        verify(workerReportAuditMapper, times(1)).insert(any(WorkerReportAudit.class));
    }

    @Test
    @DisplayName("工序必须确定（#4694 不放宽）：operationId 缺失 ⇒ 422，与身份改造无关")
    void reportStillRequiresDeterminateOperation() {
        Map<String, Object> body = new HashMap<>();
        body.put("qty", new BigDecimal("1"));
        body.put("qualified_qty", new BigDecimal("1"));
        body.put("work_type", "normal");

        try {
            service.report(ORDER_ID, "  ", body, TENANT, null,
                    new WorkerIdentity(SESSION_WORKER_ID, SESSION_WORKER_NAME,
                            WorkerIdentity.SOURCE_SERVER_SESSION, "sess-1"));
            org.junit.jupiter.api.Assertions.fail("工序未确定必须拒绝");
        } catch (BusinessException e) {
            assertThat(e.getCode()).isEqualTo("VALIDATION_ERROR");
        }
    }

    // ============================================================ 夹具

    private Order order() {
        Order o = new Order();
        o.setId(ORDER_ID);
        o.setTenantId(TENANT);
        o.setOrderNo("ORD-20260920-001");
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
        po.setDeleted(0);
        return po;
    }

    private ProcessingPositionOperation operation() {
        return ProcessingPositionOperation.builder()
                .id(OP_ID).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("布帘").seq(1).operationName("三边").groupName("后道").unit("米")
                .qty(new BigDecimal("10")).unitPrice(new BigDecimal("1.50")).factor(new BigDecimal("1.00"))
                .isMustFinish(false).isStartMarker(false)
                .status("pending").doneQty(BigDecimal.ZERO).deleted(0)
                .build();
    }

    /** 让 Wrapper 泛型检查不报未使用（与既有测试同款）。 */
    @SuppressWarnings("unused")
    private void unusedWrapper(Wrapper<?> w) {
    }
}
