package com.migao.admin.dto.agent;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * Agent 专用订单创建请求。
 * subtotal 可选 → 服务端按 quantity × unitPrice 重算。
 * productName 必填，productId 可选。
 *
 * 参数范围约束（issue #3622）：quantity/unitPrice/subtotal 与表单路径
 * `OrderCreateRequest.OrderItemRequest` **同口径**（@NotNull/@Positive）——Agent 路径是
 * ai-agent 唯一实走的路径，此前该 DTO 零约束注解 + Controller 无 @Valid，导致
 * **负数量/负单价可落库**（负金额，且「需求量 ≤ 库存」对负需求恒真 → 超卖防线被绕过）。
 * 注意：`items` 必须带 `@Valid` 才能把约束级联到元素；而 `createOrderForAgent` 手工
 * new `OrderCreateRequest` 转交 `createOrder()` 的路径**不过 Bean Validation**，
 * 故 `OrderService.createOrder` 另有显式判定（双保险，见该方法注释）。
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

    /**
     * 下单用户 ID（可选，内部服务调用时由 ai-agent 透传 X-User-Id；
     * C 端小布下单时绑定真实用户，供数据隔离查询）
     */
    private String userId;

    /** 商品明细（必填，至少一项；@Valid 让元素级约束级联生效，issue #3622） */
    @Valid
    private List<AgentOrderItem> items;

    // ---- 订单商品子对象 ----

    @Data
    public static class AgentOrderItem {
        /** 商品名称（必填） */
        private String productName;

        /** 商品 ID（可选，可为 UUID / 名称） */
        private String productId;

        /** SKU 编码（可选；提供且可解析时，服务端按 SKU 权威价严格校验 unitPrice，GB/T 47746-2026 M3，issue #2806） */
        private String skuCode;

        /** 颜色名称（可选；无 skuCode 时兜底解析 SKU 用） */
        private String colorName;

        /** 数量（必填，必须大于 0：负数量会算出负金额并绕过库存校验，issue #3622） */
        @NotNull(message = "数量不能为空")
        @Positive(message = "数量必须大于 0")
        private Integer quantity;

        /** 单价（必填，必须大于 0） */
        @NotNull(message = "单价不能为空")
        @Positive(message = "单价必须大于 0")
        private BigDecimal unitPrice;

        /** 小计（可选，空则服务端重算为 quantity × unitPrice；提供了就必须大于 0） */
        @Positive(message = "小计必须大于 0")
        private BigDecimal subtotal;

        /** 宽度（可选） */
        private BigDecimal width;

        /** 高度（可选） */
        private BigDecimal height;

        /** 加工信息（可选，透传给 admin-api） */
        private Object processingInfo;
    }
}
