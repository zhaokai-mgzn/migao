// case_ids: RPT-005
package com.migao.admin.service;

import com.migao.admin.dto.ReceivableAgingReportView;
import com.migao.admin.dto.ReceivableAgingResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 应收账龄**报表**（issue #7376 段 5）：报表中心不重算分档，只把 P0-2 的账龄底稿套上报表三条口径。
 *
 * <p>本类只判「报表侧的那一层」，账龄分档规则本身由 {@code ReceivableAgingTest} 逐格承担 ——
 * 两处各判各的，避免把「分档算错」和「报表把空数据画成 0」混成一个红。</p>
 */
@DisplayName("账龄报表：空数据合计为 null / 合计=明细之和 / 单数单列 / 范围下传")
class ReportReceivableAgingServiceTest {

    private CustomerService customerService;
    private ReportService service;

    @BeforeEach
    void setUp() {
        customerService = Mockito.mock(CustomerService.class);
        service = new ReportService(null, null, null, null, null, null,
                new com.migao.admin.time.BusinessClock(), customerService, null);
    }

    private static ReceivableAgingResponse.BucketAmount bucket(String code, String label, String amount, int count) {
        return ReceivableAgingResponse.BucketAmount.builder()
                .bucket(code).label(label)
                .amount(new BigDecimal(amount)).orderCount(count)
                .build();
    }

    private static ReceivableAgingResponse.CustomerAging customer(String name, String total, String overdue,
                                                                 List<ReceivableAgingResponse.BucketAmount> buckets) {
        return ReceivableAgingResponse.CustomerAging.builder()
                .customerName(name).customerPhone("1380000000" + name.length())
                .paymentTermsDays(30)
                .total(new BigDecimal(total)).overdue(new BigDecimal(overdue))
                .buckets(buckets)
                .build();
    }

    @Test
    @DisplayName("🔴 空数据 ≠ 0：没有欠款单 ⇒ hasData=false 且 totals=null（不是应收 0.00）")
    void emptyAgingHasNullTotalsNotZero() {
        when(customerService.receivableAging(eq(1L), isNull())).thenReturn(
                ReceivableAgingResponse.builder()
                        .asOf(LocalDate.of(2026, 10, 23))
                        .totalOutstanding(BigDecimal.ZERO.setScale(2))
                        .totalOverdue(BigDecimal.ZERO.setScale(2))
                        .buckets(List.of(
                                bucket("NOT_DUE", "未到期", "0", 0),
                                bucket("DAYS_1_30", "逾期 1-30 天", "0", 0)))
                        .customers(List.of())
                        .build());

        ReceivableAgingReportView view = service.receivableAging(1L, null);

        assertThat(view.isHasData()).isFalse();
        assertThat(view.getTotals()).isNull();          // 🔴 不是 0
        assertThat(view.getCustomerCount()).isZero();
        // 五档照旧给出（页面据此画「每档 0」的结构，但合计位置写「暂无数据」）
        assertThat(view.getBuckets()).hasSize(2);
    }

    @Test
    @DisplayName("合计 = 明细之和：totals.outstanding == Σ客户行 == Σ五档；单数 = Σ各档单数")
    void totalsEqualSumOfRows() {
        var c1 = customer("张记布艺", "1200.00", "200.00", List.of(
                bucket("NOT_DUE", "未到期", "1000.00", 1),
                bucket("DAYS_1_30", "逾期 1-30 天", "200.00", 1)));
        var c2 = customer("李家窗帘", "800.00", "0.00", List.of(
                bucket("NOT_DUE", "未到期", "800.00", 2)));
        when(customerService.receivableAging(eq(1L), isNull())).thenReturn(
                ReceivableAgingResponse.builder()
                        .asOf(LocalDate.of(2026, 10, 23))
                        .totalOutstanding(new BigDecimal("2000.00"))
                        .totalOverdue(new BigDecimal("200.00"))
                        .buckets(List.of(
                                bucket("NOT_DUE", "未到期", "1800.00", 3),
                                bucket("DAYS_1_30", "逾期 1-30 天", "200.00", 1)))
                        .customers(List.of(c1, c2))
                        .build());

        ReceivableAgingReportView view = service.receivableAging(1L, null);

        assertThat(view.isHasData()).isTrue();
        assertThat(view.getCustomerCount()).isEqualTo(2);
        assertThat(view.getTotals().getOutstanding()).isEqualByComparingTo("2000.00");
        // 恒等式（同一份读数三种算法的交叉验证）
        assertThat(view.getTotals().getOutstanding()).isEqualByComparingTo(
                view.getCustomers().stream().map(ReceivableAgingResponse.CustomerAging::getTotal)
                        .reduce(BigDecimal.ZERO, BigDecimal::add));
        assertThat(view.getTotals().getOutstanding()).isEqualByComparingTo(
                view.getBuckets().stream().map(ReceivableAgingResponse.BucketAmount::getAmount)
                        .reduce(BigDecimal.ZERO, BigDecimal::add));
        // 单数单列（金额里读不出「欠了多少张单」）
        assertThat(view.getTotals().getOrderCount()).isEqualTo(4);
        assertThat(view.getTotals().getOverdue()).isEqualByComparingTo("200.00");
    }

    @Test
    @DisplayName("数据范围下传：self 范围把制单人原样交给账龄真值源（报表不自己裁单）")
    void scopeOwnerIsPassedThroughToTheAgingTruthSource() {
        when(customerService.receivableAging(eq(7L), eq("u-42"))).thenReturn(
                ReceivableAgingResponse.builder()
                        .asOf(LocalDate.of(2026, 10, 23))
                        .totalOutstanding(new BigDecimal("100.00"))
                        .totalOverdue(BigDecimal.ZERO.setScale(2))
                        .buckets(List.of(bucket("NOT_DUE", "未到期", "100.00", 1)))
                        .customers(List.of(customer("王家", "100.00", "0.00",
                                List.of(bucket("NOT_DUE", "未到期", "100.00", 1)))))
                        .build());

        ReceivableAgingReportView view = service.receivableAging(7L, "u-42");

        assertThat(view.getTotals().getOutstanding()).isEqualByComparingTo("100.00");
        // 范围必须交给真值源（在这里自己过滤 = 账龄口径分叉成两份）
        verify(customerService).receivableAging(7L, "u-42");
        verify(customerService, Mockito.never()).receivableAging(any(), isNull());
    }
}
