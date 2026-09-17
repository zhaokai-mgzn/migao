package com.migao.admin.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 订单创建请求 DTO
 */
@Data
public class OrderCreateRequest {

    /**
     * 客户姓名
     */
    @NotBlank(message = "客户姓名不能为空")
    private String customerName;

    /**
     * 客户电话（必填；格式校验与 agent 下单路径一致，保证订单携带有效手机号——
     * 用于售后联系、客户绑定归属回填、以及物流查询手机尾号）
     */
    @NotBlank(message = "客户电话不能为空")
    @Pattern(regexp = "^1[3-9]\\d{9}$", message = "手机号格式不正确，请输入11位中国大陆手机号")
    private String customerPhone;

    /**
     * 客户地址
     */
    private String customerAddress;

    /**
     * 备注
     */
    private String remark;

    /**
     * 下单用户 ID（可选；C 端小布下单时绑定真实用户，供数据隔离查询）
     */
    private String userId;

    /**
     * 实收款（用户输入的实际收款金额，默认等于订单总额）
     */
    private BigDecimal actualAmount;

    /**
     * 优惠金额（默认 0；应收 totalAmount - 优惠 discountAmount 应等于实收 actualAmount）
     */
    private BigDecimal discountAmount;

    /**
     * 订单明细列表
     */
    @NotEmpty(message = "订单明细不能为空")
    @Valid
    private List<OrderItemRequest> items;

    /**
     * 订单明细请求 DTO
     */
    @Data
    public static class OrderItemRequest {

        /**
         * 商品ID
         */
        private String productId;

        /**
         * 商品名称
         */
        @NotBlank(message = "商品名称不能为空")
        private String productName;

        /**
         * 数量（issue #3666 放宽为 DECIMAL(10,2)/BigDecimal；issue #3682 收紧下限为 1）：
         * 口径按计价方式——per_meter=米数、per_set=件数、per_area=宽×高（㎡）。
         * 这些口径**不都是整数**（2.8m × 3m = 8.4 ㎡），Integer 会截断成 8 →
         * 30 元/㎡ 的刺绣工艺少收 12.00 元。与 base_price/amount 的金额口径一致。
         *
         * <p>下限为什么是 1（而不是「&gt; 0」）：`OrderService` 对 quantity 取整数部分驱动
         * 库存/销量（`:1051` 库存校验 / `:1408` `deductStock` / `:1409` `increaseSalesCount`）
         * —— 0.5 → `needed = 0` 校验恒通过、扣 0 库存、销量 +0 → **订单成交但库存/销量零变动
         * 且无任何告警**。下限与表单页 `orders/new/page.tsx` 的 `min={1}` 同口径。</p>
         */
        @NotNull(message = "数量不能为空")
        @DecimalMin(value = "1", message = "数量不能小于 1")
        private BigDecimal quantity;

        /**
         * 单价
         */
        @NotNull(message = "单价不能为空")
        @Positive(message = "单价必须大于 0")
        private BigDecimal unitPrice;

        /**
         * 宽度(米)
         *
         * <p>非负（issue #4089 · A17 收敛，分歧 D6）：收敛前该边界**只有 ai-agent 工具侧**有
         * （schema {@code minimum: 0} + 本地 {@code _reject_invalid_amount}），服务端裸
         * {@code BigDecimal} 零注解 —— 绕过工具直调即可落负宽度，而负尺寸会进面积/单价数学
         * （{@code per_area} 按宽×高计价）。唯一生产者本就只发非负值，故对合法输入零影响。</p>
         */
        @DecimalMin(value = "0", message = "宽度不能为负数")
        private BigDecimal width;

        /**
         * 高度(米)
         *
         * <p>非负（issue #4089 · A17 收敛，分歧 D6）：与宽度同口径，见上。</p>
         */
        @DecimalMin(value = "0", message = "高度不能为负数")
        private BigDecimal height;

        /**
         * 加工项详情 JSON
         */
        private Object processingInfo;

        /**
         * 小计
         *
         * <p>必填（issue #4089 · A17 收敛）：收敛前 agent 侧 DTO 是平行定义且 {@code subtotal} 可选，
         * 表单侧必填 —— 同一字段两种必填性（分歧 D3）。收敛为单一类型后取**更严**的一份：
         * ai-agent 工具 schema 也把 {@code subtotal} 放在 {@code required} 里（唯一生产者本来就必传），
         * 故对 agent 路径**不产生新增摩擦**，只是让服务端与工具侧同口径。</p>
         */
        @NotNull(message = "小计不能为空")
        @Positive(message = "小计必须大于 0")
        private BigDecimal subtotal;
    }
}
