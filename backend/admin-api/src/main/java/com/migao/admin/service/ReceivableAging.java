package com.migao.admin.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;

/**
 * 应收账龄分档（issue #7370，P0-2 段 2）—— **纯函数**，逐档边界都有判据。
 *
 * <h3>为什么分档要单独一个类</h3>
 * <p>账龄的「错」几乎全在边界上：到期日**当天**算不算逾期、第 30 天归哪档、第 31 天怎么跳档。
 * 把这些判断埋在 SQL 的 {@code CASE WHEN} 里，就只能靠「上线后看数字对不对」发现错，
 * 而数字看起来总是合理的。所以这里钉成纯函数 + 逐格判据（{@code ReceivableAgingTest}）。</p>
 *
 * <h3>口径（逐条可验）</h3>
 * <ol>
 *   <li><b>到期日当天归「未到期」</b>：逾期天数 = 今天 − 到期日，{@code <= 0} 即未到期
 *       （客户今天付款仍算及时，不该被标成逾期）。</li>
 *   <li><b>分档为左闭右闭的整数日</b>：1–30 / 31–60 / 61–90 / 91+。第 30 天属 30 档、第 31 天跳 31 档。</li>
 *   <li><b>账期为 {@code null} 或 0 ⇒ 到期日 = 下单日</b>（现结：下单当天就该收钱），
 *       而不是「永不到期」—— 后者会让这类客户的应收永远不出现在逾期面上。</li>
 *   <li>金额一律 2 位小数（钱只有两位小数的物理意义）。</li>
 * </ol>
 */
public final class ReceivableAging {

    /** 账龄档（顺序 = 上屏顺序；枚举名即稳定标识，中文名由前端/报表翻译）。 */
    public enum Bucket {
        /** 未到期（含到期日当天）。 */
        NOT_DUE("未到期"),
        /** 逾期 1–30 天。 */
        DAYS_1_30("逾期 1-30 天"),
        /** 逾期 31–60 天。 */
        DAYS_31_60("逾期 31-60 天"),
        /** 逾期 61–90 天。 */
        DAYS_61_90("逾期 61-90 天"),
        /** 逾期 91 天以上。 */
        DAYS_90_PLUS("逾期 90 天以上");

        private final String label;

        Bucket(String label) {
            this.label = label;
        }

        public String label() {
            return label;
        }
    }

    private ReceivableAging() {
    }

    /**
     * 到期日 = 下单日 + 账期天数。
     *
     * @param orderDate 下单日（业务时区）
     * @param termsDays 账期天数（{@code null} 或 0 ⇒ 现结，到期日 = 下单日）
     */
    public static LocalDate dueDate(LocalDate orderDate, Integer termsDays) {
        if (orderDate == null) {
            throw new IllegalArgumentException("下单日不能为空");
        }
        int days = termsDays == null ? 0 : Math.max(termsDays, 0);
        return orderDate.plusDays(days);
    }

    /** 逾期天数：{@code <= 0} 表示未到期（含到期日当天）。 */
    public static long overdueDays(LocalDate dueDate, LocalDate today) {
        return ChronoUnit.DAYS.between(dueDate, today);
    }

    /** 分档（边界逐值：0 未到期 / 1–30 / 31–60 / 61–90 / 91+）。 */
    public static Bucket bucketOf(long overdueDays) {
        if (overdueDays <= 0) {
            return Bucket.NOT_DUE;
        }
        if (overdueDays <= 30) {
            return Bucket.DAYS_1_30;
        }
        if (overdueDays <= 60) {
            return Bucket.DAYS_31_60;
        }
        if (overdueDays <= 90) {
            return Bucket.DAYS_61_90;
        }
        return Bucket.DAYS_90_PLUS;
    }

    /** 便捷组合：按「下单日 + 账期 + 今天」直接取档。 */
    public static Bucket bucketFor(LocalDate orderDate, Integer termsDays, LocalDate today) {
        return bucketOf(overdueDays(dueDate(orderDate, termsDays), today));
    }

    /**
     * 该笔**未收款订单**的应收余额：{@code 应收 − 已退}，负数按 0（退款超过货值 ⇒ 不显示负数应收）。
     *
     * <p>「已收/未收」由订单的 {@code paid_at} 定性（与授信闸门同一真值源），不由本函数推断：
     * 把 {@code actual_amount IS NULL} 读成「已收满」（既有对账页的兜底口径）会让**未登记的收款**
     * 变成「已付清」—— 欠款静默消失是账龄面最不能接受的错。</p>
     *
     * @param receivable 订单应收（totalAmount）
     * @param refunded   该单退款合计（null ⇒ 0）
     */
    public static BigDecimal remaining(BigDecimal receivable, BigDecimal refunded) {
        BigDecimal rest = nz(receivable).subtract(nz(refunded));
        if (rest.signum() < 0) {
            return BigDecimal.ZERO.setScale(2, RoundingMode.UNNECESSARY);
        }
        return rest.setScale(2, RoundingMode.HALF_UP);
    }

    private static BigDecimal nz(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }

    /**
     * 把单笔应收行**汇总成账龄读面**（纯函数：不碰库、不看时钟 —— 今天由调用方给）。
     *
     * <p>恒等式（判据复算）：{@code totalOutstanding == Σ五档 == Σ customers[].total}。
     * 三个数只要有一个对不上，就说明某笔钱被丢了或重复计了。</p>
     *
     * @param rows         每笔余额 &gt; 0 的应收（余额由 SQL 与 {@link #remaining} 同口径给出）
     * @param termsByPhone 电话 → 账期天数（缺失 = 未设置 ⇒ 现结）
     * @param today        业务「今天」
     */
    public static com.migao.admin.dto.ReceivableAgingResponse summarize(
            java.util.List<com.migao.admin.dto.ReceivableAgingRow> rows,
            java.util.Map<String, Integer> termsByPhone,
            LocalDate today) {
        java.util.Map<Bucket, BigDecimal> globalAmount = new java.util.EnumMap<>(Bucket.class);
        java.util.Map<Bucket, Integer> globalCount = new java.util.EnumMap<>(Bucket.class);
        java.util.Map<String, Agg> byCustomer = new java.util.LinkedHashMap<>();
        BigDecimal total = BigDecimal.ZERO;
        BigDecimal overdue = BigDecimal.ZERO;

        for (com.migao.admin.dto.ReceivableAgingRow row : rows) {
            Integer terms = row.getCustomerPhone() == null ? null : termsByPhone.get(row.getCustomerPhone());
            // ⚠️ 业务日期换算**不在这里**：调用方传进来的 businessDate 必须是 +08 口径的那一天
            // （换算在 CustomerService 用 BusinessClock 做，见 #3802 —— 日界只许有一个来源）。
            Bucket bucket = bucketFor(row.getBusinessDate(), terms, today);
            BigDecimal amount = remaining(row.getReceivable(), row.getRefunded());
            if (amount.signum() == 0) {
                continue;
            }
            total = total.add(amount);
            globalAmount.merge(bucket, amount, BigDecimal::add);
            globalCount.merge(bucket, 1, Integer::sum);
            if (bucket != Bucket.NOT_DUE) {
                overdue = overdue.add(amount);
            }

            String key = row.getCustomerPhone() == null ? "__no_phone__" : row.getCustomerPhone();
            Agg agg = byCustomer.computeIfAbsent(key, k -> new Agg(
                    row.getCustomerName() == null ? "（未留电话的散客单）" : row.getCustomerName(),
                    row.getCustomerPhone(), terms));
            agg.amounts.merge(bucket, amount, BigDecimal::add);
            agg.counts.merge(bucket, 1, Integer::sum);
            agg.total = agg.total.add(amount);
            if (bucket != Bucket.NOT_DUE) {
                agg.overdue = agg.overdue.add(amount);
            }
        }

        java.util.List<com.migao.admin.dto.ReceivableAgingResponse.BucketAmount> buckets = new java.util.ArrayList<>();
        for (Bucket bucket : Bucket.values()) {
            buckets.add(com.migao.admin.dto.ReceivableAgingResponse.BucketAmount.builder()
                    .bucket(bucket.name()).label(bucket.label())
                    .amount(scale(globalAmount.get(bucket)))
                    .orderCount(globalCount.getOrDefault(bucket, 0))
                    .build());
        }

        java.util.List<com.migao.admin.dto.ReceivableAgingResponse.CustomerAging> customers = new java.util.ArrayList<>();
        for (Agg agg : byCustomer.values()) {
            java.util.List<com.migao.admin.dto.ReceivableAgingResponse.BucketAmount> own = new java.util.ArrayList<>();
            for (Bucket bucket : Bucket.values()) {
                own.add(com.migao.admin.dto.ReceivableAgingResponse.BucketAmount.builder()
                        .bucket(bucket.name()).label(bucket.label())
                        .amount(scale(agg.amounts.get(bucket)))
                        .orderCount(agg.counts.getOrDefault(bucket, 0))
                        .build());
            }
            customers.add(com.migao.admin.dto.ReceivableAgingResponse.CustomerAging.builder()
                    .customerName(agg.name).customerPhone(agg.phone).paymentTermsDays(agg.terms)
                    .total(scale(agg.total)).overdue(scale(agg.overdue)).buckets(own)
                    .build());
        }
        customers.sort((a, b) -> b.getTotal().compareTo(a.getTotal()));

        return com.migao.admin.dto.ReceivableAgingResponse.builder()
                .asOf(today)
                .totalOutstanding(scale(total))
                .totalOverdue(scale(overdue))
                .buckets(buckets)
                .customers(customers)
                .build();
    }

    private static BigDecimal scale(BigDecimal value) {
        return value == null
                ? BigDecimal.ZERO.setScale(2)
                : value.setScale(2, RoundingMode.HALF_UP);
    }

    /** 单客户聚合的中间态。 */
    private static final class Agg {
        private final String name;
        private final String phone;
        private final Integer terms;
        private final java.util.Map<Bucket, BigDecimal> amounts = new java.util.EnumMap<>(Bucket.class);
        private final java.util.Map<Bucket, Integer> counts = new java.util.EnumMap<>(Bucket.class);
        private BigDecimal total = BigDecimal.ZERO;
        private BigDecimal overdue = BigDecimal.ZERO;

        private Agg(String name, String phone, Integer terms) {
            this.name = name;
            this.phone = phone;
            this.terms = terms;
        }
    }
}
