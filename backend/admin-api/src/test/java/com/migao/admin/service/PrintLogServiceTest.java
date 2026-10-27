// case_ids: OR-071
package com.migao.admin.service;

import com.migao.admin.dto.PrintLogItemRequest;
import com.migao.admin.dto.PrintLogRecordResult;
import com.migao.admin.dto.PrintLogRequest;
import com.migao.admin.dto.PrintLogView;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.PrintLog;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.PrintLogMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 打印流水服务（issue #7902）—— 登记 / 快照 / 闭集合 / 列表 四组边界。
 *
 * <h3>本类钉住的错法（每一种都真实发生过或极易发生）</h3>
 * <ol>
 *   <li><b>快照来自服务端而不是请求体</b>：订单号 / 订单状态 / 操作人 / 租户 / 时间都不许由客户端递交
 *       —— 否则「谁打的」可以由调用方自己写，流水就没有证据价值；</li>
 *   <li><b>闭集合 fail-closed</b>：`doc_type` 只认四类（sales / processing / quotation / labels），
 *       写成 `report` 之类的自由串会让「打了哪种单据」的聚合永远对不上（表上还有 CHECK 兜底）；</li>
 *   <li><b>批量上限</b>：一次请求最多 10 条（超了 ⇒ 400，不是静默截断）；</li>
 *   <li><b>批号成组</b>：一次联合打印的 N 条共享 `batchId`，`batchIndex` 从 0 起、`batchSize` = 本次条数
 *       —— 三件缺一，就分不清「3 张纸一批」与「三批各 1 张」；</li>
 *   <li><b>订单不存在 / 跨租户 ⇒ 404</b>（不是 403：403 等于告诉对方「这个单存在，只是不归你」）；</li>
 *   <li><b>列表上限</b>：默认 20、封顶 100（不许把「看流水」变成全表扫）。</li>
 * </ol>
 *
 * <h3>红证（把实现改坏 ⇒ 本类必红）</h3>
 * <ul>
 *   <li>把 {@code order_no}/{@code order_status}/{@code operator_id} 改成从请求体取 ⇒ 判据 1 红；</li>
 *   <li>把 doc_type 白名单摘掉（或只判非空）⇒ 判据 2 红；</li>
 *   <li>把 {@code MAX_DOCS_PER_REQUEST} 改成「截断」⇒ 判据 3 红（不再抛 400）；</li>
 *   <li>把 batchIndex 写成 1 起、或每行一个新 batchId ⇒ 判据 4 红；</li>
 *   <li>列表 limit 不封顶 ⇒ 判据 6 红（verify 到的是 500 而不是 100）。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("打印流水服务：登记/快照/闭集合/列表的边界（#7902）")
class PrintLogServiceTest {

    private static final Long TENANT = 7L;
    private static final String ORDER_ID = "order-1";
    private static final String ORDER_NO = "ORD-20261027-0001";

    @Mock
    private PrintLogMapper printLogMapper;

    @Mock
    private OrderMapper orderMapper;

    @Mock
    private ProcessingOrderMapper processingOrderMapper;

    @InjectMocks
    private PrintLogService service;

    private final AtomicInteger idSeq = new AtomicInteger();

    private static final PrintLogService.Operator OPERATOR =
            new PrintLogService.Operator("u-1", "张三");

    @BeforeEach
    void setUp() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(Order.builder()
                .id(ORDER_ID)
                .tenantId(TENANT)
                .orderNo(ORDER_NO)
                .status("shipped")
                .build());
        // 真实环境里主键由 MyBatis-Plus 的 ASSIGN_UUID 在 insert 时填入；Mock 侧等价复现这一事实
        when(printLogMapper.insert(any(PrintLog.class))).thenAnswer(invocation -> {
            PrintLog row = invocation.getArgument(0);
            row.setId("log-" + idSeq.incrementAndGet());
            return 1;
        });
    }

    // ============================================================ 判据 1 / 4：逐条映射 + 批号

    @Test
    @DisplayName("🔴 两条文档 ⇒ 两行，订单号/状态/操作人都由**服务端**补齐，批内共享 batchId")
    void recordFillsServerSideSnapshotsPerDoc() {
        when(processingOrderMapper.selectById("po-1")).thenReturn(ProcessingOrder.builder()
                .id("po-1")
                .tenantId(TENANT)
                .orderId(ORDER_ID)
                .processingOrderNo("PO-20261027-0001")
                .build());

        PrintLogRecordResult result = service.record(ORDER_ID, request(
                item(PrintLog.DOC_PROCESSING, "加工单", "po-1", "continuous-241x140", 2),
                item(PrintLog.DOC_SALES, "销售单", null, "a4", null)
        ), TENANT, OPERATOR, "10.0.0.9", "Mozilla/5.0 (Macintosh)");

        ArgumentCaptor<PrintLog> rows = ArgumentCaptor.forClass(PrintLog.class);
        verify(printLogMapper, times(2)).insert(rows.capture());
        List<PrintLog> written = rows.getAllValues();

        assertThat(result.getIds()).containsExactly("log-1", "log-2");
        assertThat(result.getPrintedAt()).isNotNull();

        PrintLog processing = written.get(0);
        assertThat(processing.getTenantId()).isEqualTo(TENANT);
        assertThat(processing.getOrderId()).isEqualTo(ORDER_ID);
        // 🔴 快照：请求体里没有这三个字段，它们是服务端从订单/安全上下文补的
        assertThat(processing.getOrderNo()).isEqualTo(ORDER_NO);
        assertThat(processing.getOrderStatus()).isEqualTo("shipped");
        assertThat(processing.getOperatorId()).isEqualTo("u-1");
        assertThat(processing.getOperatorName()).isEqualTo("张三");
        assertThat(processing.getClientIp()).isEqualTo("10.0.0.9");
        assertThat(processing.getUserAgent()).isEqualTo("Mozilla/5.0 (Macintosh)");
        assertThat(processing.getDocType()).isEqualTo(PrintLog.DOC_PROCESSING);
        assertThat(processing.getDocTitle()).isEqualTo("加工单");
        assertThat(processing.getProcessingOrderId()).isEqualTo("po-1");
        assertThat(processing.getProcessingOrderNo()).isEqualTo("PO-20261027-0001");
        assertThat(processing.getMediaId()).isEqualTo("continuous-241x140");
        assertThat(processing.getSheets()).isEqualTo(2);
        assertThat(processing.getChannel()).isEqualTo(PrintLog.CHANNEL_BROWSER);
        assertThat(processing.getStatus()).isEqualTo(PrintLog.STATUS_FIRED);
        assertThat(processing.getCreatedAt()).isNotNull();

        PrintLog sales = written.get(1);
        assertThat(sales.getDocType()).isEqualTo(PrintLog.DOC_SALES);
        assertThat(sales.getDocTitle()).isEqualTo("销售单");
        assertThat(sales.getProcessingOrderId()).isNull();
        assertThat(sales.getProcessingOrderNo()).isNull();
        // 未给 sheets ⇒ 1 张（不是 null，也不是 0）
        assertThat(sales.getSheets()).isEqualTo(1);

        // 判据 4：批号成组
        assertThat(processing.getBatchId()).isNotBlank().isEqualTo(sales.getBatchId());
        assertThat(processing.getBatchIndex()).isZero();
        assertThat(sales.getBatchIndex()).isEqualTo(1);
        assertThat(processing.getBatchSize()).isEqualTo(2);
        assertThat(sales.getBatchSize()).isEqualTo(2);
    }

    @Test
    @DisplayName("未给 channel/status ⇒ 默认 browser/fired；failed 的原样落库并记下原因")
    void recordDefaultsChannelAndStatus() {
        PrintLogItemRequest failed = item(PrintLog.DOC_QUOTATION, "报价单", null, "a4", 1);
        failed.setStatus(PrintLog.STATUS_FAILED);
        failed.setFailReason("打印机脱机");

        service.record(ORDER_ID, request(failed), TENANT, OPERATOR, null, null);

        ArgumentCaptor<PrintLog> row = ArgumentCaptor.forClass(PrintLog.class);
        verify(printLogMapper).insert(row.capture());
        assertThat(row.getValue().getStatus()).isEqualTo(PrintLog.STATUS_FAILED);
        assertThat(row.getValue().getFailReason()).isEqualTo("打印机脱机");
        assertThat(row.getValue().getChannel()).isEqualTo(PrintLog.CHANNEL_BROWSER);
        assertThat(row.getValue().getClientIp()).isNull();
    }

    @Test
    @DisplayName("加工单号查不到/不属于本单 ⇒ 留空，不报错（打印不能因为主数据缺失而失败）")
    void recordKeepsProcessingOrderNoBlankWhenMissing() {
        service.record(ORDER_ID, request(
                item(PrintLog.DOC_LABELS, "水洗唛", "po-unknown", "label-50x150", 3)
        ), TENANT, OPERATOR, null, null);

        ArgumentCaptor<PrintLog> row = ArgumentCaptor.forClass(PrintLog.class);
        verify(printLogMapper).insert(row.capture());
        assertThat(row.getValue().getProcessingOrderId()).isEqualTo("po-unknown");
        assertThat(row.getValue().getProcessingOrderNo()).isNull();
    }

    @Test
    @DisplayName("加工单属于别的订单 ⇒ 也不借用它的单号（否则流水会把两张单串起来）")
    void recordDoesNotBorrowAnotherOrdersProcessingOrderNo() {
        when(processingOrderMapper.selectById("po-2")).thenReturn(ProcessingOrder.builder()
                .id("po-2")
                .tenantId(TENANT)
                .orderId("order-other")
                .processingOrderNo("PO-OTHER")
                .build());

        service.record(ORDER_ID, request(
                item(PrintLog.DOC_PROCESSING, "加工单", "po-2", "a4", 1)
        ), TENANT, OPERATOR, null, null);

        ArgumentCaptor<PrintLog> row = ArgumentCaptor.forClass(PrintLog.class);
        verify(printLogMapper).insert(row.capture());
        assertThat(row.getValue().getProcessingOrderNo()).isNull();
    }

    // ============================================================ 判据 2 / 3：闭集合与上限

    @Test
    @DisplayName("🔴 doc_type 是封闭集合：不认识的值 ⇒ 400，且一行都不写")
    void recordRejectsUnknownDocType() {
        PrintLogItemRequest bogus = item("receipt", "小票", null, "a4", 1);

        assertThatThrownBy(() -> service.record(ORDER_ID, request(bogus), TENANT, OPERATOR, null, null))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException ex = (BusinessException) e;
                    assertThat(ex.getCode()).isEqualTo("VALIDATION_ERROR");
                    assertThat(ex.getHttpStatus()).isEqualTo(400);
                    assertThat(ex.getMessage()).contains("receipt");
                });
        verify(printLogMapper, never()).insert(any(PrintLog.class));
    }

    @Test
    @DisplayName("🔴 一次最多 10 条：11 条 ⇒ 400，且一条都不写")
    void recordRejectsMoreThanTenDocs() {
        List<PrintLogItemRequest> docs = new ArrayList<>();
        for (int i = 0; i < PrintLogService.MAX_DOCS_PER_REQUEST + 1; i++) {
            docs.add(item(PrintLog.DOC_SALES, "销售单", null, "a4", 1));
        }

        assertThatThrownBy(() -> service.record(ORDER_ID, request(docs), TENANT, OPERATOR, null, null))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException ex = (BusinessException) e;
                    assertThat(ex.getCode()).isEqualTo("VALIDATION_ERROR");
                    assertThat(ex.getHttpStatus()).isEqualTo(400);
                });
        verify(printLogMapper, never()).insert(any(PrintLog.class));
    }

    @Test
    @DisplayName("空 docs / 缺 docs ⇒ 400（不写空流水）")
    void recordRejectsEmptyDocs() {
        assertThatThrownBy(() -> service.record(ORDER_ID, new PrintLogRequest(), TENANT, OPERATOR, null, null))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(400));
        verify(printLogMapper, never()).insert(any(PrintLog.class));
    }

    @Test
    @DisplayName("出纸张数越界（0 / 1000）⇒ 400")
    void recordRejectsSheetsOutOfRange() {
        for (int sheets : List.of(0, 1000)) {
            assertThatThrownBy(() -> service.record(ORDER_ID,
                    request(item(PrintLog.DOC_SALES, "销售单", null, "a4", sheets)), TENANT, OPERATOR, null, null))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(400));
        }
        verify(printLogMapper, never()).insert(any(PrintLog.class));
    }

    @Test
    @DisplayName("纸面名超长（> 32）⇒ 400（列宽就是 32，不许由 DB 静默截断）")
    void recordRejectsOverlongDocTitle() {
        PrintLogItemRequest item = item(PrintLog.DOC_SALES, "销".repeat(33), null, "a4", 1);

        assertThatThrownBy(() -> service.record(ORDER_ID, request(item), TENANT, OPERATOR, null, null))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(400));
        verify(printLogMapper, never()).insert(any(PrintLog.class));
    }

    // ============================================================ 判据 5：订单不存在 / 跨租户

    @Test
    @DisplayName("🔴 订单不存在 ⇒ 404（打印流水不能挂在一个不存在的单上）")
    void recordRejectsMissingOrder() {
        when(orderMapper.selectById("order-missing")).thenReturn(null);

        assertThatThrownBy(() -> service.record("order-missing", request(
                item(PrintLog.DOC_SALES, "销售单", null, "a4", 1)), TENANT, OPERATOR, null, null))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException ex = (BusinessException) e;
                    assertThat(ex.getCode()).isEqualTo("NOT_FOUND");
                    assertThat(ex.getHttpStatus()).isEqualTo(404);
                });
        verify(printLogMapper, never()).insert(any(PrintLog.class));
    }

    @Test
    @DisplayName("🔴 跨租户 ⇒ 与「不存在」同一个 404（不是 403：403 泄露存在性）")
    void recordTreatsOtherTenantsOrderAsMissing() {
        when(orderMapper.selectById("order-9")).thenReturn(Order.builder()
                .id("order-9").tenantId(99L).orderNo("ORD-OTHER").status("pending").build());

        assertThatThrownBy(() -> service.record("order-9", request(
                item(PrintLog.DOC_SALES, "销售单", null, "a4", 1)), TENANT, OPERATOR, null, null))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));
        verify(printLogMapper, never()).insert(any(PrintLog.class));
    }

    @Test
    @DisplayName("🔴 没有租户上下文 ⇒ 401（不把「你没有租户」伪装成「这单没打过」，也不留一个 NOT NULL 的 500）")
    void recordAndListRejectMissingTenantContext() {
        for (Runnable call : List.<Runnable>of(
                () -> service.record(ORDER_ID, request(item(PrintLog.DOC_SALES, "销售单", null, "a4", 1)),
                        null, OPERATOR, null, null),
                () -> service.listByOrder(ORDER_ID, 20, null))) {
            assertThatThrownBy(call::run)
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> {
                        BusinessException ex = (BusinessException) e;
                        assertThat(ex.getCode()).isEqualTo("TENANT_INVALID");
                        assertThat(ex.getHttpStatus()).isEqualTo(401);
                    });
        }
        verify(printLogMapper, never()).insert(any(PrintLog.class));
        verify(printLogMapper, never()).selectByOrder(any(), any(), any(Integer.class));
    }

    // ============================================================ 判据 6：列表

    @Test
    @DisplayName("🔴 列表默认 20 条、封顶 100 条（limit=500 ⇒ 查 100）")
    void listCapsLimitAtHundredAndDefaultsToTwenty() {
        when(printLogMapper.selectByOrder(eq(TENANT), eq(ORDER_ID), any(Integer.class)))
                .thenReturn(List.of(sampleLog()));

        service.listByOrder(ORDER_ID, null, TENANT);
        verify(printLogMapper).selectByOrder(TENANT, ORDER_ID, PrintLogService.DEFAULT_LIST_LIMIT);

        service.listByOrder(ORDER_ID, 500, TENANT);
        verify(printLogMapper).selectByOrder(TENANT, ORDER_ID, PrintLogService.MAX_LIST_LIMIT);

        service.listByOrder(ORDER_ID, 5, TENANT);
        verify(printLogMapper).selectByOrder(TENANT, ORDER_ID, 5);
    }

    @Test
    @DisplayName("列表逐键映射（前端按这些键渲染「谁 / 何时 / 哪种单据 / 几张」）")
    void listMapsEveryKey() {
        when(printLogMapper.selectByOrder(TENANT, ORDER_ID, PrintLogService.DEFAULT_LIST_LIMIT))
                .thenReturn(List.of(sampleLog()));

        List<PrintLogView> views = service.listByOrder(ORDER_ID, null, TENANT);

        assertThat(views).hasSize(1);
        PrintLogView view = views.get(0);
        assertThat(view.getId()).isEqualTo("log-9");
        assertThat(view.getOrderId()).isEqualTo(ORDER_ID);
        assertThat(view.getOrderNo()).isEqualTo(ORDER_NO);
        assertThat(view.getDocType()).isEqualTo(PrintLog.DOC_PROCESSING);
        assertThat(view.getDocTitle()).isEqualTo("加工单");
        assertThat(view.getProcessingOrderNo()).isEqualTo("PO-1");
        assertThat(view.getMediaId()).isEqualTo("continuous-241x140");
        assertThat(view.getSheets()).isEqualTo(2);
        assertThat(view.getChannel()).isEqualTo(PrintLog.CHANNEL_BLE);
        assertThat(view.getBatchId()).isEqualTo("batch-1");
        assertThat(view.getBatchIndex()).isZero();
        assertThat(view.getBatchSize()).isEqualTo(1);
        assertThat(view.getOrderStatus()).isEqualTo("shipped");
        assertThat(view.getStatus()).isEqualTo(PrintLog.STATUS_FIRED);
        assertThat(view.getOperatorId()).isEqualTo("u-1");
        assertThat(view.getOperatorName()).isEqualTo("张三");
        assertThat(view.getCreatedAt()).isNotNull();
    }

    @Test
    @DisplayName("列表：订单不存在 ⇒ 404（不返回空列表冒充「没打过」）")
    void listRejectsMissingOrder() {
        when(orderMapper.selectById("order-missing")).thenReturn(null);

        assertThatThrownBy(() -> service.listByOrder("order-missing", 20, TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));
        verify(printLogMapper, never()).selectByOrder(any(), any(), any(Integer.class));
    }

    // ============================================================ 工具

    private static PrintLog sampleLog() {
        return PrintLog.builder()
                .id("log-9")
                .tenantId(TENANT)
                .orderId(ORDER_ID)
                .orderNo(ORDER_NO)
                .docType(PrintLog.DOC_PROCESSING)
                .docTitle("加工单")
                .processingOrderId("po-1")
                .processingOrderNo("PO-1")
                .mediaId("continuous-241x140")
                .sheets(2)
                .channel(PrintLog.CHANNEL_BLE)
                .batchId("batch-1")
                .batchIndex(0)
                .batchSize(1)
                .orderStatus("shipped")
                .status(PrintLog.STATUS_FIRED)
                .operatorId("u-1")
                .operatorName("张三")
                .clientIp("10.0.0.9")
                .createdAt(OffsetDateTime.now())
                .build();
    }

    private static PrintLogRequest request(PrintLogItemRequest... docs) {
        return request(List.of(docs));
    }

    private static PrintLogRequest request(List<PrintLogItemRequest> docs) {
        PrintLogRequest request = new PrintLogRequest();
        request.setDocs(new ArrayList<>(docs));
        return request;
    }

    private static PrintLogItemRequest item(String docType, String docTitle, String processingOrderId,
                                            String mediaId, Integer sheets) {
        PrintLogItemRequest item = new PrintLogItemRequest();
        item.setDocType(docType);
        item.setDocTitle(docTitle);
        item.setProcessingOrderId(processingOrderId);
        item.setMediaId(mediaId);
        item.setSheets(sheets);
        return item;
    }
}
