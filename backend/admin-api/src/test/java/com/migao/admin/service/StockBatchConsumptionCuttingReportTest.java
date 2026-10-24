// case_ids: PG-092
package com.migao.admin.service;

import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.StockBatchConsumption;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchConsumptionMapper;
import com.migao.admin.mapper.StockBatchMapper;
import com.migao.admin.mapper.StockLedgerMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 裁剪报工确认批次（V191 / issue #7647）—— 批次账的**写面 ①b** 判据。
 *
 * <p>用户 2026-10-24 裁定（逐字）：「裁剪报工的时候需要工人裁剪的哪个批次，如果通过智能派单的就默认展示
 * 指定批次，允许工人改，如果没指定批次就需要工人手输才能完成报工，并且实时更新库存」。</p>
 *
 * <p>六条判据（每条都能红；红证 = 把对应分支改回改前形态 ⇒ 本条红）：</p>
 * <ol>
 *   <li><b>批次不存在 / 不是这一行的布</b> ⇒ 422，<b>零写入</b>（错别字不能落成账）；</li>
 *   <li><b>派工已指定 + 工人填的就是那一批</b> ⇒ <b>零写入</b>（不重复扣，排料省下的米数不动）；</li>
 *   <li><b>派工已指定 + 工人换了批次</b> ⇒ 两条分录（回补原批次 + 扣实裁批次），该行净额不变；</li>
 *   <li><b>派工未指定</b> ⇒ 按本次报工米数扣（实时更新库存），分次报工累计正确；</li>
 *   <li><b>余量不足</b> ⇒ <b>放行</b>（不挡工钱），余量如实为负 + 缺口显式回给调用方；</li>
 *   <li><b>作废回补按净额</b> ⇒ 换过批次的单作废后净额归零（不二次回补），纯派工单与改前逐值相同。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("批次账 · 裁剪报工确认批次（V191 / issue #7647）")
class StockBatchConsumptionCuttingReportTest {

    private static final Long TENANT = 1L;
    private static final Long SKU_ID = 12L;
    private static final String PRODUCT_ID = "prod-1";
    private static final String SKU_CODE = "SKU-A";
    private static final String PO_NO = "CSO261024-00001";
    private static final String ORDER_NO = "SO-1";
    private static final String ITEM_ID = "oi-1";

    @Mock private StockBatchMapper stockBatchMapper;
    @Mock private StockBatchConsumptionMapper consumptionMapper;
    @Mock private ProductSkuMapper productSkuMapper;
    @Mock private StockLedgerMapper stockLedgerMapper;
    @Mock private CraftCalcConfigService craftCalcConfigService;

    @InjectMocks private StockBatchConsumptionService service;

    // ── 夹具 ──────────────────────────────────────────────────────────────────

    private StockBatch batch(long id, String batchNo, String meters) {
        return StockBatch.builder()
                .id(id).tenantId(TENANT).batchNo(batchNo).productId(PRODUCT_ID)
                .skuId(SKU_ID).skuCode(SKU_CODE).inboundNo("RK-1").dyeLot("L1")
                .unitCost(new BigDecimal("12.5")).quantity(new BigDecimal(meters))
                .receivedDate(LocalDate.of(2026, 10, 1)).deleted(0).build();
    }

    /** 台账里已有的一行（delta 带符号：负 = 扣减、正 = 回补）。 */
    private StockBatchConsumption row(long id, long batchId, String batchNo, String delta, String reason) {
        BigDecimal signed = new BigDecimal(delta);
        return StockBatchConsumption.builder()
                .id(id).tenantId(TENANT).batchId(batchId).batchNo(batchNo).productId(PRODUCT_ID)
                .skuId(SKU_ID).skuCode(SKU_CODE)
                .delta(signed)
                .beforeQty(new BigDecimal("99")).afterQty(new BigDecimal("99"))
                .formulaMeters(signed.negate()).plannedMeters(signed.negate())
                .unitCost(new BigDecimal("12.5"))
                .reason(reason).processingOrderNo(PO_NO).orderNo(ORDER_NO).orderItemId(ITEM_ID)
                .operator("u1").build();
    }

    /** 余量派生桩：Σdelta = 0 ⇒ 余量 = 批次入库量。 */
    private void stubNoPriorDelta() {
        when(consumptionMapper.sumDeltaByBatchIds(eq(TENANT), any())).thenReturn(List.of());
    }

    private void stubExistingRows(StockBatchConsumption... rows) {
        when(consumptionMapper.selectList(any())).thenReturn(List.of(rows));
    }

    private List<StockBatchConsumption> capturedRows(int expected) {
        ArgumentCaptor<StockBatchConsumption> captor =
                ArgumentCaptor.forClass(StockBatchConsumption.class);
        verify(consumptionMapper, org.mockito.Mockito.times(expected)).insert(captor.capture());
        return captor.getAllValues();
    }

    private StockBatchConsumptionService.CuttingReportResult apply(StockBatch target, String batchNo,
                                                                  String meters) {
        when(stockBatchMapper.selectList(any())).thenReturn(List.of(target));
        return service.applyCuttingReport(TENANT, PO_NO, ORDER_NO, ITEM_ID, PRODUCT_ID, SKU_ID, SKU_CODE,
                batchNo, new BigDecimal(meters));
    }

    // ── ① 校验：批次不存在 / 不是这一行的布 ⇒ 422 + 零写入 ──────────────────────

    @Test
    @DisplayName("🔴 批次不存在 ⇒ 422 BATCH_NOT_FOUND，且一行都不落（错别字不能变成账）")
    void unknownBatchIsRejectedWithoutWriting() {
        when(stockBatchMapper.selectList(any())).thenReturn(List.of());

        assertThatThrownBy(() -> service.applyCuttingReport(TENANT, PO_NO, ORDER_NO, ITEM_ID, PRODUCT_ID,
                SKU_ID, SKU_CODE, "PC-不存在", new BigDecimal("11")))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "BATCH_NOT_FOUND");
        verify(consumptionMapper, never()).insert(any(StockBatchConsumption.class));
    }

    @Test
    @DisplayName("🔴 批次属于别的商品 / 别的 SKU ⇒ 422 BATCH_SKU_MISMATCH，且零写入")
    void foreignSkuBatchIsRejectedWithoutWriting() {
        StockBatch other = StockBatch.builder()
                .id(9L).tenantId(TENANT).batchNo("PC-OTHER").productId("prod-2")
                .skuId(99L).skuCode("SKU-Z").quantity(new BigDecimal("50")).deleted(0).build();
        when(stockBatchMapper.selectList(any())).thenReturn(List.of(other));

        assertThatThrownBy(() -> service.applyCuttingReport(TENANT, PO_NO, ORDER_NO, ITEM_ID, PRODUCT_ID,
                SKU_ID, SKU_CODE, "PC-OTHER", new BigDecimal("11")))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "BATCH_SKU_MISMATCH");
        verify(consumptionMapper, never()).insert(any(StockBatchConsumption.class));
    }

    // ── ② 派工已指定 + 同一批 ⇒ 零写入 ─────────────────────────────────────────

    @Test
    @DisplayName("派工指定过批次、工人填的就是那一批 ⇒ 零写入（不重复扣，排料省下的米数不动）")
    void sameBatchAsDispatchWritesNothing() {
        StockBatch a = batch(1L, "PC-A", "20");
        StockBatchConsumption consumed = row(1L, 1L, "PC-A", "-10",
                StockBatchConsumption.REASON_PROCESSING_ORDER);
        stubExistingRows(consumed);
        stubNoPriorDeltaFor(consumed); // Σdelta = −10 ⇒ 余量 20 − 10 = 10

        StockBatchConsumptionService.CuttingReportResult result = apply(a, "PC-A", "10");

        verify(consumptionMapper, never()).insert(any(StockBatchConsumption.class));
        assertThat(result.batchNo()).isEqualTo("PC-A");
        // 余量 = 20 + (−10) = 10（派工已经扣过 ⇒ 报工不再扣）
        assertThat(result.batchRemaining()).isEqualByComparingTo("10");
        assertThat(result.shortageMeters()).isNull();
    }

    // ── ③ 派工已指定 + 换了批次 ⇒ 回补 + 扣减（净额不变） ─────────────────────

    @Test
    @DisplayName("派工指定 A、工人实裁 B ⇒ 同一事务两条分录（+A 回补、−B 扣减），该行净额不变")
    void differentBatchMovesTheNet() {
        StockBatch a = batch(1L, "PC-A", "20");
        StockBatch b = batch(2L, "PC-B", "50");
        stubNoPriorDelta();
        stubExistingRows(row(1L, 1L, "PC-A", "-10", StockBatchConsumption.REASON_PROCESSING_ORDER));
        when(stockBatchMapper.selectOne(any())).thenReturn(a);

        StockBatchConsumptionService.CuttingReportResult result = apply(b, "PC-B", "10");

        List<StockBatchConsumption> written = capturedRows(2);
        // 先回补原批次（+10），再扣实裁批次（−10）—— 顺序即「余量不会先变负的理由」
        assertThat(written.get(0).getBatchNo()).isEqualTo("PC-A");
        assertThat(written.get(0).getDelta()).isEqualByComparingTo("10");
        assertThat(written.get(1).getBatchNo()).isEqualTo("PC-B");
        assertThat(written.get(1).getDelta()).isEqualByComparingTo("-10");
        written.forEach(r -> assertThat(r.getReason())
                .isEqualTo(StockBatchConsumption.REASON_CUTTING_REPORT));
        // 净额不变：该行消耗仍是 10 米，只是从 A 搬到 B
        assertThat(result.batchNo()).isEqualTo("PC-B");
        assertThat(result.batchRemaining()).isEqualByComparingTo("40");
        assertThat(result.shortageMeters()).isNull();
    }

    // ── ④ 派工未指定 ⇒ 按本次报工米数扣（实时更新库存） ────────────────────────

    @Test
    @DisplayName("派工未指定批次 ⇒ 报工时按本次米数扣该批次（分次报工累计正确）")
    void unassignedDeductsReportedMeters() {
        StockBatch b = batch(2L, "PC-B", "50");
        stubNoPriorDelta();
        stubExistingRows(); // 该行从来没有派工族行

        StockBatchConsumptionService.CuttingReportResult result = apply(b, "PC-B", "11");

        List<StockBatchConsumption> written = capturedRows(1);
        assertThat(written.get(0).getDelta()).isEqualByComparingTo("-11");
        assertThat(written.get(0).getReason())
                .isEqualTo(StockBatchConsumption.REASON_CUTTING_REPORT);
        assertThat(result.batchRemaining()).isEqualByComparingTo("39");

        // 第二次分次报工（同一批）⇒ 再扣这一次的米数（累计 11 + 4 = 15，不是停在 11）
        stubExistingRows(row(2L, 2L, "PC-B", "-11", StockBatchConsumption.REASON_CUTTING_REPORT));
        stubNoPriorDeltaFor(row(2L, 2L, "PC-B", "-11", StockBatchConsumption.REASON_CUTTING_REPORT));
        StockBatchConsumptionService.CuttingReportResult second = apply(b, "PC-B", "4");
        List<StockBatchConsumption> all = capturedRows(2);
        assertThat(all.get(1).getDelta()).isEqualByComparingTo("-4");
        assertThat(second.batchRemaining()).isEqualByComparingTo("35");
    }

    /** 第二次调用时 `remainingMeters` 要看到第一次的扣减（Σdelta = −11 ⇒ 余量 39）。 */
    private void stubNoPriorDeltaFor(StockBatchConsumption first) {
        StockBatchConsumptionMapper.BatchDeltaSum sum = new StockBatchConsumptionMapper.BatchDeltaSum();
        sum.setBatchId(first.getBatchId());
        sum.setDeltaSum(first.getDelta());
        when(consumptionMapper.sumDeltaByBatchIds(eq(TENANT), any())).thenReturn(List.of(sum));
    }

    // ── ⑤ 余量不足 ⇒ 放行 + 显式缺口 ───────────────────────────────────────────

    @Test
    @DisplayName("🔴 余量不足 ⇒ 报工照常（不挡工钱），余量如实为负 + 缺口显式回给调用方")
    void insufficientStockIsAllowedWithExplicitShortage() {
        StockBatch b = batch(2L, "PC-B", "5");
        stubNoPriorDelta();
        stubExistingRows();

        StockBatchConsumptionService.CuttingReportResult result = apply(b, "PC-B", "11");

        List<StockBatchConsumption> written = capturedRows(1);
        assertThat(written.get(0).getDelta()).isEqualByComparingTo("-11");
        assertThat(written.get(0).getAfterQty()).isEqualByComparingTo("-6"); // 负余量如实落账
        assertThat(result.batchRemaining()).isEqualByComparingTo("-6");
        assertThat(result.shortageMeters()).isEqualByComparingTo("6");
    }

    // ── ⑥ 作废回补按净额 ⇒ 换过批次的单也能归零 ────────────────────────────────

    @Test
    @DisplayName("🔴 换过批次的单作废 ⇒ 按净额回补（净额归零，不二次回补）；重跑零写入")
    void reverseRestoresNetToZeroAfterBatchMove() {
        StockBatch a = batch(1L, "PC-A", "20");
        StockBatch b = batch(2L, "PC-B", "50");
        stubNoPriorDelta();
        // 派工 A 扣 10 → 报工纠偏：回补 A 10、扣 B 10
        stubExistingRows(
                row(1L, 1L, "PC-A", "-10", StockBatchConsumption.REASON_PROCESSING_ORDER),
                row(2L, 1L, "PC-A", "10", StockBatchConsumption.REASON_CUTTING_REPORT),
                row(3L, 2L, "PC-B", "-10", StockBatchConsumption.REASON_CUTTING_REPORT));
        when(stockBatchMapper.selectList(any())).thenReturn(List.of(a, b));

        int reversed = service.reverse(TENANT, PO_NO, ORDER_NO, "加工单作废");

        assertThat(reversed).isEqualTo(1);
        List<StockBatchConsumption> written = capturedRows(1);
        // A 的净额已是 0（派工 −10 + 回补 +10）⇒ 不再回补；B 净额 10 ⇒ 回补 +10
        assertThat(written.get(0).getBatchNo()).isEqualTo("PC-B");
        assertThat(written.get(0).getDelta()).isEqualByComparingTo("10");
        assertThat(written.get(0).getReason())
                .isEqualTo(StockBatchConsumption.REASON_PROCESSING_ORDER_CANCELLED);
        assertThat(written.get(0).getFormulaMeters()).isEqualByComparingTo("-10");

        // 可重跑：把刚写的回补行也算进净额（净额归零）⇒ 第二次一行都不写
        stubExistingRows(
                row(1L, 1L, "PC-A", "-10", StockBatchConsumption.REASON_PROCESSING_ORDER),
                row(2L, 1L, "PC-A", "10", StockBatchConsumption.REASON_CUTTING_REPORT),
                row(3L, 2L, "PC-B", "-10", StockBatchConsumption.REASON_CUTTING_REPORT),
                row(4L, 2L, "PC-B", "10", StockBatchConsumption.REASON_PROCESSING_ORDER_CANCELLED));
        assertThat(service.reverse(TENANT, PO_NO, ORDER_NO, "加工单作废")).isZero();
    }

    @Test
    @DisplayName("🔴 报工换批后工人读面的批次跟着换（改前会返回「第一行见到的 A」+ B 的米数）")
    void assignmentsFollowTheBatchAfterAReportMove() {
        stubExistingRows(
                row(1L, 1L, "PC-A", "-10", StockBatchConsumption.REASON_PROCESSING_ORDER),
                row(2L, 1L, "PC-A", "10", StockBatchConsumption.REASON_CUTTING_REPORT),
                row(3L, 2L, "PC-B", "-10", StockBatchConsumption.REASON_CUTTING_REPORT));

        Map<String, StockBatchConsumptionService.BatchAssignment> moved =
                service.assignmentsOf(TENANT, PO_NO);

        assertThat(moved).containsKey(ITEM_ID);
        assertThat(moved.get(ITEM_ID).batchNo()).isEqualTo("PC-B");
        assertThat(moved.get(ITEM_ID).meters()).isEqualByComparingTo("10");
    }

    @Test
    @DisplayName("纯派工单的指派读数与改前逐值相同（批次 A、净额 10 米）")
    void assignmentsKeepPureDispatchBehavior() {
        stubExistingRows(row(1L, 1L, "PC-A", "-10", StockBatchConsumption.REASON_PROCESSING_ORDER));

        Map<String, StockBatchConsumptionService.BatchAssignment> out = service.assignmentsOf(TENANT, PO_NO);

        assertThat(out.get(ITEM_ID).batchNo()).isEqualTo("PC-A");
        assertThat(out.get(ITEM_ID).meters()).isEqualByComparingTo("10");
    }

    @Test
    @DisplayName("纯派工单作废 ⇒ 回补量与改前逐值相同（+10，两个米数取相反数）")
    void reverseKeepsPureDispatchBehavior() {
        StockBatch a = batch(1L, "PC-A", "20");
        stubNoPriorDelta();
        stubExistingRows(row(1L, 1L, "PC-A", "-10", StockBatchConsumption.REASON_PROCESSING_ORDER));
        when(stockBatchMapper.selectList(any())).thenReturn(List.of(a));

        assertThat(service.reverse(TENANT, PO_NO, ORDER_NO, "加工单作废")).isEqualTo(1);

        List<StockBatchConsumption> written = capturedRows(1);
        assertThat(written.get(0).getDelta()).isEqualByComparingTo("10");
        assertThat(written.get(0).getFormulaMeters()).isEqualByComparingTo("-10");
        assertThat(written.get(0).getPlannedMeters()).isEqualByComparingTo("-10");
    }
}
