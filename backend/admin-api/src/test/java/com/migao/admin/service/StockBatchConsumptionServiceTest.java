package com.migao.admin.service;

// case_ids: PR-055, PR-065, PR-063

import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.StockBatchConsumption;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchConsumptionMapper;
import com.migao.admin.mapper.StockBatchMapper;
import com.migao.admin.mapper.StockLedgerMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
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

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 批次消耗台账服务（V116，issue #5145 阶段 1）。
 *
 * <p>本文件是「派工即扣 / 不重复扣 / 对称回补 / 缺料不静默 / 对账可读 / 分布可算」六条判据的
 * **算账面**判据（装配与顺序在 {@code ProcessingOrderServiceTest}）。
 * 全部用**小数**夹具（2.7 / 0.5 / 0.2）：整数场景是这些判据的退化情形，
 * 只测整数等于没测（#5063 / V115 的教训）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("批次消耗台账服务（V116 / issue #5145 阶段 1）")
class StockBatchConsumptionServiceTest {

    private static final Long TENANT = 1L;
    private static final Long SKU_ID = 12L;
    private static final String PRODUCT_ID = "prod-1";

    @Mock private StockBatchMapper stockBatchMapper;
    @Mock private StockBatchConsumptionMapper consumptionMapper;
    @Mock private ProductSkuMapper productSkuMapper;
    @Mock private StockLedgerMapper stockLedgerMapper;
    /** 排料定尺要一个「上下卷边」—— 走算料配置的**单一读面**（V119 / issue #5158）。 */
    @Mock private CraftCalcConfigService craftCalcConfigService;

    @InjectMocks private StockBatchConsumptionService service;

    // ── 夹具 ──────────────────────────────────────────────────────────────────

    private StockBatch batch(long id, String batchNo, String meters) {
        return StockBatch.builder()
                .id(id).tenantId(TENANT).batchNo(batchNo).productId(PRODUCT_ID)
                .skuId(SKU_ID).skuCode("SKU-A").inboundNo("RK-1").dyeLot("L1")
                // 当时均价 12.5 元/米（V119 的快照源；saved_amount = saved_meters × 它）
                .unitCost(new BigDecimal("12.5"))
                .quantity(new BigDecimal(meters)).receivedDate(LocalDate.of(2026, 9, 1))
                .build();
    }

    private void stubBatches(StockBatch... batches) {
        when(stockBatchMapper.selectList(any())).thenReturn(List.of(batches));
    }

    /** Σdelta 桩（负 = 净扣减）；余量 = stock_batches.quantity + Σdelta。 */
    private void stubConsumed(long batchId, String deltaSum) {
        StockBatchConsumptionMapper.BatchDeltaSum sum = new StockBatchConsumptionMapper.BatchDeltaSum();
        sum.setBatchId(batchId);
        sum.setDeltaSum(new BigDecimal(deltaSum));
        when(consumptionMapper.sumDeltaByBatchIds(eq(TENANT), any())).thenReturn(List.of(sum));
    }

    private StockBatchConsumption consumption(long batchId, String batchNo, long id,
                                              String orderItemId, String delta, String before, String after,
                                              String reason) {
        BigDecimal signed = new BigDecimal(delta);
        return StockBatchConsumption.builder()
                .id(id).tenantId(TENANT).batchId(batchId).batchNo(batchNo).productId(PRODUCT_ID)
                .skuId(SKU_ID).skuCode("SKU-A")
                .delta(signed).beforeQty(new BigDecimal(before)).afterQty(new BigDecimal(after))
                // 两个米数 = −delta（V119 起的历史行口径）；均价 12.5 = 当时快照
                .formulaMeters(signed.negate()).plannedMeters(signed.negate())
                .unitCost(new BigDecimal("12.5"))
                .reason(reason).processingOrderNo("JG-1").orderNo("ORD-1").orderItemId(orderItemId)
                .operator("u1").build();
    }

    private StockBatchConsumptionService.Designation designation(String itemId, String batchNo, String meters) {
        return new StockBatchConsumptionService.Designation(
                itemId, PRODUCT_ID, "SKU-A", batchNo, new BigDecimal(meters), null, null, null);
    }

    /** **定高买宽**的派工行（一块 = 整窗；占门幅宽 = 窗高 + 上下卷边）。 */
    private StockBatchConsumptionService.Designation fixedHeight(String itemId, String batchNo,
                                                                 String meters, String height) {
        return new StockBatchConsumptionService.Designation(itemId, PRODUCT_ID, "SKU-A", batchNo,
                new BigDecimal(meters), "定高买宽", new BigDecimal(height), null);
    }

    /** **定宽买高**的派工行（一块 = 每一幅；幅数 = 引擎的 `panels` 输出）。 */
    private StockBatchConsumptionService.Designation fixedWidth(String itemId, String batchNo,
                                                                String meters, int panels) {
        return new StockBatchConsumptionService.Designation(itemId, PRODUCT_ID, "SKU-A", batchNo,
                new BigDecimal(meters), "定宽买高", new BigDecimal("1.1"), panels);
    }

    /** 上下卷边桩（引擎默认 0.3）；传 {@code null} = 取不到（fail-soft ⇒ 不排料）。 */
    private void stubHemMargin(String value) {
        when(craftCalcConfigService.hemMarginOrNull(TENANT))
                .thenReturn(value == null ? null : new BigDecimal(value));
    }

    /** 批次 SKU 的门幅（{@code "2.8米"} / {@code "2.8"} 两种存量形态都要能解析）。 */
    private void stubDoorWidth(String doorWidth) {
        when(productSkuMapper.selectList(any())).thenReturn(List.of(ProductSku.builder()
                .id(SKU_ID).tenantId(TENANT).productId(PRODUCT_ID)
                .doorWidth(doorWidth).skuCode("SKU-A").build()));
    }

    // ── 派工扣减：plan（只读校验）─────────────────────────────────────────────

    @Nested
    @DisplayName("plan —— 缺料 fail-closed")
    class Plan {

        @Test
        @DisplayName("不指派任何批次 ⇒ 空计划，一个查询都不发（行为与今天逐字相同）")
        void emptyDesignationsProduceEmptyPlan() {
            assertThat(service.plan(TENANT, List.of())).isEmpty();
            verifyNoInteractions(stockBatchMapper, consumptionMapper);
        }

        @Test
        @DisplayName("余量足够 ⇒ 计划给出该批次的剩余量与扣减米数（2.7 米小数逐值可比）")
        void sufficientBatchPlansDeduction() {
            stubBatches(batch(77L, "PC-1", "60"));
            stubConsumed(77L, "-2.7"); // 此前已扣 2.7 ⇒ 余量 57.3

            var plan = service.plan(TENANT, List.of(designation("item-1", "PC-1", "2.7")));

            assertThat(plan).hasSize(1);
            assertThat(plan.get(0).batchNo()).isEqualTo("PC-1");
            assertThat(plan.get(0).meters()).isEqualByComparingTo("2.7");
            assertThat(plan.get(0).remainingBefore()).isEqualByComparingTo("57.3");
            assertThat(plan.get(0).orderItemId()).isEqualTo("item-1");
            assertThat(plan.get(0).skuId()).isEqualTo(SKU_ID);
        }

        @Test
        @DisplayName("余量不足 ⇒ 显式拒绝 + 可行动建议（列出同 SKU 其它可用批次），绝不静默少扣")
        void insufficientBatchFailsClosedWithActionableHint() {
            when(stockBatchMapper.selectList(any()))
                    .thenReturn(List.of(batch(77L, "PC-1", "0.5"), batch(78L, "PC-2", "30")));
            when(consumptionMapper.sumDeltaByBatchIds(eq(TENANT), any())).thenReturn(List.of());

            assertThatThrownBy(() -> service.plan(TENANT, List.of(designation("item-1", "PC-1", "2.7"))))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("余量不足")
                    .hasMessageContaining("0.5")
                    .hasMessageContaining("2.7")
                    .extracting(e -> ((BusinessException) e).getCode())
                    .isEqualTo(StockBatchConsumptionService.ERR_BATCH_STOCK_INSUFFICIENT);
            // 建议必须**可行动**：说出还能用哪个批次、剩多少
            assertThatThrownBy(() -> service.plan(TENANT, List.of(designation("item-1", "PC-1", "2.7"))))
                    .extracting(e -> ((BusinessException) e).getSuggestion())
                    .asString()
                    .contains("PC-2").contains("30");
        }

        @Test
        @DisplayName("同一批次被两行指定 ⇒ 按累积判余量（0.5+2.3 > 2.6 ⇒ 拒）")
        void cumulativeJudgementAcrossLines() {
            stubBatches(batch(77L, "PC-1", "2.6"));
            when(consumptionMapper.sumDeltaByBatchIds(eq(TENANT), any())).thenReturn(List.of());

            assertThatThrownBy(() -> service.plan(TENANT, List.of(
                    designation("item-1", "PC-1", "0.5"),
                    designation("item-2", "PC-1", "2.3"))))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("余量不足");
        }

        @Test
        @DisplayName("累积足够时逐行递减剩余量（2.6 − 0.5 = 2.1 后，第二行 before = 2.1）")
        void cumulativeRemainingIsDecremented() {
            stubBatches(batch(77L, "PC-1", "2.6"));
            when(consumptionMapper.sumDeltaByBatchIds(eq(TENANT), any())).thenReturn(List.of());

            var plan = service.plan(TENANT, List.of(
                    designation("item-1", "PC-1", "0.5"),
                    designation("item-2", "PC-1", "2.1")));

            assertThat(plan.get(0).remainingBefore()).isEqualByComparingTo("2.6");
            assertThat(plan.get(1).remainingBefore()).isEqualByComparingTo("2.1");
        }

        @Test
        @DisplayName("批次不存在 / 不属于该租户 ⇒ 显式拒绝（不静默跳过）")
        void unknownBatchIsRejected() {
            stubBatches();
            when(consumptionMapper.sumDeltaByBatchIds(eq(TENANT), any())).thenReturn(List.of());

            assertThatThrownBy(() -> service.plan(TENANT, List.of(designation("item-1", "PC-X", "2.7"))))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("不存在或不属于当前租户")
                    .extracting(e -> ((BusinessException) e).getCode())
                    .isEqualTo(StockBatchConsumptionService.ERR_BATCH_NOT_FOUND);
        }

        @Test
        @DisplayName("批次属于另一个 SKU ⇒ 显式拒绝（指定错了货）")
        void skuMismatchIsRejected() {
            StockBatch other = batch(77L, "PC-1", "60");
            other.setSkuCode("SKU-B");
            stubBatches(other);
            stubConsumed(77L, "0");

            assertThatThrownBy(() -> service.plan(TENANT, List.of(designation("item-1", "PC-1", "2.7"))))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("SKU")
                    .extracting(e -> ((BusinessException) e).getCode())
                    .isEqualTo(StockBatchConsumptionService.ERR_BATCH_SKU_MISMATCH);
        }
    }

    // ── 排料接线（V119 / issue #5158）───────────────────────────────────────────

    /**
     * 「省料」真正产生的地方：扣减米数 = 排料口径。
     *
     * <p>判据全部用**可并排 / 不可并排**的对照读数（不是「调用了哪个方法」）：不接线时
     * 两扇矮窗各扣 3 米（合计 6），接线后合计 3 —— 差额只能来自
     * {@link CuttingPlanCalculator} 的装箱结果。</p>
     */
    @Nested
    @DisplayName("排料接线 —— 扣减按排料结果落账（V119 / issue #5158）")
    class CuttingPlanWiring {

        @Test
        @DisplayName("判据1 并排成立：门幅 2.8 / 窗高各 1.1 / 各需 3 米 ⇒ 合计扣 3 米（不是 6 米）")
        void pairableSmallWindowsAreDeductedOnce() {
            stubBatches(batch(77L, "PC-1", "60"));
            stubConsumed(77L, "0");
            stubHemMargin("0.3");
            stubDoorWidth("2.8米");

            var plan = service.plan(TENANT, List.of(
                    fixedHeight("item-1", "PC-1", "3", "1.1"),
                    fixedHeight("item-2", "PC-1", "3", "1.1")));

            assertThat(plan).hasSize(2);
            // 每行：公式 3 米；排料后每行分摊 = 3 × 3/6 = 1.5（组应领 3 = 行长 max(3,3)，两块各占 1.4 门幅）
            assertThat(plan).allSatisfy(d -> {
                assertThat(d.formulaMeters()).isEqualByComparingTo("3");
                assertThat(d.plannedMeters()).isEqualByComparingTo("1.5");
                assertThat(d.meters()).as("实际扣减 = 排料口径").isEqualByComparingTo("1.5");
            });
            BigDecimal deducted = StockQuantity.sum(
                    plan.stream().map(StockBatchConsumptionService.Deduction::meters).toList());
            assertThat(deducted).as("🔴 本单的核心读数：合计扣 3 米（不接线时是 6 米）")
                    .isEqualByComparingTo("3");
            assertThat(StockQuantity.sum(
                    plan.stream().map(StockBatchConsumptionService.Deduction::formulaMeters).toList()))
                    .as("公式口径合计仍是 6（两个米数都要能读出来）").isEqualByComparingTo("6");
        }

        @Test
        @DisplayName("判据1' 定宽买高并排：两扇单开窄窗（各 1.4 米）⇒ 合计扣 1.4 米（不是 2.8）")
        void pairableNarrowWindowsShareOneRow() {
            stubBatches(batch(77L, "PC-1", "60"));
            stubConsumed(77L, "0");
            stubHemMargin("0.3");
            stubDoorWidth("2.8");

            var plan = service.plan(TENANT, List.of(
                    fixedWidth("item-1", "PC-1", "1.4", 1),
                    fixedWidth("item-2", "PC-1", "1.4", 1)));

            assertThat(plan).allSatisfy(d -> assertThat(d.formulaMeters()).isEqualByComparingTo("1.4"));
            assertThat(StockQuantity.sum(
                    plan.stream().map(StockBatchConsumptionService.Deduction::meters).toList()))
                    .as("两块各占 1.4 门幅（合计 2.8 ✓）⇒ 1 行 / 领 1.4 米").isEqualByComparingTo("1.4");
        }

        @Test
        @DisplayName("判据2 不倒退：不可并排（窗高 2.7 + 卷边 0.3 > 门幅 2.8）⇒ 逐值等于公式米数、saved = 0")
        void nonPairableKeepsFormulaMetersExactly() {
            stubBatches(batch(77L, "PC-1", "60"));
            stubConsumed(77L, "0");
            stubHemMargin("0.3");
            stubDoorWidth("2.8");

            var plan = service.plan(TENANT, List.of(
                    fixedHeight("item-1", "PC-1", "2.7", "2.7"),
                    fixedHeight("item-2", "PC-1", "2.7", "2.7")));

            assertThat(plan).hasSize(2);
            assertThat(plan).allSatisfy(d -> {
                assertThat(d.formulaMeters()).isEqualByComparingTo("2.7");
                assertThat(d.plannedMeters()).as("宁可为 0，不许估").isEqualByComparingTo("2.7");
                assertThat(d.formulaMeters().subtract(d.plannedMeters())).isEqualByComparingTo("0");
            });
        }

        @Test
        @DisplayName("🔴 不虚报：跨批次（不同卷）即使门幅相同也**不得**成组（否则省的是假数）")
        void differentBatchesAreNeverPooledTogether() {
            StockBatch b2 = batch(78L, "PC-2", "60");
            stubBatches(batch(77L, "PC-1", "60"), b2);
            when(consumptionMapper.sumDeltaByBatchIds(eq(TENANT), any())).thenReturn(List.of());
            stubHemMargin("0.3");
            stubDoorWidth("2.8");

            var plan = service.plan(TENANT, List.of(
                    fixedHeight("item-1", "PC-1", "3", "1.1"),
                    fixedHeight("item-2", "PC-2", "3", "1.1")));

            assertThat(plan).allSatisfy(d -> assertThat(d.plannedMeters())
                    .as("两块料在两卷上 ⇒ 各自都要单独占一段卷长").isEqualByComparingTo("3"));
        }

        @Test
        @DisplayName("取不到上下卷边 / 工艺未知 / 缺定尺输入 ⇒ 一律退回公式口径（不猜，saved = 0）")
        void missingInputsFallBackToFormula() {
            stubBatches(batch(77L, "PC-1", "60"));
            stubConsumed(77L, "0");
            stubDoorWidth("2.8米");

            stubHemMargin(null); // 算料配置取不到 ⇒ 不排料
            assertThat(service.plan(TENANT, List.of(
                    fixedHeight("item-1", "PC-1", "3", "1.1"),
                    fixedHeight("item-2", "PC-1", "3", "1.1"))))
                    .allSatisfy(d -> assertThat(d.plannedMeters()).isEqualByComparingTo("3"));

            stubHemMargin("0.3");
            // 加工类型未知 ⇒ 不猜工艺（猜错会把整窗拆成多幅 ⇒ 少领）
            assertThat(service.plan(TENANT, List.of(
                    designation("item-1", "PC-1", "3"), designation("item-2", "PC-1", "3"))))
                    .allSatisfy(d -> assertThat(d.plannedMeters()).isEqualByComparingTo("3"));
            // 定高买宽缺窗高 ⇒ 定不了尺
            assertThat(service.plan(TENANT, List.of(
                    new StockBatchConsumptionService.Designation("item-1", PRODUCT_ID, "SKU-A", "PC-1",
                            new BigDecimal("3"), "定高买宽", null, null))))
                    .allSatisfy(d -> assertThat(d.plannedMeters()).isEqualByComparingTo("3"));
            // 定宽买高缺幅数（引擎的 panels 输出缺席）⇒ 不自己算 ceil(M/G)
            assertThat(service.plan(TENANT, List.of(
                    new StockBatchConsumptionService.Designation("item-1", PRODUCT_ID, "SKU-A", "PC-1",
                            new BigDecimal("2.8"), "定宽买高", new BigDecimal("1.1"), null))))
                    .allSatisfy(d -> assertThat(d.plannedMeters()).isEqualByComparingTo("2.8"));
        }

        @Test
        @DisplayName("排料省下的米数落在批次余量上 + 当时均价随行落库（saved_amount 可读）")
        void savingStaysOnBatchAndIsAuditable() {
            stubBatches(batch(77L, "PC-1", "60"));
            stubConsumed(77L, "0");
            stubHemMargin("0.3");
            stubDoorWidth("2.8米");

            var plan = service.plan(TENANT, List.of(
                    fixedHeight("item-1", "PC-1", "3", "1.1"),
                    fixedHeight("item-2", "PC-1", "3", "1.1")));
            service.apply(TENANT, "JG-1", "ORD-1", plan);

            ArgumentCaptor<StockBatchConsumption> captor =
                    ArgumentCaptor.forClass(StockBatchConsumption.class);
            verify(consumptionMapper, times(2)).insert(captor.capture());
            List<StockBatchConsumption> rows = captor.getAllValues();
            assertThat(StockQuantity.sum(rows.stream().map(StockBatchConsumption::getSavedMeters).toList()))
                    .as("🔴 账面看得见的省钱：省下 3 米留在批次余量上（6 − 3）")
                    .isEqualByComparingTo("3");
            assertThat(StockQuantity.sum(rows.stream().map(StockBatchConsumption::getFormulaMeters).toList()))
                    .isEqualByComparingTo("6");
            assertThat(StockQuantity.sum(rows.stream().map(StockBatchConsumption::getPlannedMeters).toList()))
                    .isEqualByComparingTo("3");
            assertThat(rows.get(0).getSavedAmount())
                    .as("saved_amount = saved_meters × 当时该批次均价（12.5 元/米）")
                    .isEqualByComparingTo("18.75");
        }

        @Test
        @DisplayName("🔴 均价快照的不变量：改掉批次均价 ⇒ 历史单的 saved_amount 一字不变")
        void savedAmountIgnoresLaterBatchPriceChange() {
            StockBatchConsumption row = consumption(77L, "PC-1", 1L, "item-1", "-1.5", "60", "58.5",
                    StockBatchConsumptionService.REASON_PROCESSING_ORDER);
            row.setFormulaMeters(new BigDecimal("3"));
            row.setPlannedMeters(new BigDecimal("1.5"));
            row.setUnitCost(new BigDecimal("12.5"));

            assertThat(row.getSavedAmount()).as("1.5 米 × 12.5 = 18.75").isEqualByComparingTo("18.75");
            // 批次均价被改（调价 / 成本订正）—— 台账行里的快照**不受影响**
            StockBatch repriced = batch(77L, "PC-1", "60");
            repriced.setUnitCost(new BigDecimal("99"));
            assertThat(row.getSavedAmount()).as("用的是**当时**均价 ⇒ 换价后历史数不得变")
                    .isEqualByComparingTo("18.75");
            assertThat(row.getUnitCost()).isEqualByComparingTo("12.5");
        }

        @Test
        @DisplayName("双口径与排料器无关的行：只给公式米数时 planned 逐值等于 formula（`meters()` 仍读得出）")
        void plannedEqualsFormulaWhenNoGeometryGiven() {
            stubBatches(batch(77L, "PC-1", "60"));
            stubConsumed(77L, "0");
            stubHemMargin("0.3");
            stubDoorWidth("2.8米");

            var plan = service.plan(TENANT, List.of(designation("item-1", "PC-1", "2.7")));

            assertThat(plan.get(0).formulaMeters()).isEqualByComparingTo("2.7");
            assertThat(plan.get(0).plannedMeters()).isEqualByComparingTo("2.7");
            assertThat(plan.get(0).remainingBefore()).isEqualByComparingTo("60");
        }
    }

    // ── 派工扣减：apply / reverse ─────────────────────────────────────────────

    @Nested
    @DisplayName("apply / reverse —— 派工即扣与对称回补")
    class ApplyAndReverse {

        @Test
        @DisplayName("apply：delta = −米数，before/after 与 delta 三者自洽（2.7 米）")
        void applyWritesConsistentRow() {
            var plan = service.plan(TENANT, List.of());
            assertThat(plan).isEmpty();

            var deduction = new StockBatchConsumptionService.Deduction(
                    77L, "PC-1", PRODUCT_ID, SKU_ID, "SKU-A", "item-1",
                    new BigDecimal("2.7"), new BigDecimal("2.7"), new BigDecimal("12.5"),
                    new BigDecimal("60"));
            service.apply(TENANT, "JG-1", "ORD-1", List.of(deduction));

            ArgumentCaptor<StockBatchConsumption> captor =
                    ArgumentCaptor.forClass(StockBatchConsumption.class);
            verify(consumptionMapper).insert(captor.capture());
            StockBatchConsumption row = captor.getValue();
            assertThat(row.getDelta()).isEqualByComparingTo("-2.7");
            assertThat(row.getBeforeQty()).isEqualByComparingTo("60");
            assertThat(row.getAfterQty()).isEqualByComparingTo("57.3");
            assertThat(row.getAfterQty().subtract(row.getBeforeQty()))
                    .isEqualByComparingTo(row.getDelta());
            // 两个米数 + 当时均价随行落库（V119 / issue #5158）
            assertThat(row.getFormulaMeters()).isEqualByComparingTo("2.7");
            assertThat(row.getPlannedMeters()).isEqualByComparingTo("2.7");
            assertThat(row.getUnitCost()).isEqualByComparingTo("12.5");
            assertThat(row.getSavedMeters()).isEqualByComparingTo("0");
            assertThat(row.getSavedAmount()).isEqualByComparingTo("0.00");
            assertThat(row.getReason()).isEqualTo(StockBatchConsumptionService.REASON_PROCESSING_ORDER);
            assertThat(row.getProcessingOrderNo()).isEqualTo("JG-1");
            assertThat(row.getOrderNo()).isEqualTo("ORD-1");
            assertThat(row.getOrderItemId()).isEqualTo("item-1");
        }

        @Test
        @DisplayName("apply **只动批次账**：不碰 product_skus.stock、不写 SKU 销售账（路线 A 的命门）")
        void applyNeverTouchesSkuStock() {
            var deduction = new StockBatchConsumptionService.Deduction(
                    77L, "PC-1", PRODUCT_ID, SKU_ID, "SKU-A", "item-1",
                    new BigDecimal("2.7"), new BigDecimal("2.7"), null, new BigDecimal("60"));
            service.apply(TENANT, "JG-1", "ORD-1", List.of(deduction));

            verify(consumptionMapper, times(1)).insert(any(StockBatchConsumption.class));
            verifyNoInteractions(productSkuMapper, stockLedgerMapper);
        }

        @Test
        @DisplayName("reverse：回补量 = 原扣减量的相反数，余量回到派工前**逐值相同**（60 → 57.3 → 60）")
        void reverseRestoresExactRemaining() {
            StockBatchConsumption consumed = consumption(77L, "PC-1", 1L, "item-1",
                    "-2.7", "60", "57.3", StockBatchConsumptionService.REASON_PROCESSING_ORDER);
            when(consumptionMapper.selectList(any())).thenReturn(List.of(consumed), List.of());
            stubBatches(batch(77L, "PC-1", "60"));
            stubConsumed(77L, "-2.7"); // 当前余量 = 60 − 2.7 = 57.3

            int rows = service.reverse(TENANT, "JG-1", "ORD-1", "作废回补");

            assertThat(rows).isEqualTo(1);
            ArgumentCaptor<StockBatchConsumption> captor =
                    ArgumentCaptor.forClass(StockBatchConsumption.class);
            verify(consumptionMapper).insert(captor.capture());
            StockBatchConsumption back = captor.getValue();
            assertThat(back.getDelta()).isEqualByComparingTo("2.7");
            assertThat(back.getBeforeQty()).isEqualByComparingTo("57.3");
            assertThat(back.getAfterQty()).isEqualByComparingTo("60"); // ← 派工前逐值相同
            // 回补行**逐值对称**：两个米数取相反数（整单净额归零 ⇒ 作废不冒功），均价原样搬运
            assertThat(back.getFormulaMeters()).isEqualByComparingTo("-2.7");
            assertThat(back.getPlannedMeters()).isEqualByComparingTo("-2.7");
            assertThat(back.getUnitCost()).isEqualByComparingTo("12.5");
            assertThat(back.getSavedMeters()).isEqualByComparingTo("0");
            assertThat(back.getReason())
                    .isEqualTo(StockBatchConsumptionService.REASON_PROCESSING_ORDER_CANCELLED);
            assertThat(back.getOrderItemId()).isEqualTo("item-1");
        }

        @Test
        @DisplayName("reverse 幂等可重跑：已回补过的行跳过，第二遍返回 0 且不再插入")
        void reverseIsIdempotent() {
            StockBatchConsumption consumed = consumption(77L, "PC-1", 1L, "item-1",
                    "-2.7", "60", "57.3", StockBatchConsumptionService.REASON_PROCESSING_ORDER);
            StockBatchConsumption already = consumption(77L, "PC-1", 2L, "item-1",
                    "2.7", "57.3", "60", StockBatchConsumptionService.REASON_PROCESSING_ORDER_CANCELLED);
            when(consumptionMapper.selectList(any())).thenReturn(List.of(consumed), List.of(already));
            stubBatches(batch(77L, "PC-1", "60"));
            stubConsumed(77L, "0"); // 已回补 ⇒ 净额 0 ⇒ 余量回到 60

            assertThat(service.reverse(TENANT, "JG-1", "ORD-1", "重跑")).isZero();
            verify(consumptionMapper, never()).insert(any(StockBatchConsumption.class));
        }

        @Test
        @DisplayName("reverse：该单没有批次扣减 ⇒ 0 行（不写空账）")
        void reverseWithoutRowsIsNoop() {
            when(consumptionMapper.selectList(any())).thenReturn(List.of());
            assertThat(service.reverse(TENANT, "JG-1", "ORD-1", "作废")).isZero();
            verify(consumptionMapper, never()).insert(any(StockBatchConsumption.class));
        }
    }

    // ── 读面：余量 / 分布 / 对账 / 候选 ──────────────────────────────────────

    @Nested
    @DisplayName("读面")
    class ReadFaces {

        @Test
        @DisplayName("余量派生：remaining = 入库量 + Σdelta（60 − 2.7 = 57.3）；onlyAvailable 过滤用尽批次")
        void remainingIsDerived() {
            stubBatches(batch(77L, "PC-1", "60"), batch(78L, "PC-2", "0.5"));
            when(consumptionMapper.sumDeltaByBatchIds(eq(TENANT), any())).thenAnswer(inv -> {
                StockBatchConsumptionMapper.BatchDeltaSum a = new StockBatchConsumptionMapper.BatchDeltaSum();
                a.setBatchId(77L);
                a.setDeltaSum(new BigDecimal("-2.7"));
                StockBatchConsumptionMapper.BatchDeltaSum b = new StockBatchConsumptionMapper.BatchDeltaSum();
                b.setBatchId(78L);
                b.setDeltaSum(new BigDecimal("-0.5"));
                return List.of(a, b);
            });

            var all = service.remaining(TENANT, PRODUCT_ID, SKU_ID, false);
            assertThat(all).hasSize(2);
            assertThat(all.get(0).inboundMeters()).isEqualByComparingTo("60");
            assertThat(all.get(0).consumedMeters()).isEqualByComparingTo("2.7");
            assertThat(all.get(0).remainingMeters()).isEqualByComparingTo("57.3");
            assertThat(all.get(1).remainingMeters()).isEqualByComparingTo("0");

            assertThat(service.remaining(TENANT, PRODUCT_ID, SKU_ID, true)).hasSize(1);
        }

        @Test
        @DisplayName("分布四档逐值可比：≤0.2 / 0.2~0.5 / 0.5~1 / >1（含负余量归入 ≤0.2 档）")
        void distributionBucketsAreExact() {
            stubBatches(batch(1L, "B1", "0.2"), batch(2L, "B2", "0.1"), batch(3L, "B3", "-0.5"),
                    batch(4L, "B4", "0.5"), batch(5L, "B5", "1"), batch(6L, "B6", "1.1"));
            when(consumptionMapper.sumDeltaByBatchIds(eq(TENANT), any())).thenReturn(List.of());

            BatchStockViews.Distribution distribution = service.distribution(TENANT, PRODUCT_ID);

            assertThat(distribution.totalBatches()).isEqualTo(6);
            assertThat(distribution.buckets()).extracting(BatchStockViews.Bucket::key)
                    .containsExactly("le_0_2", "b0_2_0_5", "b0_5_1", "gt_1");
            assertThat(distribution.buckets()).extracting(BatchStockViews.Bucket::batchCount)
                    .containsExactly(3, 1, 1, 1); // 0.2 / 0.1 / −0.5 ⇒ ≤0.2；0.5 ⇒ 第二档；1 ⇒ 第三档；1.1 ⇒ 第四档
            assertThat(distribution.buckets().get(0).share()).isEqualByComparingTo("0.5");
            assertThat(distribution.buckets().get(1).share()).isEqualByComparingTo("0.1667");
        }

        @Test
        @DisplayName("空仓 ⇒ 四档恒在且全 0（前端不必猜「没有这一档」是 0 还是缺数据）")
        void distributionOnEmptyTenant() {
            stubBatches();
            BatchStockViews.Distribution distribution = service.distribution(TENANT, null);
            assertThat(distribution.totalBatches()).isZero();
            assertThat(distribution.buckets()).hasSize(4);
            assertThat(distribution.buckets()).allSatisfy(b -> {
                assertThat(b.batchCount()).isZero();
                assertThat(b.share()).isEqualByComparingTo("0");
            });
        }

        @Test
        @DisplayName("对账：已售未派场景 ⇒ 差额 = 已扣未派米数，且恒等式成立（批次入 60 / 卖 2.7 / 未派工）")
        void reconcileExplainsSoldButNotDispatched() {
            stubBatches(batch(77L, "PC-1", "60"));
            when(consumptionMapper.sumDeltaByBatchIds(eq(TENANT), any())).thenReturn(List.of());
            when(consumptionMapper.sumDeltaBySku(eq(TENANT))).thenReturn(List.of());
            when(stockLedgerMapper.sumBySku(eq(TENANT))).thenReturn(List.of(
                    ledgerSum(SKU_ID, "2.7", "0", "57.3"))); // 入库 +60 与销售 −2.7 的净额
            when(productSkuMapper.selectList(any())).thenReturn(List.of(sku("57.3")));

            BatchStockViews.Reconcile reconcile = service.reconcile(TENANT, PRODUCT_ID, SKU_ID);

            assertThat(reconcile.rows()).hasSize(1);
            BatchStockViews.ReconcileRow row = reconcile.rows().get(0);
            assertThat(row.batchRemaining()).isEqualByComparingTo("60");
            assertThat(row.skuStock()).isEqualByComparingTo("57.3");
            assertThat(row.diff()).isEqualByComparingTo("2.7");           // 已售未派
            assertThat(row.dispatchedMeters()).isEqualByComparingTo("0");
            assertThat(row.soldDeductedMeters()).isEqualByComparingTo("2.7");
            assertThat(row.unbatchedMeters()).isEqualByComparingTo("0");
            assertThat(row.explainedDiff()).isEqualByComparingTo("2.7");
            assertThat(row.reconciled()).as("差额必须可解释：diff == explained − unbatched").isTrue();
            assertThat(reconcile.unreconciledCount()).isZero();
        }

        @Test
        @DisplayName("对账：派工之后差额归零（实物账追上销售账）")
        void reconcileAfterDispatchIsZero() {
            stubBatches(batch(77L, "PC-1", "60"));
            stubConsumed(77L, "-2.7");
            when(consumptionMapper.sumDeltaBySku(eq(TENANT))).thenReturn(List.of(skuDelta(SKU_ID, "-2.7")));
            when(stockLedgerMapper.sumBySku(eq(TENANT))).thenReturn(List.of(
                    ledgerSum(SKU_ID, "2.7", "0", "57.3")));
            when(productSkuMapper.selectList(any())).thenReturn(List.of(sku("57.3")));

            BatchStockViews.ReconcileRow row = service.reconcile(TENANT, PRODUCT_ID, SKU_ID).rows().get(0);

            assertThat(row.batchRemaining()).isEqualByComparingTo("57.3");
            assertThat(row.dispatchedMeters()).isEqualByComparingTo("2.7");
            assertThat(row.diff()).isEqualByComparingTo("0");
            assertThat(row.explainedDiff()).isEqualByComparingTo("0");
            assertThat(row.reconciled()).isTrue();
        }

        @Test
        @DisplayName("对账：退货回补（aftersales）造成的差额也如实反映，不静默")
        void reconcileShowsOtherLedgerDelta() {
            stubBatches(batch(77L, "PC-1", "60"));
            stubConsumed(77L, "-2.7");
            when(consumptionMapper.sumDeltaBySku(eq(TENANT))).thenReturn(List.of(skuDelta(SKU_ID, "-2.7")));
            // 入库 +60、销售 −2.7、退货回补 +2.7 ⇒ 净额 60
            when(stockLedgerMapper.sumBySku(eq(TENANT))).thenReturn(List.of(
                    ledgerSum(SKU_ID, "2.7", "2.7", "60")));
            when(productSkuMapper.selectList(any())).thenReturn(List.of(sku("60")));

            BatchStockViews.ReconcileRow row = service.reconcile(TENANT, PRODUCT_ID, SKU_ID).rows().get(0);

            assertThat(row.otherLedgerDeltaMeters()).isEqualByComparingTo("2.7");
            // 批次账 57.3 vs SKU 账 60 ⇒ 差额 −2.7 = **退货回补没回批次**（实物还在批次账上被扣着）
            assertThat(row.diff()).isEqualByComparingTo("-2.7");
            assertThat(row.explainedDiff()).isEqualByComparingTo("-2.7");
            assertThat(row.reconciled()).isTrue();
        }

        @Test
        @DisplayName("对账不平也能读出来（reconciled=false + unreconciledCount）—— 差额不得静默")
        void reconcileFlagsUnbalancedLedger() {
            stubBatches(batch(77L, "PC-1", "60"));
            stubConsumed(77L, "-2.7");
            when(consumptionMapper.sumDeltaBySku(eq(TENANT))).thenReturn(List.of(skuDelta(SKU_ID, "-2.7")));
            // 台账净额与库存对不上（模拟「有变更没落台账」）：库存 57.3 而台账总变化只有 50
            when(stockLedgerMapper.sumBySku(eq(TENANT))).thenReturn(List.of(
                    ledgerSum(SKU_ID, "2.7", "0", "50")));
            when(productSkuMapper.selectList(any())).thenReturn(List.of(sku("57.3")));

            BatchStockViews.Reconcile reconcile = service.reconcile(TENANT, PRODUCT_ID, SKU_ID);

            assertThat(reconcile.rows().get(0).reconciled())
                    .as("恒等式不成立必须判 false（红证：把 reconciled 恒置 true ⇒ 本断言红）").isFalse();
            assertThat(reconcile.unreconciledCount()).isEqualTo(1);
        }

        @Test
        @DisplayName("🔴 对账可拆（V119）：差额拆成「已售未派」+「排料节省」两项且分别可读，拆开后仍平")
        void reconcileSplitsSoldUnbatchedAndPlanSaved() {
            // 批次入 60；卖 6（销售账扣了 6）；派工按排料结果只扣 3 ⇒ 差额 3 应读作**排料节省**
            stubBatches(batch(77L, "PC-1", "60"));
            stubConsumed(77L, "-3");
            when(consumptionMapper.sumDeltaBySku(eq(TENANT))).thenReturn(List.of(
                    skuDelta(SKU_ID, "-3", "6")));
            when(stockLedgerMapper.sumBySku(eq(TENANT))).thenReturn(List.of(
                    ledgerSum(SKU_ID, "6", "0", "54")));
            when(productSkuMapper.selectList(any())).thenReturn(List.of(sku("54")));

            BatchStockViews.Reconcile reconcile = service.reconcile(TENANT, PRODUCT_ID, SKU_ID);

            BatchStockViews.ReconcileRow row = reconcile.rows().get(0);
            assertThat(row.batchRemaining()).isEqualByComparingTo("57");   // 60 − 3（排料口径）
            assertThat(row.skuStock()).isEqualByComparingTo("54");         // 60 − 6（公式口径）
            assertThat(row.diff()).isEqualByComparingTo("3");
            assertThat(row.planSavedMeters()).as("🔴 第 2 项：排料节省 = Σ公式 6 − Σ派工扣减 3")
                    .isEqualByComparingTo("3");
            assertThat(row.soldUnbatchedMeters()).as("第 1 项：已售未派 = 0（6 都派了、只是少扣 3）")
                    .isEqualByComparingTo("0");
            assertThat(row.explainedDiff()).isEqualByComparingTo("3");
            assertThat(row.reconciled()).as("拆成两项后恒等式仍成立（不是把一项挪到另一项）").isTrue();
            assertThat(reconcile.totalSavedMeters()).isEqualByComparingTo("3");
            assertThat(reconcile.totalFormulaMeters()).isEqualByComparingTo("6");
            assertThat(reconcile.totalPlannedMeters()).isEqualByComparingTo("3");
        }

        @Test
        @DisplayName("🔴 两项并存且仍平：已售未派 2 + 排料节省 3 = 差额 5（不许一项冒充另一项）")
        void reconcileReadsBothItemsSeparately() {
            // 批次入 60；卖 10（销售账扣 10，其中只派了 5）；派工 5 的公式口径是 8、排料后 5
            stubBatches(batch(77L, "PC-1", "60"));
            stubConsumed(77L, "-5");
            when(consumptionMapper.sumDeltaBySku(eq(TENANT))).thenReturn(List.of(
                    skuDelta(SKU_ID, "-5", "8")));
            when(stockLedgerMapper.sumBySku(eq(TENANT))).thenReturn(List.of(
                    ledgerSum(SKU_ID, "10", "0", "50")));
            when(productSkuMapper.selectList(any())).thenReturn(List.of(sku("50")));

            BatchStockViews.ReconcileRow row =
                    service.reconcile(TENANT, PRODUCT_ID, SKU_ID).rows().get(0);

            assertThat(row.diff()).isEqualByComparingTo("5");
            assertThat(row.planSavedMeters()).isEqualByComparingTo("3");   // 8 − 5
            assertThat(row.soldUnbatchedMeters()).isEqualByComparingTo("2"); // 10 − 8
            assertThat(row.explainedDiff()).isEqualByComparingTo("5");
            assertThat(row.reconciled()).isTrue();
        }

        @Test
        @DisplayName("历史行（formula ≡ −delta，无排料）⇒ 排料节省腿恒为 0，差额全部归「已售未派」（不冒功）")
        void historicalRowsHaveNoPlanSaving() {
            stubBatches(batch(77L, "PC-1", "60"));
            stubConsumed(77L, "-2.7");
            when(consumptionMapper.sumDeltaBySku(eq(TENANT))).thenReturn(List.of(
                    skuDelta(SKU_ID, "-2.7", "2.7")));
            when(stockLedgerMapper.sumBySku(eq(TENANT))).thenReturn(List.of(
                    ledgerSum(SKU_ID, "5.4", "0", "54.6")));
            when(productSkuMapper.selectList(any())).thenReturn(List.of(sku("54.6")));

            BatchStockViews.ReconcileRow row =
                    service.reconcile(TENANT, PRODUCT_ID, SKU_ID).rows().get(0);

            assertThat(row.planSavedMeters()).isEqualByComparingTo("0");
            assertThat(row.soldUnbatchedMeters()).isEqualByComparingTo("2.7");
            assertThat(row.diff()).isEqualByComparingTo("2.7");
            assertThat(row.reconciled()).isTrue();
        }

        @Test
        @DisplayName("候选批次：建议值 = 入库日期先进先出且余量够的那一个（朴素口径，非 best-fit）")
        void candidatesSuggestFifoEnoughBatch() {
            StockBatch first = batch(1L, "PC-OLD", "0.5");
            first.setReceivedDate(LocalDate.of(2026, 8, 1));
            StockBatch second = batch(2L, "PC-NEW", "30");
            second.setReceivedDate(LocalDate.of(2026, 9, 1));
            stubBatches(first, second);
            when(consumptionMapper.sumDeltaByBatchIds(eq(TENANT), any())).thenReturn(List.of());

            BatchStockViews.Candidates candidates = service.candidates(TENANT, PRODUCT_ID, SKU_ID,
                    new BigDecimal("2.7"));

            assertThat(candidates.suggestionRule())
                    .isEqualTo(StockBatchConsumptionService.SUGGESTION_RULE_FIFO);
            assertThat(candidates.suggestedBatchNo()).as("第一个够用的批次（先进先出）").isEqualTo("PC-NEW");
            assertThat(candidates.candidates()).extracting(BatchStockViews.Candidate::enough)
                    .containsExactly(false, true);
            assertThat(candidates.candidates()).extracting(BatchStockViews.Candidate::suggested)
                    .containsExactly(false, true);
        }

        @Test
        @DisplayName("工人端指派读面：同一行扣减 + 回补 ⇒ 取净额；净额 0 的行不出现")
        void workerAssignmentsAreNetted() {
            when(consumptionMapper.selectList(any())).thenReturn(List.of(
                    consumption(77L, "PC-1", 1L, "item-1", "-2.7", "60", "57.3",
                            StockBatchConsumptionService.REASON_PROCESSING_ORDER),
                    consumption(78L, "PC-2", 2L, "item-2", "-2.7", "60", "57.3",
                            StockBatchConsumptionService.REASON_PROCESSING_ORDER),
                    consumption(78L, "PC-2", 3L, "item-2", "2.7", "57.3", "60",
                            StockBatchConsumptionService.REASON_PROCESSING_ORDER_CANCELLED)));

            var assignments = service.assignmentsOf(TENANT, "JG-1");

            assertThat(assignments).containsOnlyKeys("item-1");
            assertThat(assignments.get("item-1").batchNo()).isEqualTo("PC-1");
            assertThat(assignments.get("item-1").meters()).isEqualByComparingTo("2.7");
        }
    }

    private StockLedgerMapper.SkuLedgerSum ledgerSum(Long skuId, String sold, String other, String total) {
        StockLedgerMapper.SkuLedgerSum sum = new StockLedgerMapper.SkuLedgerSum();
        sum.setSkuId(skuId);
        sum.setSoldDeducted(new BigDecimal(sold));
        sum.setOtherDelta(new BigDecimal(other));
        sum.setTotalDelta(new BigDecimal(total));
        return sum;
    }

    private StockBatchConsumptionMapper.SkuDeltaSum skuDelta(Long skuId, String delta) {
        // 历史行口径：formula_meters = −delta（V119 的回填值）⇒ 排料节省腿为 0
        return skuDelta(skuId, delta, new BigDecimal(delta).negate().toPlainString());
    }

    /**
     * 逐 SKU 汇总桩。{@code formulaSum} = **公式口径**净额（V119，扣减行为正）
     * —— 单参版即历史行口径（= −delta ⇒ 排料节省为 0）。
     */
    private StockBatchConsumptionMapper.SkuDeltaSum skuDelta(Long skuId, String delta, String formulaSum) {
        StockBatchConsumptionMapper.SkuDeltaSum sum = new StockBatchConsumptionMapper.SkuDeltaSum();
        sum.setSkuId(skuId);
        sum.setDeltaSum(new BigDecimal(delta));
        sum.setFormulaSum(new BigDecimal(formulaSum));
        return sum;
    }

    private ProductSku sku(String stock) {
        return ProductSku.builder().id(SKU_ID).tenantId(TENANT).productId(PRODUCT_ID)
                .skuCode("SKU-A").stock(new BigDecimal(stock)).build();
    }
}
