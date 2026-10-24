// case_ids: WH-001
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 调拨守恒判据（issue #7373，P1-1 段 1）—— issue 判据第一条「调拨两端数量守恒」的核心。
 *
 * <p>写错方向（两边都减）不会报错，只会让库存慢慢对不上；这种错**必须**由纯函数钉住。</p>
 */
@DisplayName("调拨守恒：可调量 / 同仓拒 / 总量不变 / 剩余量")
class StockTransferPolicyTest {

    @Test
    @DisplayName("可调量：不超过调出仓现有量（等于可以，超一点就拒）")
    void movableUpToAvailable() {
        assertThat(StockTransferPolicy.canMove(new BigDecimal("100"), new BigDecimal("100"), false)).isTrue();
        assertThat(StockTransferPolicy.canMove(new BigDecimal("100"), new BigDecimal("100.1"), false)).isFalse();
        assertThat(StockTransferPolicy.canMove(new BigDecimal("100"), new BigDecimal("40"), false)).isTrue();
    }

    @Test
    @DisplayName("同仓调拨一律拒（无意义，且会掩盖「写错仓」）")
    void sameWarehouseIsRejected() {
        assertThat(StockTransferPolicy.canMove(new BigDecimal("100"), new BigDecimal("10"), true)).isFalse();
    }

    @Test
    @DisplayName("数量 0 / 负数 / null 一律拒（不产生空转调拨单）")
    void nonPositiveQtyIsRejected() {
        assertThat(StockTransferPolicy.canMove(new BigDecimal("100"), BigDecimal.ZERO, false)).isFalse();
        assertThat(StockTransferPolicy.canMove(new BigDecimal("100"), new BigDecimal("-5"), false)).isFalse();
        assertThat(StockTransferPolicy.canMove(new BigDecimal("100"), null, false)).isFalse();
    }

    @Test
    @DisplayName("批次数量未知 ⇒ 不能调（不猜 0，也不放行）")
    void unknownBatchQtyCannotMove() {
        assertThat(StockTransferPolicy.canMove(null, new BigDecimal("1"), false)).isFalse();
    }

    @Test
    @DisplayName("🔴 守恒：调拨前后总量必须一字不变")
    void conservationHolds() {
        assertThat(StockTransferPolicy.conserved(new BigDecimal("500"), new BigDecimal("500"))).isTrue();
        assertThat(StockTransferPolicy.conserved(new BigDecimal("500"), new BigDecimal("499.9")))
                .as("差 0.1 米也是错 —— 守恒不是「差不多」").isFalse();
        assertThat(StockTransferPolicy.conserved(null, new BigDecimal("500"))).isFalse();
    }

    @Test
    @DisplayName("调出仓剩余量 = 现有 − 调拨（即时调拨语义）")
    void remainingAfterMove() {
        assertThat(StockTransferPolicy.remainingInFromWarehouse(new BigDecimal("100"), new BigDecimal("30")))
                .isEqualByComparingTo("70");
        assertThat(StockTransferPolicy.remainingInFromWarehouse(null, new BigDecimal("30"))).isNull();
    }
}
