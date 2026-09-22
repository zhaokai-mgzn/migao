// case_ids: PR-048, PR-050
// 库存米数精度口径（issue #5063）—— `StockQuantity` 的**纯函数**判据。
//
// 为什么单独一个文件：本类的三条口径（准入判据 / 订单侧显式进位 / 0.1 米刻度换算）
// 是**跨服务共同判据**（入库 / 库存调整 / 建品改品 / 订单扣减回补）。散在各服务里断言
// 会让「两套口径」有机会同时存在（一处拒 2.755、另一处悄悄存成 2.8 还不报错）
// —— 本文件把口径钉在一个地方，红证是「改坏任一条 ⇒ 这里必红」。
package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@DisplayName("库存米数精度口径（issue #5063 / V115）")
class StockQuantityTest {

    @Nested
    @DisplayName("PR-048 库存类输入的准入判据（fail-closed，不静默取整）")
    class RequireOneDecimal {

        @Test
        @DisplayName("整数与 1 位小数一律放行（含 0 位小数的书写形态）")
        void acceptsZeroOrOneDecimal() {
            assertThat(StockQuantity.requireOneDecimal(new BigDecimal("60.5"), "数量"))
                    .isEqualByComparingTo("60.5");
            assertThat(StockQuantity.requireOneDecimal(new BigDecimal("2.7"), "数量"))
                    .isEqualByComparingTo("2.7");
            assertThat(StockQuantity.requireOneDecimal(BigDecimal.valueOf(10), "数量"))
                    .isEqualByComparingTo("10");
            assertThat(StockQuantity.requireOneDecimal(new BigDecimal("999.9"), "数量"))
                    .isEqualByComparingTo("999.9");
            // 2 位书写、1 位有效（2.70）⇒ 合法，且尾零被去掉（scale 也逐值不变）
            assertThat(StockQuantity.requireOneDecimal(new BigDecimal("2.70"), "数量"))
                    .isEqualTo(new BigDecimal("2.7"));
        }

        @Test
        @DisplayName("2 位及以上小数 ⇒ 显式拒绝（2.755 不得被存成 2.8、2.75 不得被存成 2.7）")
        void rejectsTwoOrMoreDecimals() {
            for (String raw : new String[]{"2.755", "2.75", "1.05", "0.05"}) {
                assertThatThrownBy(() -> StockQuantity.requireOneDecimal(new BigDecimal(raw), "库存"))
                        .as("%s 必须被拒绝（超过 1 位小数）", raw)
                        .isInstanceOf(BusinessException.class)
                        .hasMessageContaining("1 位小数")
                        .hasMessageContaining(raw);
            }
        }

        @Test
        @DisplayName("拒绝文案可行动（说清 0.1 米粒度 + 不许静默取整）")
        void rejectionMessageIsActionable() {
            assertThatThrownBy(() -> StockQuantity.requireOneDecimal(new BigDecimal("2.755"), "调整量"))
                    .hasMessageContaining("0.1 米粒度")
                    .hasMessageContaining("请改为 1 位小数")
                    .hasMessageContaining("不做静默取整");
        }

        @Test
        @DisplayName("可空版本保 null（改品请求里 null = 「这一项不改」，不得归一成 0 把库存清零）")
        void nullPreservingVariant() {
            assertThat(StockQuantity.requireOneDecimalOrNull(null, "库存 stock")).isNull();
            assertThat(StockQuantity.requireOneDecimalOrNull(new BigDecimal("60.5"), "库存 stock"))
                    .isEqualByComparingTo("60.5");
            assertThatThrownBy(() -> StockQuantity.requireOneDecimalOrNull(new BigDecimal("1.25"), "库存 stock"))
                    .isInstanceOf(BusinessException.class);
        }
    }

    @Nested
    @DisplayName("PR-050 订单侧口径与整数逐值不变")
    class OrderSideAndIntegerRegression {

        @Test
        @DisplayName("订单侧按 §8 用料口径向上进位到 0.1（不拒绝、也不截断）")
        void ceilingsToStockScale() {
            // docs/curtain-fabric-quote-rules.md §8「用料米数一律向上进位到 0.1」
            assertThat(StockQuantity.toStockScaleByCeiling(new BigDecimal("2.75")))
                    .isEqualByComparingTo("2.8");
            assertThat(StockQuantity.toStockScaleByCeiling(new BigDecimal("2.71")))
                    .isEqualByComparingTo("2.8");
        }

        @Test
        @DisplayName("已在粒度内的值**逐值不变**（含 scale —— 2 不得变成 2.0、10.00 不得变成 1E+1）")
        void alreadyInScaleIsByteIdentical() {
            assertThat(StockQuantity.toStockScaleByCeiling(BigDecimal.valueOf(2)))
                    .isEqualTo(BigDecimal.valueOf(2));
            assertThat(StockQuantity.toStockScaleByCeiling(new BigDecimal("2.7")))
                    .isEqualTo(new BigDecimal("2.7"));
            assertThat(StockQuantity.toStockScaleByCeiling(new BigDecimal("10.00")))
                    .isEqualTo(BigDecimal.TEN);
            assertThat(StockQuantity.toStockScaleByCeiling(new BigDecimal("10.00")).toPlainString())
                    .isEqualTo("10");
            assertThat(StockQuantity.toStockScaleByCeiling(null)).isEqualTo(BigDecimal.ZERO);
        }

        @Test
        @DisplayName("0.1 米刻度换算可逆，且整刻度回落成整数（27↔2.7、20↔2）")
        void tenthsRoundTrip() {
            assertThat(StockQuantity.tenths(new BigDecimal("2.7"))).isEqualTo(27L);
            assertThat(StockQuantity.fromTenths(27)).isEqualTo(new BigDecimal("2.7"));
            assertThat(StockQuantity.fromTenths(20)).isEqualTo(BigDecimal.valueOf(2));
            assertThat(StockQuantity.fromTenths(20).toPlainString()).isEqualTo("2");
            assertThat(StockQuantity.tenths(BigDecimal.valueOf(10))).isEqualTo(100L);
        }

        @Test
        @DisplayName("空安全求和（null 项按 0 计，不丢精度）")
        void sumIsNullSafe() {
            assertThat(StockQuantity.sum(java.util.Arrays.asList(
                    new BigDecimal("60.5"), null, new BigDecimal("1.5"))))
                    .isEqualByComparingTo("62");
            assertThat(StockQuantity.sum(java.util.List.of())).isEqualTo(BigDecimal.ZERO);
            assertThat(StockQuantity.orZero(null)).isEqualTo(BigDecimal.ZERO);
        }
    }
}
