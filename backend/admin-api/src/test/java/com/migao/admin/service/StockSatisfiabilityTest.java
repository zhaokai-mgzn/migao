// case_ids: PR-081
// 行级**库存可满足性**（issue #7091）—— `StockSatisfiability` 的**纯函数**判据。
//
// 为什么单独一个文件：本类回答的「这一行有没有能裁出它的批次」被两处消费 ——
// 池读面的行级标记（缺料行禁用勾选 + 行内提示）与派工前的 fail-closed 拒绝判据。
// 它**不碰 DB**（批次快照与 `Σdelta` 由调用方传入）⇒ 口径可以在内存里逐条钉住：
// 余量方向 / 单批最大 / SKU 一致性 / 缺省读数，任一条被改坏这里必红 ——
// 而不是等到商家点「一键合并派单」被拒（或反过来：明明能派却被标成不可派）。
//
// 🔴 边界（照实登记）：本文件**不判**「`Σdelta` 从哪里来」。批次余量的**聚合唯一性**由
// `tests/unit_ci_workflows/test_batch_stocktake_write_point.py` 的
// `test_batch_remaining_is_derived_in_one_place` 守着（它扫源码：第二处聚合即具名判红）；
// 本文件判的是「拿到那份 consumed 之后算得对不对」，两者不互为替代。
package com.migao.admin.service;

import com.migao.admin.entity.StockBatch;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("行级库存可满足性（issue #7091）")
class StockSatisfiabilityTest {

    /** 一个批次：只填判定用到的四个字段（其余 null ⇒ 顺带证明本类不读别的列）。 */
    private static StockBatch batch(Long id, String productId, String skuCode, String quantity) {
        return StockBatch.builder().id(id).productId(productId).skuCode(skuCode)
                .quantity(new BigDecimal(quantity)).build();
    }

    private static StockSatisfiability.MaterialDemand demand(String productId, String skuCode) {
        return new StockSatisfiability.MaterialDemand(productId, skuCode);
    }

    @Nested
    @DisplayName("PR-081 SKU 一致性口径（唯一实现，派工三层共用）")
    class SameSku {

        @Test
        @DisplayName("缺一不算不一致：任一侧没值 ⇒ 放行（存量批次 / 存量订单行就是这样）")
        void missingOnEitherSideIsNotAMismatch() {
            assertThat(StockSatisfiability.sameSku(null, "SKU-1")).as("行上没有 SKU").isTrue();
            assertThat(StockSatisfiability.sameSku("SKU-1", null)).as("批次上没有 SKU").isTrue();
            assertThat(StockSatisfiability.sameSku("", "SKU-1")).as("空串等同没值").isTrue();
            assertThat(StockSatisfiability.sameSku("  ", "SKU-1")).as("空白等同没值").isTrue();
            assertThat(StockSatisfiability.sameSku(null, null)).isTrue();
        }

        @Test
        @DisplayName("两侧都有值且不同 ⇒ 真不一致（这条红了 = 换色/换门幅的批次会被当成可用）")
        void differentCodesAreAMismatch() {
            assertThat(StockSatisfiability.sameSku("SKU-1", "SKU-2")).isFalse();
            assertThat(StockSatisfiability.sameSku("SKU-1", "SKU-1")).as("逐字相同").isTrue();
        }
    }

    @Nested
    @DisplayName("PR-081 要查的商品（纯投影：调用方据此一条查询取回全部批次）")
    class ProductIds {

        @Test
        @DisplayName("去重、保序、跳过缺商品的物料（缺商品匹配不到任何批次，读数恒 0）")
        void dedupesAndSkipsBlankProducts() {
            Set<String> ids = StockSatisfiability.productIdsOf(List.of(
                    demand("prod-1", "SKU-1"), demand("prod-1", "SKU-2"),
                    demand(null, "SKU-3"), demand("", "SKU-4"), demand("  ", "SKU-5"),
                    demand("prod-2", null)));
            assertThat(ids).containsExactly("prod-1", "prod-2");
        }

        @Test
        @DisplayName("入参缺席 ⇒ 空集（不是 NPE，也不是「查全租户」）")
        void nullDemandsYieldEmptySet() {
            assertThat(StockSatisfiability.productIdsOf(null)).isEmpty();
            assertThat(StockSatisfiability.productIdsOf(List.of())).isEmpty();
        }
    }

    @Nested
    @DisplayName("PR-081 最大单批余量（= 入库量 + Σ消耗，取单批最大而不是求和）")
    class MaxRemaining {

        @Test
        @DisplayName("余量 = 入库量 + Σ消耗（consumed 是负数：净消耗）")
        void remainingIsInboundPlusNetConsumption() {
            Map<StockSatisfiability.MaterialDemand, BigDecimal> max =
                    StockSatisfiability.maxRemainingByMaterial(
                            List.of(demand("prod-1", "SKU-1")),
                            List.of(batch(1L, "prod-1", "SKU-1", "10")),
                            Map.of(1L, new BigDecimal("-4")));
            assertThat(max.get(demand("prod-1", "SKU-1")))
                    .as("10 米入库、已消耗 4 米 ⇒ 还剩 6 米")
                    .isEqualByComparingTo("6");
        }

        @Test
        @DisplayName("取**单批最大**，不是各批之和（求和会把两卷布算成一卷 ⇒ 够用判断变假绿）")
        void takesTheLargestSingleBatchNotTheSum() {
            Map<StockSatisfiability.MaterialDemand, BigDecimal> max =
                    StockSatisfiability.maxRemainingByMaterial(
                            List.of(demand("prod-1", "SKU-1")),
                            List.of(batch(1L, "prod-1", "SKU-1", "4"),
                                    batch(2L, "prod-1", "SKU-1", "6")),
                            Map.of());
            assertThat(max.get(demand("prod-1", "SKU-1")))
                    .as("两批都不够 7 米（4 + 6 之和够了，但没有**任何单批**够）⇒ 上限是 6")
                    .isEqualByComparingTo("6");
        }

        @Test
        @DisplayName("超扣（余量为负）读作 0：显式读数，不是负数、也不是「没查」")
        void overConsumedBatchReadsZero() {
            Map<StockSatisfiability.MaterialDemand, BigDecimal> max =
                    StockSatisfiability.maxRemainingByMaterial(
                            List.of(demand("prod-1", "SKU-1")),
                            List.of(batch(1L, "prod-1", "SKU-1", "2")),
                            Map.of(1L, new BigDecimal("-2.5")));
            assertThat(max.get(demand("prod-1", "SKU-1")))
                    .as("入库 2 米、净消耗 2.5 米 ⇒ 这一批裁不出任何东西（不许把负数当余量）")
                    .isEqualByComparingTo("0");
        }

        @Test
        @DisplayName("SKU 不一致的批次不计入；物料没写 SKU ⇒ 任一批次都算候选（缺一不算不一致）")
        void batchOfAnotherSkuDoesNotCount() {
            List<StockBatch> batches = List.of(batch(1L, "prod-1", "SKU-2", "9"));
            Map<StockSatisfiability.MaterialDemand, BigDecimal> max =
                    StockSatisfiability.maxRemainingByMaterial(
                            List.of(demand("prod-1", "SKU-1"), demand("prod-1", null)),
                            batches, Map.of());
            assertThat(max.get(demand("prod-1", "SKU-1")))
                    .as("颜色/门幅对不上 ⇒ 这卷布不能拿来裁这一行").isEqualByComparingTo("0");
            assertThat(max.get(demand("prod-1", null)))
                    .as("行上没写 SKU ⇒ 同商品的批次都是候选").isEqualByComparingTo("9");
        }

        @Test
        @DisplayName("没有可用批次的物料读作 0（**显式给读数**，不拿「缺席」区分「没查」与「没有」）")
        void materialWithoutAnyBatchReadsZero() {
            Map<StockSatisfiability.MaterialDemand, BigDecimal> max =
                    StockSatisfiability.maxRemainingByMaterial(
                            List.of(demand("prod-1", "SKU-1"), demand("prod-404", "SKU-1")),
                            List.of(batch(1L, "prod-1", "SKU-1", "3")),
                            Map.of());
            assertThat(max).containsKeys(demand("prod-1", "SKU-1"), demand("prod-404", "SKU-1"));
            assertThat(max.get(demand("prod-404", "SKU-1"))).isEqualByComparingTo("0");
        }

        @Test
        @DisplayName("同一物料多行 ⇒ 只判一次（物料是去重键）；入参缺席 ⇒ 空表")
        void dedupesDemandsByName() {
            Map<StockSatisfiability.MaterialDemand, BigDecimal> max =
                    StockSatisfiability.maxRemainingByMaterial(
                            List.of(demand("prod-1", "SKU-1"), demand("prod-1", "SKU-1")),
                            List.of(batch(1L, "prod-1", "SKU-1", "5")),
                            Map.of());
            assertThat(max).hasSize(1);
            assertThat(max.get(demand("prod-1", "SKU-1"))).isEqualByComparingTo("5");

            assertThat(StockSatisfiability.maxRemainingByMaterial(null, List.of(), Map.of())).isEmpty();
            assertThat(StockSatisfiability.maxRemainingByMaterial(List.of(), List.of(), Map.of())).isEmpty();
        }

        @Test
        @DisplayName("consumed 里多余/缺失的批次键都不影响读数（缺失按 0 算，多余的被忽略）")
        void consumedKeysOutsideTheBatchSetAreIgnored() {
            Map<StockSatisfiability.MaterialDemand, BigDecimal> max =
                    StockSatisfiability.maxRemainingByMaterial(
                            List.of(demand("prod-1", "SKU-1")),
                            List.of(batch(1L, "prod-1", "SKU-1", "8")),
                            Map.of(99L, new BigDecimal("-100"), 1L, new BigDecimal("-3")));
            assertThat(max.get(demand("prod-1", "SKU-1")))
                    .as("只认这一批自己的净消耗（-3）：8 - 3 = 5")
                    .isEqualByComparingTo("5");
        }
    }
}
