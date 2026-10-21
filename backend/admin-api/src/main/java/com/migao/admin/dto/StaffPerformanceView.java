package com.migao.admin.dto;

import lombok.Builder;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 员工业绩报表（issue #7376，P1-4 段 3）。
 *
 * <p>🔴 三条口径与另两张报表一致：合计 = 明细之和；空数据时合计为 {@code null}（不是 0）；
 * **没有制单人的历史订单单独成一档**（"未记录"），不并进某个人的业绩里 —— 那会凭空给人加分。</p>
 */
@Data
@Builder
public class StaffPerformanceView {

    private String startDate;

    private String endDate;

    private boolean hasData;

    private List<Row> rows;

    private Totals totals;

    /** 没有制单人（存量订单 / C 端自助单）的订单数 —— 单列一档，不摊给任何人。 */
    private int unattributedOrders;

    @Data
    @Builder
    public static class Row {

        /** 制单人 id（`null` ⇒ 未记录）。 */
        private String staffId;

        private String staffName;

        private int orderCount;

        private BigDecimal revenue;

        /** 客单价 = 收入 / 单数（单数为 0 ⇒ null，不做 0 除）。 */
        private BigDecimal avgOrderValue;
    }

    @Data
    @Builder
    public static class Totals {

        private int orderCount;

        private BigDecimal revenue;

    }
}
