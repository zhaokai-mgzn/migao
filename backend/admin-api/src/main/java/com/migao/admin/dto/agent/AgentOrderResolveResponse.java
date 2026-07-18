package com.migao.admin.dto.agent;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;

/**
 * Agent 订单解析响应。
 * GET /api/admin/agent/orders/resolve 的返回值。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AgentOrderResolveResponse {

    /** 订单 UUID */
    private String id;

    /** 订单号（ORD-xxx） */
    private String orderNo;

    /** 客户姓名 */
    private String customerName;

    /** 订单状态 */
    private String status;

    /** 订单金额 */
    private BigDecimal totalAmount;

    /** 商品件数 */
    private Integer itemCount;
}
