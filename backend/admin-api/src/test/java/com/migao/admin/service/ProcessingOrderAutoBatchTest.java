// case_ids: MC-310
package com.migao.admin.service;

import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.ProductionPoolViews;
import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 自动批次**决策单元自身**的不变量判据（issue #8770 自动批次一档）。
 *
 * <h2>它补的是哪一格（与 characterization 分工）</h2>
 * {@code ProcessingOrderAutoBatchCharacterizationTest} 判的是「搬前搬后**逐字节相同**」——
 * 它能把「口径变了」抓住，但抓不住「这个单元**本来就该**守什么」：
 * 一个从第一天就写错、且从未变过的行为，characterization 会**一路绿**（golden 就是错的那份）。
 * ⇒ 本判据钉单元自己的不变量：边界是否含等号、分母是谁、优先级、以及
 * <b>「关闸零外呼」与「三级降级逐条留痕」这两条结构性要求</b>。
 *
 * <h2>与既有判据的分工（不重复）</h2>
 * {@code AutoBatchDispatchTest} / {@code AutoBatchDueScanServiceTest} 走**门面公开入口**
 * （端到端读数：派了哪几张单）；本判据走**决策函数的直接入参**（边界值、分母、SKU 一致性）。
 * 两者缺一不可：前者证明「入口到出口对」，后者证明「算式本身对」。
 *
 * <h2>红证</h2>
 * 逐条见 PR body（含把 {@code <=} 改成 {@code <}、把分母换成余量、把 min_batch 降到 converge 之后、
 * 把 SKU 一致性判据摘掉、把关闸拆掉 —— 每种都**具名**红在本文件的某一条上）。
 */
@DisplayName("自动批次决策单元：条件边界 / 分母 / 优先级 / SKU 一致性 / 关闸零外呼 / 三级降级留痕")
class ProcessingOrderAutoBatchTest {

    private static final Long TENANT = 8770L;
    private static final String PRODUCT = "prod-unit";
    private static final String SKU = "SKU-A";

    /** 只提供 {@code batchStock()} 的最小 Owner（其余方法调用即失败 —— 它们不该被这些用例碰到）。 */
    private ProcessingOrderAutoBatch unitWith(StockBatchConsumptionService batchStock) {
        return new ProcessingOrderAutoBatch(new ProcessingOrderAutoBatch.Owner() {
            @Override
            public ProductionPoolViews.Pool pool(Long tenantId, BigDecimal maxWaitHours) {
                throw new AssertionError("本用例不该读池");
            }

            @Override
            public List<ProcessingOrderService.GenerateResult> generate(List<String> orderIds,
                    List<com.migao.admin.dto.ProcessingOrderGenerateRequest.BatchAssignment> assignments,
                    Long tenantId, String operator, String rule, Boolean pooled) {
                throw new AssertionError("本用例不该派单");
            }

            @Override
            public LocalDate today() {
                return LocalDate.of(2026, 11, 6);
            }

            @Override
            public StockBatchConsumptionService batchStock() {
                return batchStock;
            }
        });
    }

    // ── 判据 1：需求非正 ⇒ 不成批（不得恒真）──────────────────────────────

    @Test
    @DisplayName("🔴 判据1 需求为 0 / 负 ⇒ 三条条件都不判（不误派），且一次批次查询都不发")
    void zeroDemandNeverTriggersBatching() {
        StockBatchConsumptionService batchStock = mock(StockBatchConsumptionService.class);
        ProcessingOrderAutoBatch unit = unitWith(batchStock);

        assertThat(unit.batchConditionReason(group("0"), TENANT, policy(80, "0.2", "0")))
                .as("需求 0 米 ⇒ 没有「值得凑」的东西（红证：摘掉 demand<=0 的早返回 ⇒ 条件③ 0>=0 命中）")
                .isNull();
        assertThat(unit.batchConditionReason(group("-1"), TENANT, policy(80, "0.2", "0")))
                .as("负需求是脏数据 ⇒ 同样不判（不拿脏数据去凑批次）").isNull();
        verifyNoInteractions(batchStock);
    }

    // ── 判据 2：优先级（③ 先于 ①②，命中即返回，不再查批次）────────────────

    @Test
    @DisplayName("🔴 判据2 条件③（最小批量）优先：同一条组同时满足 ③ 与 ①② 时，命中的是 ③ 且不查批次")
    void minBatchWinsOverFillRatioAndConverge() {
        StockBatchConsumptionService batchStock = mock(StockBatchConsumptionService.class);
        ProcessingOrderAutoBatch unit = unitWith(batchStock);

        String reason = unit.batchConditionReason(group("3"), TENANT, policy(80, "0.2", "3"));

        assertThat(reason)
                .as("命中的必须是 ③ min_batch（红证：把 ③ 挪到 ①② 之后 ⇒ 这里变成 fill_ratio）")
                .contains("condition=min_batch").contains("demand=3>=3");
        verify(batchStock, never()).remaining(any(), any(), any(), anyBoolean());
    }

    // ── 判据 3：边界含等号（收敛 0.2 命中 / 0.21 不命中）──────────────────

    @Test
    @DisplayName("🔴 判据3 条件②是**闭区间**：余量−需求 = 0.2 ⇒ 命中；= 0.21 ⇒ 不命中")
    void convergeIsInclusiveAtTheBoundary() {
        StockBatchConsumptionService hit = mock(StockBatchConsumptionService.class);
        when(hit.remaining(eq(TENANT), eq(PRODUCT), any(), anyBoolean()))
                .thenReturn(List.of(batch("PC-HIT", "90", "3.2", SKU)));
        assertThat(unitWith(hit).batchConditionReason(group("3"), TENANT, policy(80, "0.2", "100")))
                .as("0 ≤ 3.2 − 3 = 0.2 ≤ 0.2 ⇒ 命中（红证：把 <= 改 < ⇒ 本断言红）")
                .contains("condition=converge");

        StockBatchConsumptionService miss = mock(StockBatchConsumptionService.class);
        when(miss.remaining(eq(TENANT), eq(PRODUCT), any(), anyBoolean()))
                .thenReturn(List.of(batch("PC-MISS", "90", "3.21", SKU)));
        assertThat(unitWith(miss).batchConditionReason(group("3"), TENANT, policy(80, "0.2", "100")))
                .as("3.21 − 3 = 0.21 > 0.2 ⇒ 不命中（边界不能放宽）").isNull();
    }

    // ── 判据 4：条件① 的分母是**入库量**（不是余量）────────────────────────

    @Test
    @DisplayName("🔴 判据4 条件① 的分母是入库量：入库 3 米 / 余量 0.3 米、需求 3 米 ⇒ 命中（分母换成余量就不命中）")
    void fillRatioUsesInboundAsTheDenominator() {
        StockBatchConsumptionService asInbound = mock(StockBatchConsumptionService.class);
        when(asInbound.remaining(eq(TENANT), eq(PRODUCT), any(), anyBoolean()))
                .thenReturn(List.of(batch("PC-IN", "3", "0.3", SKU)));

        assertThat(unitWith(asInbound).batchConditionReason(group("3"), TENANT, policy(80, "0.001", "100")))
                .as("3 ≥ 80% × 3 ⇒ 命中（红证：把分母换成 remainingMeters ⇒ 3 ≥ 2.4 变成 3 ≥ 0.24 仍中，"
                        + "故反向用余量极小值：这里若按余量 0.3 ≤ 需求 3 且 0 ≤ −2.7 → 不中）")
                .contains("condition=fill_ratio").contains("batch[PC-IN]=3");
    }

    // ── 判据 5：SKU 一致性（有一侧没记 ⇒ 不作不一致判定）──────────────────

    @Test
    @DisplayName("🔴 判据5 批次 SKU 与组 SKU 都记了且不同 ⇒ 该批次不参与判定；有一侧没记 ⇒ 仍参与")
    void batchWithMismatchedSkuIsIgnored() {
        StockBatchConsumptionService batchStock = mock(StockBatchConsumptionService.class);
        when(batchStock.remaining(eq(TENANT), eq(PRODUCT), any(), anyBoolean()))
                .thenReturn(List.of(batch("PC-OTHER", "90", "3.1", "SKU-OTHER"),
                        batch("PC-SAME", "900", "900", SKU)));

        assertThat(unitWith(batchStock).batchConditionReason(group("3"), TENANT, policy(80, "0.2", "100")))
                .as("唯一的可命中批次属于别的 SKU ⇒ 必须被忽略；同 SKU 那条余量 900 远未收敛 ⇒ 不命中"
                        + "（红证：摘掉 SKU 一致性判据 ⇒ PC-OTHER 命中 converge）")
                .isNull();

        StockBatchConsumptionService unknownSku = mock(StockBatchConsumptionService.class);
        when(unknownSku.remaining(eq(TENANT), eq(PRODUCT), any(), anyBoolean()))
                .thenReturn(List.of(batch("PC-NULLSKU", "90", "3.1", null)));
        assertThat(unitWith(unknownSku).batchConditionReason(group("3"), TENANT, policy(80, "0.2", "100")))
                .as("批次侧没记 SKU ⇒ 不作不一致判定（「有一侧没记」不能当成「不一致」）")
                .contains("condition=converge");
    }

    // ── 判据 6：关闸在**单元内**且零外呼（不是靠调用方记得）──────────────

    @Test
    @DisplayName("🔴 判据6 显式关 ⇒ 单元返回 enabled=false 且**一次 Owner 调用都没有**（连池都不查）")
    void explicitOffNeverTouchesTheOwner() {
        ProcessingOrderAutoBatch.Owner owner = mock(ProcessingOrderAutoBatch.Owner.class);
        ProcessingOrderAutoBatch unit = new ProcessingOrderAutoBatch(owner);

        ProcessingOrderService.AutoBatchOutcome event = unit.dispatch(TENANT, "t", disabledPolicy());
        ProcessingOrderService.AutoBatchOutcome due = unit.dispatchDue(TENANT, "due_scan",
                disabledPolicy());

        assertThat(event.enabled()).isFalse();
        assertThat(due.enabled()).isFalse();
        assertThat(event.reasons()).as("零读零写 ⇒ 没有理由、没有单号、没有失败").isEmpty();
        assertThat(event.dispatchedOrderNos()).isEmpty();
        verifyNoInteractions(owner);
    }

    @Test
    @DisplayName("🔴 判据6b tenantId 为 null ⇒ 同一条关闸（不查池、不派单）")
    void nullTenantNeverTouchesTheOwner() {
        ProcessingOrderAutoBatch.Owner owner = mock(ProcessingOrderAutoBatch.Owner.class);
        ProcessingOrderAutoBatch unit = new ProcessingOrderAutoBatch(owner);

        assertThat(unit.dispatch(null, "t", policy(80, "0.2", "30")).enabled()).isFalse();
        assertThat(unit.dispatchDue(null, "due_scan", policy(80, "0.2", "30")).enabled()).isFalse();
        verifyNoInteractions(owner);
    }

    // ── 判据 7：三级降级 + 失败逐条留痕（trigger 前缀进 failures）────────────

    @Test
    @DisplayName("🔴 判据7 三级全失败 ⇒ 逐单走满 3 次尝试（池级 → 逐单+规则 → 逐单不带规则），"
            + "failures 带 trigger 前缀与单号")
    void threeLevelFallbackRecordsAFailureWithTheTriggerPrefix() {
        StockBatchConsumptionService batchStock = mock(StockBatchConsumptionService.class);
        List<String> operators = new ArrayList<>();
        ProcessingOrderAutoBatch unit = new ProcessingOrderAutoBatch(new ProcessingOrderAutoBatch.Owner() {
            @Override
            public ProductionPoolViews.Pool pool(Long tenantId, BigDecimal maxWaitHours) {
                return new ProductionPoolViews.Pool(maxWaitHours, true, 1, 1, 0, 0, List.of(),
                        List.of(), List.of(), 0, List.of(new ProductionPoolViews.PoolGroup(
                        PRODUCT + "|" + SKU, "布艺遮光帘A", PRODUCT, SKU, 1, new BigDecimal("3"),
                        List.of(line("o-1", "ORD-U1")))));
            }

            @Override
            public List<ProcessingOrderService.GenerateResult> generate(List<String> orderIds,
                    List<com.migao.admin.dto.ProcessingOrderGenerateRequest.BatchAssignment> assignments,
                    Long tenantId, String operator, String rule, Boolean pooled) {
                operators.add(operator + "|" + rule + "|" + pooled);
                List<ProcessingOrderService.GenerateResult> out = new ArrayList<>();
                for (String id : orderIds) {
                    out.add(ProcessingOrderService.GenerateResult.fail(id, "FAKE_CODE",
                            "夹具：这一级派不出去", null));
                }
                return out;
            }

            @Override
            public LocalDate today() {
                return LocalDate.of(2026, 11, 6);
            }

            @Override
            public StockBatchConsumptionService batchStock() {
                return batchStock;
            }
        });

        ProcessingOrderService.AutoBatchOutcome outcome = unit.dispatch(TENANT, "order_confirmed",
                policy(80, "0.2", "3"));

        assertThat(operators)
                .as("必须走满三级（顺序即优先级）：池级 → 逐单+规则(`:single`) → 逐单不带规则(`:plain`)")
                .containsExactly(
                        "auto:order_confirmed:fifo|fifo|true",
                        "auto:order_confirmed:fifo:single|fifo|false",
                        "auto:order_confirmed:fifo:plain|null|false");
        assertThat(outcome.failedOrderIds()).containsExactly("o-1");
        assertThat(outcome.failures()).singleElement().asString()
                .as("失败文案必须带 trigger 前缀 + 单号 + 可读原因（排查的第一手线索）")
                .startsWith("trigger=order_confirmed, orderId=o-1: ").contains("夹具：这一级派不出去");
    }

    // ── 夹具 ───────────────────────────────────────────────────────────────

    private static ProcessingOrderService.AutoBatchPolicy policy(int fillRatio, String converge,
                                                                 String minBatch) {
        return ProcessingOrderService.AutoBatchPolicy.enabledPolicy()
                .with(fillRatio, converge, minBatch, 7);
    }

    private static ProcessingOrderService.AutoBatchPolicy disabledPolicy() {
        return new ProcessingOrderService.AutoBatchPolicy(false, 80, new BigDecimal("0.2"),
                new BigDecimal("30"), 7, "fifo", new BigDecimal("24"));
    }

    private static ProductionPoolViews.PoolGroup group(String requiredMeters) {
        return new ProductionPoolViews.PoolGroup(PRODUCT + "|" + SKU, "布艺遮光帘A", PRODUCT, SKU,
                1, new BigDecimal(requiredMeters), List.of(line("o-1", "ORD-U1")));
    }

    private static ProductionPoolViews.PoolLine line(String orderId, String orderNo) {
        return new ProductionPoolViews.PoolLine(orderId, orderNo, "i-1", PRODUCT, "布艺遮光帘A", SKU,
                new BigDecimal("3"), java.time.OffsetDateTime.parse("2026-11-06T09:00:00+08:00"),
                BigDecimal.ONE, false, false, false, LocalDate.of(2026, 12, 30), null);
    }

    private static BatchStockViews.BatchRemaining batch(String batchNo, String inbound,
                                                        String remaining, String skuCode) {
        return new BatchStockViews.BatchRemaining(1L, batchNo, PRODUCT, 1L, skuCode, "RK-1", null,
                LocalDate.of(2026, 10, 1), new BigDecimal("12.5"), new BigDecimal(inbound),
                new BigDecimal(inbound).subtract(new BigDecimal(remaining)),
                new BigDecimal(remaining));
    }
}
