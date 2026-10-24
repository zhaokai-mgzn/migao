package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;

/**
 * 提交审批申请（issue #7374）。
 *
 * <p>⚠️ `tenantId` 由服务端从上下文填（不接受客户端递交租户 —— 那等于让调用方挑库）。</p>
 */
@Data
public class ApprovalRequest {

    /** 五类之一：credit_override / price_change / refund / purchase_over / stocktake_diff */
    private String objectType;

    /** 定位业务对象的键（客户手机号 / 订单号 / 采购单 id） */
    private String objectRef;

    /** 人读标签（客户名 / 单号），上屏用 */
    private String objectLabel;

    /** 钱：超多少 / 退多少 / 超预算多少（非钱类可为空） */
    private BigDecimal amount;

    /** 类型专属细节（改价旧价/新价等）：JSON 字符串 */
    private String payload;

    /** 申请理由 */
    private String reason;

    private Long tenantId;
}
