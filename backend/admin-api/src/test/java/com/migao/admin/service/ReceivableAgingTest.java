// case_ids: AR-001
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 应收账龄分档（issue #7370，P0-2 段 2）—— **边界逐格**判据。
 *
 * <p>为什么单独考一个纯函数：账龄的错几乎全在边界上（到期日当天算不算逾期、第 30/31 天怎么跳档），
 * 而错的时候屏幕上的数字**依然合理**。埋在 SQL 的 {@code CASE WHEN} 里就只能靠「上线后看看对不对」。</p>
 *
 * <p>红证方向：把 {@code bucketOf} 的 {@code <= 0} 改成 {@code < 0} ⇒ 到期日当天的单当场跳到「逾期 1-30」，
 * {@link #dueDateItselfIsNotOverdue} 红。</p>
 */
@DisplayName("应收账龄：到期日/逾期天数/五档边界/净应收余额")
class ReceivableAgingTest {

    private static final LocalDate TODAY = LocalDate.of(2026, 10, 20);

    @Test
    @DisplayName("到期日 = 下单日 + 账期；账期 null/0 ⇒ 现结（到期日 = 下单日，不是「永不到期」）")
    void dueDateFollowsTerms() {
        LocalDate order = LocalDate.of(2026, 10, 1);
        assertThat(ReceivableAging.dueDate(order, null)).isEqualTo(order);
        assertThat(ReceivableAging.dueDate(order, 0)).isEqualTo(order);
        assertThat(ReceivableAging.dueDate(order, 30)).isEqualTo(LocalDate.of(2026, 10, 31));
        // 负数账期没有物理意义 ⇒ 按现结算（不抛错：存量脏数据不该让整页 500）
        assertThat(ReceivableAging.dueDate(order, -5)).isEqualTo(order);
        assertThatThrownBy(() -> ReceivableAging.dueDate(null, 30))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    @DisplayName("逾期天数：到期日当天 = 0（不算逾期）；隔一天 = 1")
    void overdueDaysBoundary() {
        assertThat(ReceivableAging.overdueDays(TODAY, TODAY)).isZero();
        assertThat(ReceivableAging.overdueDays(TODAY.plusDays(1), TODAY))
                .as("到期日还在明天 ⇒ 未到期（负数）").isNegative();
        assertThat(ReceivableAging.overdueDays(TODAY.minusDays(1), TODAY)).isEqualTo(1);
        assertThat(ReceivableAging.overdueDays(TODAY.minusDays(30), TODAY)).isEqualTo(30);
        assertThat(ReceivableAging.overdueDays(TODAY.minusDays(91), TODAY)).isEqualTo(91);
    }

    @Test
    @DisplayName("🔴 五档边界逐格：0/负数→未到期 · 1→1-30 · 30→1-30 · 31→31-60 · 60→31-60 · 61→61-90 · 90→61-90 · 91→90+")
    void bucketBoundaries() {
        assertThat(ReceivableAging.bucketOf(0)).isEqualTo(ReceivableAging.Bucket.NOT_DUE);
        assertThat(ReceivableAging.bucketOf(-3)).isEqualTo(ReceivableAging.Bucket.NOT_DUE);
        assertThat(ReceivableAging.bucketOf(1)).isEqualTo(ReceivableAging.Bucket.DAYS_1_30);
        assertThat(ReceivableAging.bucketOf(30)).isEqualTo(ReceivableAging.Bucket.DAYS_1_30);
        assertThat(ReceivableAging.bucketOf(31)).isEqualTo(ReceivableAging.Bucket.DAYS_31_60);
        assertThat(ReceivableAging.bucketOf(60)).isEqualTo(ReceivableAging.Bucket.DAYS_31_60);
        assertThat(ReceivableAging.bucketOf(61)).isEqualTo(ReceivableAging.Bucket.DAYS_61_90);
        assertThat(ReceivableAging.bucketOf(90)).isEqualTo(ReceivableAging.Bucket.DAYS_61_90);
        assertThat(ReceivableAging.bucketOf(91)).isEqualTo(ReceivableAging.Bucket.DAYS_90_PLUS);
        assertThat(ReceivableAging.bucketOf(1000)).isEqualTo(ReceivableAging.Bucket.DAYS_90_PLUS);
        // 枚举顺序 = 上屏顺序（报表按它排，改顺序会让「未到期」跑到最后）
        assertThat(ReceivableAging.Bucket.values()).containsExactly(
                ReceivableAging.Bucket.NOT_DUE, ReceivableAging.Bucket.DAYS_1_30,
                ReceivableAging.Bucket.DAYS_31_60, ReceivableAging.Bucket.DAYS_61_90,
                ReceivableAging.Bucket.DAYS_90_PLUS);
    }

    @Test
    @DisplayName("到期日当天归「未到期」（客户今天付款仍算及时 —— 不许被标逾期）")
    void dueDateItselfIsNotOverdue() {
        // 账期 30 天、下单 2026-09-20 ⇒ 到期 2026-10-20 = 今天 ⇒ 未到期
        assertThat(ReceivableAging.bucketFor(LocalDate.of(2026, 9, 20), 30, TODAY))
                .isEqualTo(ReceivableAging.Bucket.NOT_DUE);
        // 昨日到期 ⇒ 逾期 1 天
        assertThat(ReceivableAging.bucketFor(LocalDate.of(2026, 9, 19), 30, TODAY))
                .isEqualTo(ReceivableAging.Bucket.DAYS_1_30);
        // 现结客户（账期 null）今天下单 ⇒ 未到期；昨天下的单 ⇒ 逾期 1 天
        assertThat(ReceivableAging.bucketFor(TODAY, null, TODAY)).isEqualTo(ReceivableAging.Bucket.NOT_DUE);
        assertThat(ReceivableAging.bucketFor(TODAY.minusDays(1), null, TODAY))
                .isEqualTo(ReceivableAging.Bucket.DAYS_1_30);
    }

    @Test
    @DisplayName("应收余额 = 应收 − 已退（已收/未收由订单 paid_at 定性）；退多了归 0，不出负数应收")
    void remainingIsNetReceivable() {
        assertThat(ReceivableAging.remaining(new BigDecimal("1000"), null)).isEqualByComparingTo("1000");
        // 退款冲减应收：退 200 ⇒ 还欠 800
        assertThat(ReceivableAging.remaining(new BigDecimal("1000"), new BigDecimal("200")))
                .isEqualByComparingTo("800");
        // 退超过货值 ⇒ 0（不显示负数应收）
        assertThat(ReceivableAging.remaining(new BigDecimal("1000"), new BigDecimal("1200")))
                .isEqualByComparingTo("0");
        // 两位小数（钱只有两位小数的物理意义）
        assertThat(ReceivableAging.remaining(new BigDecimal("1000.005"), null).scale()).isEqualTo(2);
    }

    private static com.migao.admin.dto.ReceivableAgingRow row(String phone, String name, String amount,
                                                             String refunded, LocalDate orderDate) {
        return com.migao.admin.dto.ReceivableAgingRow.builder()
                .orderId("o-" + phone + orderDate)
                .orderNo("SO-" + orderDate)
                .customerName(name)
                .customerPhone(phone)
                .receivable(new BigDecimal(amount))
                .refunded(refunded == null ? null : new BigDecimal(refunded))
                .remaining(new BigDecimal(amount))
                .businessDate(orderDate)
                .build();
    }

    @Test
    @DisplayName("🔴 汇总恒等式：totalOutstanding == Σ五档 == Σ客户行（三处对不上就是钱丢了或重复计）")
    void summaryKeepsTheIdentity() {
        var rows = java.util.List.of(
                // 未到期：账期 30、下单今天 ⇒ 应收 1000
                row("13800000001", "杭州布行", "1000", null, TODAY),
                // 逾期 5 天：账期 30、下单 35 天前 ⇒ 到期 5 天前，应收 2000（退 500 ⇒ 余额 1500）
                row("13800000001", "杭州布行", "2000", "500", TODAY.minusDays(35)),
                // 逾期 45 天：账期 15、下单 60 天前 ⇒ 到期 45 天前，应收 3000
                row("13800000002", "绍兴染厂", "3000", null, TODAY.minusDays(60)));
        var terms = java.util.Map.of("13800000001", 30, "13800000002", 15);

        var report = ReceivableAging.summarize(rows, terms, TODAY);

        // 未到期 1000；1-30 档 1500（2000-500）；31-60 档 3000 ⇒ 合计 5500，逾期 4500
        assertThat(report.getTotalOutstanding()).isEqualByComparingTo("5500");
        assertThat(report.getTotalOverdue()).isEqualByComparingTo("4500");
        assertThat(report.getAsOf()).isEqualTo(TODAY);

        BigDecimal sumBuckets = report.getBuckets().stream()
                .map(com.migao.admin.dto.ReceivableAgingResponse.BucketAmount::getAmount)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
        assertThat(sumBuckets).as("Σ五档 == 合计").isEqualByComparingTo(report.getTotalOutstanding());

        BigDecimal sumCustomers = report.getCustomers().stream()
                .map(com.migao.admin.dto.ReceivableAgingResponse.CustomerAging::getTotal)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
        assertThat(sumCustomers).as("Σ客户行 == 合计").isEqualByComparingTo(report.getTotalOutstanding());

        // 客户分行：杭州布行 1000 + 1500 = 2500（其中逾期 1500）；绍兴染厂 3000（全逾期）
        assertThat(report.getCustomers()).hasSize(2);
        var hangzhou = report.getCustomers().stream().filter(c -> "13800000001".equals(c.getCustomerPhone())).findFirst().orElseThrow();
        assertThat(hangzhou.getTotal()).isEqualByComparingTo("2500");
        assertThat(hangzhou.getOverdue()).isEqualByComparingTo("1500");
        assertThat(hangzhou.getPaymentTermsDays()).isEqualTo(30);
        // 笔数也逐档给出（金额对但笔数错同样是错）
        assertThat(report.getBuckets().get(0).getOrderCount()).isEqualTo(1);   // 未到期 1 笔
        assertThat(report.getBuckets().get(1).getOrderCount()).isEqualTo(1);   // 1-30 1 笔
        assertThat(report.getBuckets().get(2).getOrderCount()).isEqualTo(1);   // 31-60 1 笔
    }

    @Test
    @DisplayName("没留电话的散客单不丢钱：归到具名分组（应收面不许因为缺字段就静默消失）")
    void rowsWithoutPhoneAreKept() {
        var rows = java.util.List.of(
                row(null, null, "800", null, TODAY.minusDays(10)),
                row("13800000009", "宁波布行", "200", null, TODAY));
        var report = ReceivableAging.summarize(rows, java.util.Map.of(), TODAY);

        assertThat(report.getTotalOutstanding()).isEqualByComparingTo("1000");
        assertThat(report.getCustomers()).hasSize(2);
        assertThat(report.getCustomers().stream().anyMatch(c -> c.getCustomerPhone() == null)).isTrue();
    }
}
