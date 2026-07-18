package com.migao.admin.dto.agent;

import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * Agent 专用订单创建请求。
 * subtotal 可选 → 服务端按 quantity × unitPrice 重算。
 * productName 必填，productId 可选。
 */
@Data
public class AgentOrderCreateRequest {

    /** 客户姓名（必填） */
    private String customerName;

    /** 客户电话（必填，服务端校验 11 位手机号） */
    private String customerPhone;

    /** 客户收货地址（可选） */
    private String customerAddress;

    /** 订单备注（可选） */
    private String remark;

    /** 商品明细（必填，至少一项） */
    private List<AgentOrderItem> items;

    // ---- 订单商品子对象 ----

    @Data
    public static class AgentOrderItem {
        /** 商品名称（必填） */
        private String productName;

        /** 商品 ID（可选，可为 UUID / 名称） */
        private String productId;

        /** 数量（必填） */
        private Integer quantity;

        /** 单价（必填） */
        private BigDecimal unitPrice;

        /** 小计（可选，空则服务端重算为 quantity × unitPrice） */
        private BigDecimal subtotal;

        /** 宽度（可选） */
        private BigDecimal width;

        /** 高度（可选） */
        private BigDecimal height;

        /** 加工信息（可选，透传给 admin-api） */
        private Object processingInfo;
    }
}
