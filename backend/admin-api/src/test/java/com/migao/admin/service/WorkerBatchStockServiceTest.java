package com.migao.admin.service;

// case_ids: BM-056, PG-072

import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.WorkerBatchCorrectionRequest;
import com.migao.admin.dto.WorkerBatchStockViews;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.worker.WorkerIdentity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工人端**批次库存修正**服务测试（issue #8104）。
 *
 * <p>判据（每条都能单独变红）：</p>
 * <ol>
 *   <li><b>不写第二套库存账</b>：本类只调 {@code BatchStocktakeService#stocktake}（唯一写面），
 *       并把它收到的 tenant / productId / 幂等运行标识 / 实盘行逐值钉住；</li>
 *   <li><b>台账答得出「谁、为什么」</b>：{@code StocktakeAudit.operator} = 工人姓名、
 *       {@code notePrefix} 带工号与原因标签（工人请求在 {@code resolveOperator()} 眼里是 system ⇒ 必须显式给）；</li>
 *   <li><b>幂等键拼装</b>：{@code clientRequestId} → 运行标识 {@code wc-<id>}；缺失 / 超长 / 非法字符 ⇒ 422；</li>
 *   <li><b>实盘米数走库存链路的同一准入</b>：负数 400、超 1 位小数 422、缺值 422（不静默取整）；</li>
 *   <li><b>批次必须属于本租户</b>：查不到 ⇒ 404，且**不触达**写入面；</li>
 *   <li><b>三态原样透传</b>：applied / unchanged / replayed 不在本类里改写（零写入与幂等回放是上游判据）。</li>
 * </ol>
 */
@DisplayName("WorkerBatchStockService 工人批次库存修正（issue #8104）")
class WorkerBatchStockServiceTest {

    private static final Long TENANT = 25L;
    private static final Long BATCH_ID = 7L;
    private static final String PRODUCT_ID = "prod-1";
    private static final String WORKER_NAME = "张三";
    private static final String WORKER_NO = "CY-1001";

    private StockBatchConsumptionService batchStockService;
    private BatchStocktakeService batchStocktakeService;
    private ProductMapper productMapper;
    private UserMapper userMapper;
    private WorkerBatchStockService service;

    @BeforeEach
    void setUp() {
        batchStockService = mock(StockBatchConsumptionService.class);
        batchStocktakeService = mock(BatchStocktakeService.class);
        productMapper = mock(ProductMapper.class);
        userMapper = mock(UserMapper.class);
        service = new WorkerBatchStockService(batchStockService, batchStocktakeService,
                productMapper, userMapper);

        when(productMapper.selectList(any())).thenReturn(List.of(
                Product.builder().id(PRODUCT_ID).name("雪尼尔窗帘布").build()));
        when(userMapper.selectById(any())).thenReturn(User.builder()
                .id("worker-zhang").workerNo(WORKER_NO).nickname(WORKER_NAME).build());
    }

    private static WorkerIdentity zhang() {
        return new WorkerIdentity("worker-zhang", WORKER_NAME,
                WorkerIdentity.SOURCE_SERVER_SESSION, "sess-1");
    }

    private static BatchStockViews.BatchRemaining remaining(String meters) {
        return new BatchStockViews.BatchRemaining(BATCH_ID, "PC-20261020-0007", PRODUCT_ID, 12L,
                "2659-04-28", "RK-20261020-0001", "A12", LocalDate.of(2026, 10, 20),
                new BigDecimal("20"), new BigDecimal("45.5"), BigDecimal.ZERO,
                new BigDecimal(meters));
    }

    private static BatchStockViews.StocktakeLineResult line(String status, String before,
                                                            String actual, String delta,
                                                            String after) {
        return new BatchStockViews.StocktakeLineResult(BATCH_ID, "PC-20261020-0007", 12L,
                "2659-04-28", new BigDecimal(before), new BigDecimal(actual), new BigDecimal(delta),
                new BigDecimal(after), status);
    }

    private static WorkerBatchCorrectionRequest request(String actual, String reason,
                                                        String requestId) {
        WorkerBatchCorrectionRequest request = new WorkerBatchCorrectionRequest();
        request.setBatchId(BATCH_ID);
        request.setActualMeters(actual == null ? null : new BigDecimal(actual));
        request.setReason(reason);
        request.setClientRequestId(requestId);
        return request;
    }

    // ────────────────────────────────────────────── ① 复用唯一写面 + 审计来源

    @Test
    @DisplayName("① 提交修正 ⇒ 调 stocktake（tenant / productId / wc-幂等键 / 实盘行）+ 审计来源带工人与原因")
    void correctionDelegatesToTheSingleWriteFaceWithAudit() {
        when(batchStockService.remainingOfBatch(TENANT, BATCH_ID)).thenReturn(remaining("45.5"));
        when(batchStocktakeService.stocktake(any(), anyString(), anyString(), any(), any()))
                .thenReturn(new BatchStockViews.StocktakeResult("wc-8f2b", PRODUCT_ID, 1, 0, 0,
                        new BigDecimal("-3.5"),
                        List.of(line(BatchStockViews.STOCKTAKE_APPLIED, "45.5", "42", "-3.5", "42"))));

        WorkerBatchCorrectionRequest request = request("42", "miscount", "8f2b");
        request.setNote("裁过一截");

        WorkerBatchStockViews.Correction receipt = service.correct(TENANT, zhang(), request);

        // 唯一写面：批次归属由服务端从批次行解析（不是请求体自带的 productId）
        ArgumentCaptor<List<com.migao.admin.dto.BatchStocktakeRequest.Line>> lines =
                ArgumentCaptor.forClass(List.class);
        ArgumentCaptor<StockBatchConsumptionService.StocktakeAudit> audit =
                ArgumentCaptor.forClass(StockBatchConsumptionService.StocktakeAudit.class);
        verify(batchStocktakeService).stocktake(eq(TENANT), eq(PRODUCT_ID), eq("wc-8f2b"),
                lines.capture(), audit.capture());
        assertThat(lines.getValue()).hasSize(1);
        assertThat(lines.getValue().get(0).getBatchId()).isEqualTo(BATCH_ID);
        assertThat(lines.getValue().get(0).getActualMeters()).isEqualByComparingTo("42");

        // 审计：operator = 姓名（工人请求在 resolveOperator() 里是 system ⇒ 必须显式给）
        assertThat(audit.getValue().operator()).isEqualTo(WORKER_NAME);
        assertThat(audit.getValue().notePrefix())
                .contains("工人库存修正", WORKER_NAME, WORKER_NO, "数量记错了", "裁过一截");

        // 回执四数原样透传
        assertThat(receipt.status()).isEqualTo(BatchStockViews.STOCKTAKE_APPLIED);
        assertThat(receipt.beforeMeters()).isEqualByComparingTo("45.5");
        assertThat(receipt.actualMeters()).isEqualByComparingTo("42");
        assertThat(receipt.deltaMeters()).isEqualByComparingTo("-3.5");
        assertThat(receipt.afterMeters()).isEqualByComparingTo("42");
        assertThat(receipt.productName()).isEqualTo("雪尼尔窗帘布");
        assertThat(receipt.workerNo()).isEqualTo(WORKER_NO);
    }

    @Test
    @DisplayName("② 零差异 / 幂等回放 ⇒ 状态原样透传（本类不改写、不补写）")
    void unchangedAndReplayedStatusesPassThrough() {
        when(batchStockService.remainingOfBatch(TENANT, BATCH_ID)).thenReturn(remaining("42"));
        when(batchStocktakeService.stocktake(any(), anyString(), anyString(), any(), any()))
                .thenReturn(new BatchStockViews.StocktakeResult("wc-a", PRODUCT_ID, 0, 1, 0,
                        BigDecimal.ZERO,
                        List.of(line(BatchStockViews.STOCKTAKE_UNCHANGED, "42", "42", "0", "42"))));

        assertThat(service.correct(TENANT, zhang(), request("42", "miscount", "a")).status())
                .isEqualTo(BatchStockViews.STOCKTAKE_UNCHANGED);

        when(batchStocktakeService.stocktake(any(), anyString(), anyString(), any(), any()))
                .thenReturn(new BatchStockViews.StocktakeResult("wc-b", PRODUCT_ID, 0, 0, 1,
                        BigDecimal.ZERO,
                        List.of(line(BatchStockViews.STOCKTAKE_REPLAYED, "45.5", "42", "0", "45.5"))));
        assertThat(service.correct(TENANT, zhang(), request("42", "damaged", "b")).status())
                .isEqualTo(BatchStockViews.STOCKTAKE_REPLAYED);
    }

    // ────────────────────────────────────────────── ② 准入（全部先于写入）

    @Test
    @DisplayName("③ 实盘为负 ⇒ 400 可行动文案，且不触达写入面")
    void negativeActualIsRejectedBeforeAnyWrite() {
        assertThatThrownBy(() -> service.correct(TENANT, zhang(), request("-1", "damaged", "x")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不能为负")
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getCode()).isEqualTo(WorkerBatchStockService.ERR_ACTUAL_NEGATIVE);
                    assertThat(be.getHttpStatus()).isEqualTo(400);
                });
        verify(batchStocktakeService, never()).stocktake(any(), any(), any(), any(), any());
        verify(batchStockService, never()).applyStocktake(any(), any(), any(), any());
    }

    @Test
    @DisplayName("④ 缺实盘 / 超 1 位小数 / 未知原因 / 缺幂等键 / 备注超长 ⇒ 422 且零写入")
    void malformedRequestsAreRejectedBeforeAnyWrite() {
        assertThatThrownBy(() -> service.correct(TENANT, zhang(), request(null, "miscount", "x")))
                .isInstanceOf(BusinessException.class).hasMessageContaining("实盘米数");
        assertThatThrownBy(() -> service.correct(TENANT, zhang(), request("42.55", "miscount", "x")))
                .isInstanceOf(BusinessException.class).hasMessageContaining("1 位小数");
        assertThatThrownBy(() -> service.correct(TENANT, zhang(), request("42", "because", "x")))
                .isInstanceOf(BusinessException.class).hasMessageContaining("修正原因");
        assertThatThrownBy(() -> service.correct(TENANT, zhang(), request("42", "miscount", null)))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getCode())
                        .isEqualTo(WorkerBatchStockService.ERR_REQUEST_ID));
        assertThatThrownBy(() -> service.correct(TENANT, zhang(), request("42", "miscount", "bad id")))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getCode())
                        .isEqualTo(WorkerBatchStockService.ERR_REQUEST_ID));

        WorkerBatchCorrectionRequest tooLongNote = request("42", "miscount", "x");
        tooLongNote.setNote("备".repeat(WorkerBatchStockService.MAX_NOTE_LENGTH + 1));
        assertThatThrownBy(() -> service.correct(TENANT, zhang(), tooLongNote))
                .isInstanceOf(BusinessException.class).hasMessageContaining("备注最多");

        verify(batchStocktakeService, never()).stocktake(any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("⑤ 批次不属于本租户 ⇒ 404（不触达写入面），不泄露别的租户有没有这个 id")
    void unknownBatchIs404() {
        when(batchStockService.remainingOfBatch(TENANT, BATCH_ID)).thenReturn(null);

        assertThatThrownBy(() -> service.correct(TENANT, zhang(), request("42", "miscount", "x")))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getCode()).isEqualTo(WorkerBatchStockService.ERR_BATCH_NOT_FOUND);
                    assertThat(be.getHttpStatus()).isEqualTo(404);
                });
        verify(batchStocktakeService, never()).stocktake(any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("⑥ 无工人身份 ⇒ 401（服务层 fail-closed，不只是控制器那一层）")
    void missingIdentityIs401() {
        assertThatThrownBy(() -> service.correct(TENANT, null, request("42", "miscount", "x")))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(401));
    }

    // ────────────────────────────────────────────── ③ 读面

    @Test
    @DisplayName("⑦ 搜批次 ⇒ 补品名 + 下发原因闭词表（端侧不写第二份选项）")
    void searchAddsProductNameAndReasons() {
        when(batchStockService.remainingPage(eq(TENANT), any(), any(), eq("PC"), eq(2L), eq(10L)))
                .thenReturn(PageResponse.of(1L, 2L, 10L, List.of(remaining("45.5"))));

        WorkerBatchStockViews.BatchPage page = service.search(TENANT, "PC", 2, 10);

        assertThat(page.items()).hasSize(1);
        assertThat(page.items().get(0).productName()).isEqualTo("雪尼尔窗帘布");
        assertThat(page.items().get(0).remainingMeters()).isEqualByComparingTo("45.5");
        assertThat(page.total()).isEqualTo(1);
        assertThat(page.reasons()).isEqualTo(WorkerBatchStockService.REASONS);
        assertThat(page.reasons()).extracting(WorkerBatchStockViews.Reason::code)
                .containsExactly("miscount", "damaged", "wrong_batch", "other");
    }

    @Test
    @DisplayName("⑧ 原因是**闭词表**：码与标签都非空且两两不同（端侧渲染按它，重复/空白 ⇒ 红）")
    void reasonsAreAClosedVocabulary() {
        assertThat(WorkerBatchStockService.REASONS).hasSizeGreaterThanOrEqualTo(4);
        assertThat(WorkerBatchStockService.REASONS)
                .allSatisfy(r -> assertThat(r.code()).isNotBlank())
                .allSatisfy(r -> assertThat(r.label()).isNotBlank());
        assertThat(WorkerBatchStockService.REASONS).extracting(WorkerBatchStockViews.Reason::code)
                .doesNotHaveDuplicates();
        assertThat(WorkerBatchStockService.REASONS).extracting(WorkerBatchStockViews.Reason::label)
                .doesNotHaveDuplicates();
    }
}
