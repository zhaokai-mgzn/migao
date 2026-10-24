package com.migao.admin.dto;

import lombok.Builder;
import lombok.Data;

import java.math.BigDecimal;

/**
 * 客户授信与往来读数（issue #7370）。
 *
 * <p>{@code creditLimit == null} 表示**未启用授信**（老客户默认），此时 {@code available} 也为 null ——
 * 「未启用」与「额度 0」必须在读数上可区分（后者 available = 0 且任何赊销都被拒）。
 */
@Data
@Builder
public class CreditStatusResponse {

    private String customerId;

    /** 授信额度：null = 未启用 */
    private BigDecimal creditLimit;

    /** 账期天数：null = 未设置 */
    private Integer paymentTermsDays;

    /** 已欠 = 该客户未结清订单金额合计（见 CreditService 的口径说明） */
    private BigDecimal outstanding;

    /** 可用额度 = 额度 - 已欠；额度未启用时为 null */
    private BigDecimal available;
}
