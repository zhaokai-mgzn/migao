// case_ids: PG-018
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
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * <b>工人无码自由报工</b>（issue #6598）—— 后端行为判据。
 *
 * <h2>用户裁定（2026-10-09，逐字）</h2>
 * <p>「当前工人报工只能按固定顺序报工，这个设计是不对的，<b>允许工人自由报工</b>」；开放范围当场选定 =
 * <b>整张加工单内任选任意工序（不扫码也能自由报）</b>。</p>
 *
 * <h2>本单落成的形态（口径）</h2>
 * <ol>
 *   <li>工人（{@code X-Worker-Session-Id} 身份）可对<b>本加工单的任意待做工序</b>报工，<b>无需扫码</b>；
 *       工序由工人<b>显式选择</b>（{@code operation_id}）；</li>
 *   <li>🔴 <b>「工序必须显式确定」不放宽</b>（issue #4694 硬约束）：缺 {@code operationId}
 *       ⇒ 422 且零写入，服务端<b>绝不</b>替客户端猜「下一道」；放宽的只是
 *       「必须落在本次扫码码内」这一条；</li>
 *   <li>计件归属仍由服务端从工人 session 解（issue #4733；body 里的 {@code worker_id} 一个字节都不读）；</li>
 *   <li>🔴 <b>记账口径只有一份</b>（{@code ProductionService#applyReport}）：无码路径与扫码路径的
 *       {@code done_at} / 完工判定必须<b>逐值一致</b> —— 判据见
 *       {@link #freePathAndScanPathProduceIdenticalAccounting()}。</li>
 * </ol>
 *
 * <h2>为什么端点复用既有 {@code /api/worker/production/orders/{orderId}/operations/{operationId}/report}</h2>
 * <p>该端点早已存在（issue #4733），由 {@code WorkerProductionController#report} 暴露，且已经满足本单
 * 全部口径：身份只从 session 解、工序由调用方显式给、归属校验走
 * {@link ProductionService#requireActiveOperation}、记账走<b>同一份</b>
 * {@code ProductionService#applyReport}（{@code done_at} / CAS / 完工判定一处不差）、幂等同
 * {@code X-Client-Request-Id}。本单<b>不新写第二份记账实现</b>，只把它接到工人 UI 上
 * （前端面见 {@code frontend/bmini-app/tests/production-free-report.test.tsx}）。</p>
 *
 * <p>⚠️ <b>本文件测的是「服务层 + 既有端点契约」这一半</b>；HTTP 层的身份解与 401 由
 * {@code WorkerProductionControllerTest} 承担（本文件不重复造第二份控制器判据）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("工人无码自由报工（issue #6598）：任意工序 + 显式确定 + 同一份记账")
class ProductionWorkerFreeReportTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-1";
    private static final String PO_ID = "po-1";
    private static final String OP_CLOTH = "op-cloth-1";
    /** 另一张加工单上的工序（跨单/跨部位报工必须 fail-closed）。 */
    private static final String OP_OTHER_PO = "op-other-po";

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

    private ProductionService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        service = new ProductionService(processingOrderMapper, positionOperationMapper,
                workLogMapper, orderMapper, orderItemMapper, clientRequestIdService);

        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        when(positionOperationMapper.selectById(OP_CLOTH)).thenReturn(cloth());
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any()))
                .thenReturn(1);
        when(workLogMapper.insert(any(ProductionWorkLog.class))).thenReturn(1);
        when(processingOrderMapper.markCompletedIfActive(any(), any(), any())).thenReturn(1);
        // 幂等默认「首次」（claim=true）；回放用例单独改成 false
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(true);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ============================================================ ① 无码 + 显式 operationId + 工人 session ⇒ 成功

    @Test
    @DisplayName("🔴 无码 + 显式 operationId + 工人 session ⇒ 成功，且计件记到 session 的工人头上")
    void freeReportChargesToSessionWorkerWithoutAnyToken() {
        Map<String, Object> result = service.report(ORDER_ID, OP_CLOTH, fullQty(11), TENANT,
                "key-1", WORKER);

        ProductionWorkLog log = capturedWorkLog();
        // 🔴 计件归属的根 = 工人 session（body 里的 worker_id 不参与；见下一个用例的冒领复核）
        assertThat(log.getWorkerId()).isEqualTo("w-1");
        assertThat(log.getWorkerName()).isEqualTo("张三");
        assertThat(log.getOperationId()).isEqualTo(OP_CLOTH);
        assertThat(log.getQualifiedQty()).isEqualByComparingTo("11");
        assertThat(result.get("operation_id")).isEqualTo(OP_CLOTH);
        assertThat(result.get("done_qty")).isEqualTo(new BigDecimal("11"));
        assertThat(result.get("identity_source")).isEqualTo(WorkerIdentity.SOURCE_SERVER_SESSION);
        // 无码路径落在**同一份**记账实现上：CAS 推进 + 真正做完才落 done_at
        verify(positionOperationMapper).advanceDoneQtyIfUnchanged(
                eq(OP_CLOTH), eq(TENANT), eq(BigDecimal.ZERO), eq("pending"),
                eq(new BigDecimal("11")), any(OffsetDateTime.class));
        verify(positionOperationMapper).recordCompletionIfDone(
                eq(OP_CLOTH), eq(TENANT), any(OffsetDateTime.class));
    }

    @Test
    @DisplayName("🔴 无码路径同样不读 body 身份：塞 worker_id=冒领 ⇒ 仍记到 session 解出的工人")
    void freeReportIgnoresWorkerIdentityInBody() {
        Map<String, Object> payload = fullQty(11);
        payload.put("worker_id", "attacker-9");
        payload.put("worker_name", "冒领");

        service.report(ORDER_ID, OP_CLOTH, payload, TENANT, "key-1", WORKER);

        assertThat(capturedWorkLog().getWorkerId()).isEqualTo("w-1");
        assertThat(capturedWorkLog().getWorkerName()).isEqualTo("张三");
    }

    // ============================================================ ② 工序必须显式确定 / 归属 fail-closed

    @Test
    @DisplayName("🔴 缺 operationId（客户端想让服务端猜下一道）⇒ 422，且零写入")
    void missingOperationIdIsRejectedWithoutWriting() {
        assertThatThrownBy(() -> service.report(ORDER_ID, "  ", fullQty(11), TENANT, "key-1", WORKER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("必须指定工序");

        assertNothingWritten();
    }

    @Test
    @DisplayName("🔴 工序不存在的 id ⇒ 404，且零写入")
    void unknownOperationIdIsRejectedWithoutWriting() {
        when(positionOperationMapper.selectById("op-ghost")).thenReturn(null);

        assertThatThrownBy(() -> service.report(ORDER_ID, "op-ghost", fullQty(11), TENANT,
                "key-1", WORKER))
                .isInstanceOf(BusinessException.class);

        assertNothingWritten();
    }

    @Test
    @DisplayName("🔴 工序属于**另一张**加工单 ⇒ 拒绝，且零写入（不得按别人的单记账）")
    void operationOfAnotherProcessingOrderIsRejectedWithoutWriting() {
        ProcessingPositionOperation foreign = cloth();
        foreign.setId(OP_OTHER_PO);
        foreign.setProcessingOrderId("po-other");
        when(positionOperationMapper.selectById(OP_OTHER_PO)).thenReturn(foreign);

        assertThatThrownBy(() -> service.report(ORDER_ID, OP_OTHER_PO, fullQty(11), TENANT,
                "key-1", WORKER))
                .isInstanceOf(BusinessException.class);

        assertNothingWritten();
    }

    @Test
    @DisplayName("🔴 工序已软删（deleted=1）⇒ 拒绝，且零写入（进度不得记到废弃实例上）")
    void softDeletedOperationIsRejectedWithoutWriting() {
        ProcessingPositionOperation deleted = cloth();
        deleted.setDeleted(1);
        when(positionOperationMapper.selectById(OP_CLOTH)).thenReturn(deleted);

        assertThatThrownBy(() -> service.report(ORDER_ID, OP_CLOTH, fullQty(11), TENANT,
                "key-1", WORKER))
                .isInstanceOf(BusinessException.class);

        assertNothingWritten();
    }

    @Test
    @DisplayName("🔴 工序属于别的租户 ⇒ 拒绝，且零写入")
    void operationOfAnotherTenantIsRejectedWithoutWriting() {
        ProcessingPositionOperation other = cloth();
        other.setTenantId(99L);
        when(positionOperationMapper.selectById(OP_CLOTH)).thenReturn(other);

        assertThatThrownBy(() -> service.report(ORDER_ID, OP_CLOTH, fullQty(11), TENANT,
                "key-1", WORKER))
                .isInstanceOf(BusinessException.class);

        assertNothingWritten();
    }

    // ============================================================ ③ 幂等

    @Test
    @DisplayName("🔴 同 X-Client-Request-Id 重放 ⇒ 不重复计件（回放首次结果，零新增写入）")
    void sameRequestIdReplaysWithoutSecondCharge() {
        Map<String, Object> first = new LinkedHashMap<>();
        first.put("operation_id", OP_CLOTH);
        first.put("done_qty", new BigDecimal("11"));
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(false);
        when(clientRequestIdService.replay(eq(TENANT), eq("key-1"), any()))
                .thenReturn(Optional.of(first));

        Map<String, Object> replayed = service.report(ORDER_ID, OP_CLOTH, fullQty(11), TENANT,
                "key-1", WORKER);

        assertThat(replayed.get("replayed")).isEqualTo(Boolean.TRUE);
        assertThat(replayed.get("done_qty")).isEqualTo(new BigDecimal("11"));
        assertNothingWritten();
        verify(clientRequestIdService, never()).complete(any(), any(), any());
    }

    // ============================================================ ④ 与扫码链路逐值一致（同一份记账实现）

    /**
     * 🔴 <b>本单最承重的一条</b>：无码自由报工与扫码开工的记账读数<b>逐值一致</b>。
     *
     * <p>判据形态：同一个工序夹具下先走无码路径（{@link ProductionService#report}）、再走扫码路径
     * （{@link ProductionService#applyScanComplete}），把两次对 Mapper 的**实参**逐个比对 ——
     * 若有人日后把其中一条改成「另一份实现」（少落 {@code done_at} / 换完工判据 / 换 CAS 谓词），
     * 两条的实参必然分叉 ⇒ 本用例红。</p>
     *
     * <p>为什么必须是**逐值**而不是「都能成功」：报工表是计件工资的唯一凭证（issue #4733），
     * 两条路径给出不同 {@code done_at} / 不同完工判定 = 同一批活在两个口径下记出两本账。</p>
     */
    @Test
    @DisplayName("🔴 无码路径与扫码路径的记账实参逐值一致（done_at / CAS / 完工判定同一份实现）")
    void freePathAndScanPathProduceIdenticalAccounting() {
        // —— 无码自由报工 ——
        service.report(ORDER_ID, OP_CLOTH, fullQty(11), TENANT, "key-free", WORKER);
        ArgumentCaptor<OffsetDateTime> freeDoneAt = ArgumentCaptor.forClass(OffsetDateTime.class);
        verify(positionOperationMapper).advanceDoneQtyIfUnchanged(
                eq(OP_CLOTH), eq(TENANT), eq(BigDecimal.ZERO), eq("pending"),
                eq(new BigDecimal("11")), freeDoneAt.capture());
        ArgumentCaptor<OffsetDateTime> freeCompletion = ArgumentCaptor.forClass(OffsetDateTime.class);
        verify(positionOperationMapper).recordCompletionIfDone(eq(OP_CLOTH), eq(TENANT),
                freeCompletion.capture());

        // —— 同一工序夹具，改走扫码开工 ——
        ProcessingPositionOperation scanOp = cloth();
        when(positionOperationMapper.selectById(OP_CLOTH)).thenReturn(scanOp);
        service.applyScanComplete(order(), processingOrder(), scanOp, new BigDecimal("11"),
                new BigDecimal("11"), "normal", WORKER, TENANT);
        ArgumentCaptor<OffsetDateTime> scanDoneAt = ArgumentCaptor.forClass(OffsetDateTime.class);
        verify(positionOperationMapper, times(2)).advanceDoneQtyIfUnchanged(
                eq(OP_CLOTH), eq(TENANT), eq(BigDecimal.ZERO), eq("pending"),
                eq(new BigDecimal("11")), scanDoneAt.capture());
        ArgumentCaptor<OffsetDateTime> scanCompletion = ArgumentCaptor.forClass(OffsetDateTime.class);
        verify(positionOperationMapper, times(2)).recordCompletionIfDone(eq(OP_CLOTH), eq(TENANT),
                scanCompletion.capture());

        // 逐值一致：CAS 实参（除时刻外）在上面 eq(...) 里已钉死；这里钉「两条都落了时刻」
        assertThat(freeDoneAt.getValue()).as("无码路径必须落 done_at 时刻（与扫码同款）").isNotNull();
        assertThat(scanDoneAt.getAllValues().get(1))
                .as("扫码路径必须落 done_at 时刻").isNotNull();
        assertThat(freeCompletion.getValue()).as("无码路径必须走「真正做完」判定").isNotNull();
        assertThat(scanCompletion.getAllValues().get(1))
                .as("扫码路径必须走同一份「真正做完」判定").isNotNull();

        // 两笔报工明细的**记账字段**逐值一致（数量 / 单价 / 价态 / 工种 / 身份）
        ArgumentCaptor<ProductionWorkLog> logs = ArgumentCaptor.forClass(ProductionWorkLog.class);
        verify(workLogMapper, times(2)).insert(logs.capture());
        ProductionWorkLog free = logs.getAllValues().get(0);
        ProductionWorkLog scan = logs.getAllValues().get(1);
        assertThat(free.getQualifiedQty()).isEqualByComparingTo(scan.getQualifiedQty());
        assertThat(free.getUnitPrice()).isEqualByComparingTo(scan.getUnitPrice());
        assertThat(free.getPriceState()).isEqualTo(scan.getPriceState());
        assertThat(free.getWorkType()).isEqualTo(scan.getWorkType());
        assertThat(free.getWorkerId()).isEqualTo(scan.getWorkerId());
        assertThat(free.getWorkerName()).isEqualTo(scan.getWorkerName());
        assertThat(free.getWorkDate()).isEqualTo(scan.getWorkDate());
    }

    // ============================================================ 夹具

    private ProductionWorkLog capturedWorkLog() {
        ArgumentCaptor<ProductionWorkLog> captor = ArgumentCaptor.forClass(ProductionWorkLog.class);
        verify(workLogMapper).insert(captor.capture());
        return captor.getValue();
    }

    /** 「记账三处写入一个字节都没发生」（拒绝路径与同键回放共用）。 */
    private void assertNothingWritten() {
        verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
        verify(positionOperationMapper, never())
                .advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any());
        verify(positionOperationMapper, never()).recordCompletionIfDone(any(), any(), any());
        verify(processingOrderMapper, never()).markCompletedIfActive(any(), any(), any());
    }

    private static Map<String, Object> fullQty(int qty) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("qty", new BigDecimal(qty));
        body.put("qualified_qty", new BigDecimal(qty));
        body.put("work_type", "normal");
        return body;
    }

    private static ProcessingOrder processingOrder() {
        return ProcessingOrder.builder()
                .id(PO_ID).tenantId(TENANT).orderId(ORDER_ID).processingOrderNo("CSO260915-02615")
                .status("issued").deleted(0).build();
    }

    private static Order order() {
        return Order.builder().id(ORDER_ID).tenantId(TENANT).orderNo("SO-1").deleted(0).build();
    }

    private static ProcessingPositionOperation cloth() {
        return ProcessingPositionOperation.builder()
                .id(OP_CLOTH).tenantId(TENANT).processingOrderId(PO_ID).setId("set-14")
                .orderItemId("oi-cloth").positionKind("布帘").positionName("布艺遮光帘A")
                .operationName("精裁-布").seq(1).unit("米").qty(new BigDecimal("11"))
                .doneQty(BigDecimal.ZERO).unitPrice(new BigDecimal("3.50")).status("pending")
                .isStartMarker(Boolean.FALSE).isMustFinish(Boolean.TRUE).deleted(0).build();
    }

    /** 仅供 javadoc 链接（{@code applyScanComplete} 的签名引用）；无运行时作用。 */
    @SuppressWarnings("unused")
    private static List<String> documentedPartners() {
        return List.of("applyScanComplete", "applyReport");
    }
}
