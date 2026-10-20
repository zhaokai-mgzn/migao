package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * 应收账龄读面（issue #7370，P0-2 段 2）：**全局合计 + 按客户分行**，每行五档。
 *
 * <p>📌 恒等式（判据）：{@code totalOutstanding == 五档之和 == Σ customers[].total}。
 * 三处只要有一处对不上就说明分档把某笔钱弄丢了（或重复计了）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ReceivableAgingResponse {

    /** 业务「今天」（分档基准，回显给前端，避免两边各算一次） */
    private LocalDate asOf;

    /** 应收余额合计 */
    private BigDecimal totalOutstanding;

    /** 已逾期合计（不含未到期） */
    private BigDecimal totalOverdue;

    /** 全局分档（顺序 = 上屏顺序：未到期 → 1-30 → 31-60 → 61-90 → 90+） */
    private List<BucketAmount> buckets;

    /** 按客户分行（金额倒序） */
    private List<CustomerAging> customers;

    /** 一档的金额与笔数。 */
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class BucketAmount {
        /** 稳定标识（NOT_DUE / DAYS_1_30 / …），前端按它翻译中文 */
        private String bucket;
        private String label;
        private BigDecimal amount;
        private int orderCount;
    }

    /** 单个客户的账龄分行。 */
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class CustomerAging {
        private String customerName;
        private String customerPhone;
        /** 账期天数（null = 未设置 ⇒ 现结口径） */
        private Integer paymentTermsDays;
        private BigDecimal total;
        private BigDecimal overdue;
        private List<BucketAmount> buckets;
    }
}
