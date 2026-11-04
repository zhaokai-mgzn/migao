// case_ids: MC-199
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.Order;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.time.BusinessClock;
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
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * {@link OrderFeeSupport}（issue #8191，P2-1c 从 {@code OrderService} 搬出的财务流水族）的**行为判据**。
 *
 * <p>钉四件事：① 实收取数口径（`actualAmount` 缺省才退回 `totalAmount`）；② 只有「订单非空 + 金额 > 0」才落流水，
 * 且 `type / amount / status / operator / remark / 单号` 逐字；③ 落流水**失败不影响主流程**（吞异常、只告警）；
 * ④ 流水号 = 当天最大序号 +1、`%10000` 回绕、读不到历史时从 0001 开始。</p>
 *
 * <p><b>红证</b>：把「金额 ≤ 0 直接返回」删掉 ⇒ 对应断言红；把 catch 去掉 ⇒ fail-soft 那条红；
 * 把实收取数改成只读 `totalAmount` ⇒ 第一条红。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class OrderFeeSupportTest {

    @Mock
    private FinanceTransactionMapper financeTransactionMapper;

    private OrderFeeSupport feeSupport;

    @BeforeEach
    void setUp() {
        feeSupport = new OrderFeeSupport(financeTransactionMapper,
                new BusinessClock(Clock.fixed(Instant.parse("2026-11-04T02:00:00Z"), ZoneOffset.UTC)));
    }

    @Test
    @DisplayName("实收取数：actualAmount 优先；actualAmount 为空才退回 totalAmount")
    void effectiveAmountFallsBackToTotal() {
        Order withActual = order(new BigDecimal("100.00"), new BigDecimal("88.00"));
        Order withoutActual = order(new BigDecimal("100.00"), null);

        assertThat(feeSupport.effectiveActualAmount(withActual).toPlainString()).isEqualTo("88.00");
        assertThat(feeSupport.effectiveActualAmount(withoutActual).toPlainString()).isEqualTo("100.00");
    }

    @Test
    @DisplayName("收款流水：字段与单号逐字（FIN-<业务日>-0001），单号取当天最大序号 +1")
    void recordsIncomeTransactionVerbatim() {
        when(financeTransactionMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);

        feeSupport.recordFinanceTransaction(order(new BigDecimal("100.00"), new BigDecimal("88.00")),
                "income", "订单确认收款");

        ArgumentCaptor<FinanceTransaction> captor = ArgumentCaptor.forClass(FinanceTransaction.class);
        verify(financeTransactionMapper).insert(captor.capture());
        FinanceTransaction txn = captor.getValue();
        assertThat(txn.getTransactionNo()).isEqualTo("FIN-20261104-0001");
        assertThat(txn.getOrderId()).isEqualTo("order-1");
        assertThat(txn.getOrderNo()).isEqualTo("ORD-1");
        assertThat(txn.getType()).isEqualTo("income");
        assertThat(txn.getAmount().toPlainString()).isEqualTo("88.00");
        assertThat(txn.getStatus()).isEqualTo("success");
        assertThat(txn.getOperator()).isEqualTo("系统");
        assertThat(txn.getRemark()).isEqualTo("订单确认收款");
    }

    @Test
    @DisplayName("不落流水的两种情形：订单为空 / 金额为 0 或负")
    void skipsWhenOrderMissingOrAmountNotPositive() {
        // 4 参重载才是「订单为空就返回」的那条守卫（3 参重载会先取实收，对空订单本就 NPE —— 既有行为不变）
        feeSupport.recordFinanceTransaction(null, new BigDecimal("88.00"), "income", "空订单");
        feeSupport.recordFinanceTransaction(order(new BigDecimal("100.00"), BigDecimal.ZERO),
                BigDecimal.ZERO, "income", "零金额");
        feeSupport.recordFinanceTransaction(order(new BigDecimal("100.00"), null),
                new BigDecimal("-1.00"), "refund", "负数");

        verify(financeTransactionMapper, never()).insert(any(FinanceTransaction.class));
    }

    @Test
    @DisplayName("落流水失败不影响主流程：mapper 抛异常 ⇒ 不向外抛")
    void swallowsMapperFailure() {
        when(financeTransactionMapper.insert(any(FinanceTransaction.class)))
                .thenThrow(new IllegalStateException("db down"));

        assertThatCode(() -> feeSupport.recordFinanceTransaction(
                order(new BigDecimal("100.00"), new BigDecimal("88.00")), "income", "订单确认收款"))
                .as("对账流水是辅助数据：写失败只告警，不得让订单主流程失败")
                .doesNotThrowAnyException();
    }

    @Test
    @DisplayName("流水号：当天最大序号 +1、按 10000 回绕；读不到历史 ⇒ 0001")
    void transactionNoSequenceAndWrap() {
        when(financeTransactionMapper.selectOne(any(LambdaQueryWrapper.class)))
                .thenReturn(txn("FIN-20261104-0007"));
        assertThat(feeSupport.generateFinanceTransactionNo(1L)).isEqualTo("FIN-20261104-0008");

        when(financeTransactionMapper.selectOne(any(LambdaQueryWrapper.class)))
                .thenReturn(txn("FIN-20261104-9999"));
        assertThat(feeSupport.generateFinanceTransactionNo(1L)).isEqualTo("FIN-20261104-0000");

        when(financeTransactionMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        assertThat(feeSupport.generateFinanceTransactionNo(1L)).isEqualTo("FIN-20261104-0001");
    }

    private static Order order(BigDecimal total, BigDecimal actual) {
        return Order.builder()
                .id("order-1")
                .tenantId(1L)
                .orderNo("ORD-1")
                .totalAmount(total)
                .actualAmount(actual)
                .build();
    }

    private static FinanceTransaction txn(String no) {
        FinanceTransaction txn = new FinanceTransaction();
        txn.setTransactionNo(no);
        return txn;
    }
}
