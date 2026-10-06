// case_ids: PR-119

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.BatchStocktakeRequest;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.StockBatchConsumption;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchConsumptionMapper;
import com.migao.admin.mapper.StockBatchMapper;
import com.migao.admin.mapper.StockLedgerMapper;
import com.migao.admin.time.BusinessClock;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 按批次库存盘点（最小录入式，issue #5865）——**算账面判据**（装配与 HTTP 面在
 * {@code StockBatchControllerTest} / 真库面在 {@code BatchStocktakeRealDbTest}）。
 *
 * <p>本文件用**真服务 + 桩 mapper**（不是把两个服务都 mock 掉）：批次分录的落库形状
 * （{@code reason='stocktake'} / {@code stocktake_run_id} / {@code delta=实盘−余量} /
 * {@code planned=-delta}）与台账行形状（{@code reason=manual}、note 带批次号与盘前盘后）
 * 都是**本单的实现契约**，mock 掉就只剩「调了哪个方法」，那正是本仓反复踩过的假绿形态。</p>
 *
 * <p>七条红线逐条落判据（编号与 issue #5865 的「实现约束」一致）：
 * ① 不原地改 {@code stock_batches.quantity}（{@code stockBatchMapper} 零写调用）；
 * ② 批次分录与 SKU 库存同一事务（事务边界在 {@code BatchStocktakeService#stocktake} 上，
 * 真库面另有「第 2 行失败 ⇒ 第 1 行也不落」的注入式判据）；③ 来源可区分（{@code reason} + run id）；
 * ④ 禁负余量（实盘 &lt; 0 ⇒ 4xx；盘后 SKU 库存 &lt; 0 ⇒ 4xx）；
 * ⑤ {@code delta=0} ⇒ 零写入、重放不双记；⑥ 不静默取整（{@code 2.755} ⇒ 4xx）；
 * ⑦ 对账不因盘点变大（真库面判据）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("按批次库存盘点（issue #5865）")
class BatchStocktakeServiceTest {

    private static final Long TENANT = 1L;
    private static final String PRODUCT_ID = "prod-5865";
    private static final String RUN_ID = "PD-20261001-0001";
    private static final Long SKU_ID = 12L;

    @Mock private StockBatchMapper stockBatchMapper;
    @Mock private StockBatchConsumptionMapper consumptionMapper;
    @Mock private ProductSkuMapper productSkuMapper;
    @Mock private StockLedgerMapper stockLedgerMapper;

    private StockBatchConsumptionService batchService;
    private BatchStocktakeService service;

    @BeforeEach
    void setUp() {
        // `LambdaQueryWrapper` 要在 MyBatis-Plus 的实体元数据缓存里解析列名（生产由启动扫描建立；
        // 单类单跑的 mock 测试没有容器 ⇒ 显式初始化，否则 `.eq(实体::getX)` 抛
        // "can not find lambda cache"——同 KnowledgeCandidateMapperTest 的做法）。
        TableInfoHelper.initTableInfo(
                new MapperBuilderAssistant(new MybatisConfiguration(), ""),
                StockBatchConsumption.class);
        // 真服务 + 桩 mapper：批次分录的落库形状由**被测代码**决定，而不是由测试自己拼出来
        batchService = new StockBatchConsumptionService(stockBatchMapper, consumptionMapper,
                productSkuMapper, stockLedgerMapper, null, null, new BusinessClock());
        service = new BatchStocktakeService(batchService, productSkuMapper,
                new StockLedgerService(stockLedgerMapper, productSkuMapper));
        // 默认：该 run 没有任何已落账的盘点行（重放判据自己改桩）
        when(consumptionMapper.selectList(any())).thenReturn(List.of());
        // 默认：原子闸**本次生效**（影响 1 行）。返回 0 = 同 run × 批次已有一行 ⇒ 幂等回放
        // （issue #6301 的并发语义；那一条由真库判据 BatchStocktakeConcurrentRealDbTest 覆盖）
        when(consumptionMapper.insertStocktakeIfAbsent(any(StockBatchConsumption.class))).thenReturn(1);
        when(productSkuMapper.selectList(any())).thenReturn(List.of(sku(SKU_ID, "SKU-A", "60")));
    }

    // ── 夹具 ──────────────────────────────────────────────────────────────────

    private StockBatch batch(long id, String batchNo, String meters) {
        return StockBatch.builder()
                .id(id).tenantId(TENANT).batchNo(batchNo).productId(PRODUCT_ID)
                .skuId(SKU_ID).skuCode("SKU-A").inboundNo("RK-1").dyeLot("L1")
                .unitCost(new BigDecimal("12.5"))
                .quantity(new BigDecimal(meters)).receivedDate(LocalDate.of(2026, 9, 1))
                .build();
    }

    private ProductSku sku(Long id, String code, String stock) {
        return ProductSku.builder()
                .id(id).tenantId(TENANT).productId(PRODUCT_ID).skuCode(code)
                .stock(new BigDecimal(stock)).build();
    }

    private void stubBatches(StockBatch... batches) {
        when(stockBatchMapper.selectList(any())).thenReturn(List.of(batches));
    }

    /** Σdelta 桩（负 = 净扣减）；余量 = {@code stock_batches.quantity} + Σdelta。 */
    private void stubConsumed(long batchId, String deltaSum) {
        StockBatchConsumptionMapper.BatchDeltaSum sum = new StockBatchConsumptionMapper.BatchDeltaSum();
        sum.setBatchId(batchId);
        sum.setDeltaSum(new BigDecimal(deltaSum));
        when(consumptionMapper.sumDeltaByBatchIds(eq(TENANT), any())).thenReturn(List.of(sum));
    }

    private static BatchStocktakeRequest.Line line(long batchId, String meters) {
        BatchStocktakeRequest.Line l = new BatchStocktakeRequest.Line();
        l.setBatchId(batchId);
        l.setActualMeters(new BigDecimal(meters));
        return l;
    }

    private StockBatchConsumption capturedBatchEntry() {
        ArgumentCaptor<StockBatchConsumption> captor =
                ArgumentCaptor.forClass(StockBatchConsumption.class);
        verify(consumptionMapper).insertStocktakeIfAbsent(captor.capture());
        return captor.getValue();
    }

    private List<StockLedger> capturedLedgerRows() {
        ArgumentCaptor<StockLedger> captor = ArgumentCaptor.forClass(StockLedger.class);
        verify(stockLedgerMapper, times(1)).insert(captor.capture());
        return captor.getAllValues();
    }

    private void assertNoWrites() {
        verify(consumptionMapper, never()).insertStocktakeIfAbsent(any(StockBatchConsumption.class));
        verify(stockLedgerMapper, never()).insert(any(StockLedger.class));
        verify(productSkuMapper, never()).updateById(any(ProductSku.class));
        // 红线 ①：批次行**一字不改**（余量是派生值，改的是分录）
        verify(stockBatchMapper, never()).updateById(any(StockBatch.class));
        verify(stockBatchMapper, never()).insert(any(StockBatch.class));
        verify(stockBatchMapper, never()).deleteById(any(java.io.Serializable.class));
    }

    // ══════════════════════════════════ 判据 1 / 2：盘亏与盘盈

    @Test
    @DisplayName("判据1 盘亏：余量 60 → 实盘 58.5 ⇒ 分录 delta=-1.5 + SKU 库存 -1.5 + 台账一行")
    void shortfallWritesOneBatchEntryAndOneLedgerRow() {
        stubBatches(batch(7L, "PC-20260901-0001", "60"));
        stubConsumed(7L, "0");

        BatchStockViews.StocktakeResult result = service.stocktake(TENANT, PRODUCT_ID, RUN_ID,
                List.of(line(7L, "58.5")));

        // 读面回值：盘前/实盘/差异/盘后逐值可核（前端差异预览就是这三个数）
        assertThat(result.lines()).singleElement().satisfies(row -> {
            assertThat(row.beforeMeters()).isEqualByComparingTo("60");
            assertThat(row.actualMeters()).isEqualByComparingTo("58.5");
            assertThat(row.delta()).isEqualByComparingTo("-1.5");
            assertThat(row.afterMeters()).isEqualByComparingTo("58.5");
            assertThat(row.status()).isEqualTo(BatchStockViews.STOCKTAKE_APPLIED);
        });
        assertThat(result.changedCount()).isEqualTo(1);
        assertThat(result.totalDelta()).isEqualByComparingTo("-1.5");

        // 红线 ② + ③：批次分录 = stock_batch_consumptions 的一行，reason=stocktake、带 run id
        StockBatchConsumption entry = capturedBatchEntry();
        assertThat(entry.getReason()).isEqualTo(StockBatchConsumption.REASON_STOCKTAKE);
        assertThat(entry.getStocktakeRunId()).isEqualTo(RUN_ID);
        assertThat(entry.getDelta()).isEqualByComparingTo("-1.5");
        assertThat(entry.getBeforeQty()).isEqualByComparingTo("60");
        assertThat(entry.getAfterQty()).isEqualByComparingTo("58.5");
        // planned 与 delta 反向（沿用扣减行的符号约定）⇒ getSavedMeters 恰为 0（盘点不产生省料）
        assertThat(entry.getPlannedMeters()).isEqualByComparingTo("1.5");
        assertThat(entry.getFormulaMeters()).isEqualByComparingTo("1.5");
        assertThat(entry.getSavedMeters()).isEqualByComparingTo("0");
        // 与扣料**结构性不相邻**：三个扣料专属列在盘点行上必须是 null
        assertThat(entry.getProcessingOrderNo()).isNull();
        assertThat(entry.getOrderItemId()).isNull();
        assertThat(entry.getNote()).contains("PC-20260901-0001");

        // SKU 库存同步到实盘总数（同一事务内的第二本账）
        ArgumentCaptor<ProductSku> skuCaptor = ArgumentCaptor.forClass(ProductSku.class);
        verify(productSkuMapper).updateById(skuCaptor.capture());
        assertThat(skuCaptor.getValue().getStock()).isEqualByComparingTo("58.5");

        // 台账一行：reason=manual、note 含批次号与盘前盘后、before/after 首尾相接
        List<StockLedger> ledger = capturedLedgerRows();
        assertThat(ledger).singleElement().satisfies(row -> {
            assertThat(row.getReason()).isEqualTo(StockLedger.REASON_MANUAL);
            assertThat(row.getBeforeQty()).isEqualByComparingTo("60");
            assertThat(row.getAfterQty()).isEqualByComparingTo("58.5");
            assertThat(row.getDelta()).isEqualByComparingTo("-1.5");
            assertThat(row.getNote()).contains("PC-20260901-0001").contains("60").contains("58.5");
        });
    }

    @Test
    @DisplayName("判据2 盘盈：余量 58.5 → 实盘 60 ⇒ 分录 +1.5、SKU 库存 +1.5（对称）")
    void surplusIsSymmetric() {
        stubBatches(batch(7L, "PC-20260901-0001", "60"));
        stubConsumed(7L, "-1.5");
        when(productSkuMapper.selectList(any())).thenReturn(List.of(sku(SKU_ID, "SKU-A", "58.5")));

        BatchStockViews.StocktakeResult result = service.stocktake(TENANT, PRODUCT_ID, RUN_ID,
                List.of(line(7L, "60")));

        assertThat(result.totalDelta()).isEqualByComparingTo("1.5");
        StockBatchConsumption entry = capturedBatchEntry();
        assertThat(entry.getDelta()).isEqualByComparingTo("1.5");
        assertThat(entry.getBeforeQty()).isEqualByComparingTo("58.5");
        assertThat(entry.getAfterQty()).isEqualByComparingTo("60");
        assertThat(entry.getPlannedMeters()).isEqualByComparingTo("-1.5");
        ArgumentCaptor<ProductSku> skuCaptor = ArgumentCaptor.forClass(ProductSku.class);
        verify(productSkuMapper).updateById(skuCaptor.capture());
        assertThat(skuCaptor.getValue().getStock()).isEqualByComparingTo("60");
    }

    // ══════════════════════════════════ 判据 3 / 6：零写入与重放

    @Test
    @DisplayName("判据3 delta=0 ⇒ 零写入（分录、台账、SKU 库存都不动）")
    void zeroDeltaWritesNothing() {
        stubBatches(batch(7L, "PC-20260901-0001", "60"));
        stubConsumed(7L, "0");

        BatchStockViews.StocktakeResult result = service.stocktake(TENANT, PRODUCT_ID, RUN_ID,
                List.of(line(7L, "60")));

        assertThat(result.changedCount()).isZero();
        assertThat(result.unchangedCount()).isEqualTo(1);
        assertThat(result.totalDelta()).isEqualByComparingTo("0");
        assertThat(result.lines()).singleElement()
                .extracting(BatchStockViews.StocktakeLineResult::status)
                .isEqualTo(BatchStockViews.STOCKTAKE_UNCHANGED);
        assertNoWrites();
    }

    @Test
    @DisplayName("判据6 重放不双记：同一 run id 重跑 ⇒ 该批次跳过、分录/台账/SKU 库存都不动")
    void replayWithSameRunIdWritesNothing() {
        stubBatches(batch(7L, "PC-20260901-0001", "60"));
        stubConsumed(7L, "0");
        when(consumptionMapper.selectList(any())).thenReturn(List.of(existingStocktakeRow(7L, RUN_ID)));

        BatchStockViews.StocktakeResult result = service.stocktake(TENANT, PRODUCT_ID, RUN_ID,
                List.of(line(7L, "58.5")));

        assertThat(result.replayedCount()).isEqualTo(1);
        assertThat(result.changedCount()).isZero();
        assertThat(result.lines()).singleElement()
                .extracting(BatchStockViews.StocktakeLineResult::status)
                .isEqualTo(BatchStockViews.STOCKTAKE_REPLAYED);
        assertNoWrites();
    }

    private StockBatchConsumption existingStocktakeRow(long batchId, String runId) {
        return StockBatchConsumption.builder()
                .id(900L).tenantId(TENANT).batchId(batchId).batchNo("PC-20260901-0001")
                .productId(PRODUCT_ID).skuId(SKU_ID).skuCode("SKU-A")
                .delta(new BigDecimal("-1.5")).beforeQty(new BigDecimal("60"))
                .afterQty(new BigDecimal("58.5"))
                .formulaMeters(new BigDecimal("1.5")).plannedMeters(new BigDecimal("1.5"))
                .reason(StockBatchConsumption.REASON_STOCKTAKE).stocktakeRunId(runId)
                .operator("system").build();
    }

    // ══════════════════════════════════ 判据 5：非法值显式拒绝（fail-closed）

    @Test
    @DisplayName("判据5 非法实盘米数（-1 / 2.755）⇒ 4xx 且零写入")
    void rejectsNegativeAndOverPrecisionAndWritesNothing() {
        stubBatches(batch(7L, "PC-20260901-0001", "60"));
        stubConsumed(7L, "0");

        assertThatThrownBy(() -> service.stocktake(TENANT, PRODUCT_ID, RUN_ID, List.of(line(7L, "-1"))))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("实盘米数");
        assertThatThrownBy(() -> service.stocktake(TENANT, PRODUCT_ID, RUN_ID,
                List.of(line(7L, "2.755"))))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("1 位小数");
        assertThatThrownBy(() -> service.stocktake(TENANT, PRODUCT_ID, RUN_ID, List.of()))
                .isInstanceOf(BusinessException.class);
        assertThatThrownBy(() -> service.stocktake(TENANT, PRODUCT_ID, "  ", List.of(line(7L, "1"))))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("runId");

        assertNoWrites();
    }

    @Test
    @DisplayName("口径：盘后 SKU 库存不得为负（实盘 &lt; 差额）⇒ 4xx 且零写入")
    void refusesWhenSkuStockWouldGoNegative() {
        stubBatches(batch(7L, "PC-20260901-0001", "60"));
        stubConsumed(7L, "0");
        when(productSkuMapper.selectList(any())).thenReturn(List.of(sku(SKU_ID, "SKU-A", "1")));

        assertThatThrownBy(() -> service.stocktake(TENANT, PRODUCT_ID, RUN_ID, List.of(line(7L, "58.5"))))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("库存");
        assertNoWrites();
    }

    @Test
    @DisplayName("口径：批次不属于该货号 / 重复批次行 ⇒ 4xx 且零写入（不猜、不静默忽略）")
    void refusesUnknownBatchAndDuplicateLines() {
        stubBatches(batch(7L, "PC-20260901-0001", "60"));
        stubConsumed(7L, "0");

        assertThatThrownBy(() -> service.stocktake(TENANT, PRODUCT_ID, RUN_ID, List.of(line(99L, "1"))))
                .isInstanceOf(BusinessException.class);
        assertThatThrownBy(() -> service.stocktake(TENANT, PRODUCT_ID, RUN_ID,
                List.of(line(7L, "58.5"), line(7L, "58"))))
                .isInstanceOf(BusinessException.class);
        assertNoWrites();
    }

    // ══════════════════════════════════ 口径唯一 / 多批次

    @Test
    @DisplayName("余量口径唯一：盘前值取自派生余量（quantity 60 + Σdelta -1.5 = 58.5），不是批次行的 quantity")
    void usesDerivedRemainingNotBatchQuantity() {
        stubBatches(batch(7L, "PC-20260901-0001", "60"));
        stubConsumed(7L, "-1.5");

        BatchStockViews.StocktakeResult result = service.stocktake(TENANT, PRODUCT_ID, RUN_ID,
                List.of(line(7L, "60")));

        assertThat(result.lines()).singleElement()
                .extracting(BatchStockViews.StocktakeLineResult::beforeMeters)
                .isEqualTo(new BigDecimal("58.5"));
        assertThat(capturedBatchEntry().getDelta()).isEqualByComparingTo("1.5");
    }

    @Test
    @DisplayName("多批次一次提交：逐行分录 + SKU 库存按 Σdelta 一次更新（一个事务面的同一批写）")
    void multiBatchWritesOneEntryPerBatchAndOneSkuUpdate() {
        stubBatches(batch(7L, "PC-20260901-0001", "60"), batch(8L, "PC-20260901-0002", "10"));
        StockBatchConsumptionMapper.BatchDeltaSum a = new StockBatchConsumptionMapper.BatchDeltaSum();
        a.setBatchId(7L);
        a.setDeltaSum(BigDecimal.ZERO);
        StockBatchConsumptionMapper.BatchDeltaSum b = new StockBatchConsumptionMapper.BatchDeltaSum();
        b.setBatchId(8L);
        b.setDeltaSum(BigDecimal.ZERO);
        when(consumptionMapper.sumDeltaByBatchIds(eq(TENANT), any())).thenReturn(List.of(a, b));

        BatchStockViews.StocktakeResult result = service.stocktake(TENANT, PRODUCT_ID, RUN_ID,
                List.of(line(7L, "58.5"), line(8L, "8")));

        assertThat(result.changedCount()).isEqualTo(2);
        assertThat(result.totalDelta()).isEqualByComparingTo("-3.5");
        ArgumentCaptor<StockBatchConsumption> captor =
                ArgumentCaptor.forClass(StockBatchConsumption.class);
        verify(consumptionMapper, times(2)).insertStocktakeIfAbsent(captor.capture());
        assertThat(captor.getAllValues()).extracting(StockBatchConsumption::getStocktakeRunId)
                .containsOnly(RUN_ID);
        // 台账逐批次一行（含小数），**该 SKU 的库存链**首尾相接（60 → 58.5 → 56.5）
        ArgumentCaptor<StockLedger> ledgerCaptor = ArgumentCaptor.forClass(StockLedger.class);
        verify(stockLedgerMapper, times(2)).insert(ledgerCaptor.capture());
        assertThat(ledgerCaptor.getAllValues()).extracting(StockLedger::getAfterQty)
                .usingComparatorForType(BigDecimal::compareTo, BigDecimal.class)
                .containsExactly(new BigDecimal("58.5"), new BigDecimal("56.5"));
        assertThat(ledgerCaptor.getAllValues()).extracting(StockLedger::getNote)
                .allSatisfy(note -> assertThat(note).contains("盘前").contains("盘后"));
        ArgumentCaptor<ProductSku> skuCaptor = ArgumentCaptor.forClass(ProductSku.class);
        verify(productSkuMapper).updateById(skuCaptor.capture());
        assertThat(skuCaptor.getValue().getStock()).isEqualByComparingTo("56.5");
        // 红线 ①：批次行一字未改
        verify(stockBatchMapper, never()).updateById(any(StockBatch.class));
    }

    @Test
    @DisplayName("红线①：盘点全程不改 stock_batches.quantity（批次行零写）")
    void neverTouchesBatchRow() {
        stubBatches(batch(7L, "PC-20260901-0001", "60"));
        stubConsumed(7L, "0");

        service.stocktake(TENANT, PRODUCT_ID, RUN_ID, List.of(line(7L, "58.5")));

        verify(stockBatchMapper, never()).updateById(any(StockBatch.class));
        verify(stockBatchMapper, never()).update(any(StockBatch.class), any(Wrapper.class));
        verify(stockBatchMapper, never()).deleteById(any(java.io.Serializable.class));
    }
}
