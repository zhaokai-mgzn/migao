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
 * 「待付款订单内容编辑」请求 DTO（issue #5842；用户 2026-10-01 裁定「范围 = 全改」）。
 *
 * <h3>它是什么 / 不是什么</h3>
 * <p>它是**订单内容编辑**的专用请求体（收货信息 + 商品明细 + 加工项），对应
 * {@code PUT /api/admin/orders/{id}/content}。它<b>不是</b> {@link OrderCreateRequest} 的复用，
 * 也不是它的子类 —— 两者**语义不同**：</p>
 * <ul>
 *   <li><b>建单</b>：无订单可改，请求即全部真值（含 {@code userId} / 加急 / 到货日 / 物流偏好
 *       等**建单期**字段）；</li>
 *   <li><b>改单</b>：订单已在库，只能改<b>内容</b>三面（收货 / 明细 / 加工项）。
 *       建单期字段（{@code userId} 归属、加急、到货日、物流偏好）各有专用通道
 *       （{@code /urgency} 等）⇒ **本 DTO 一律不带**，免得两条路各写一份同一列。</li>
 * </ul>
 *
 * <h3>为什么没有 {@code subtotal}（issue 口径：金额一律服务端重算）</h3>
 * <p>建单 DTO 里 {@code items[].subtotal} 是客户端必填字段，而服务端
 * （{@code OrderService.createOrder}）**本来就独立算一遍** {@code unitPrice × quantity}，
 * 并在明细落 {@code resolveItemSubtotal}。改单这里<b>索性不给这个字段</b>：
 * 客户端无从提交一个「小计」，服务端也就无从信它 —— 比「收了再忽略」更不容易被后人误用。
 * 客户端的任何金额（含 {@code subtotal} / {@code totalAmount}）**不参与**落库与校验。</p>
 *
 * <h3>加工项（{@code items[].processingInfo}）与建单同源</h3>
 * <p>形态与建单**逐字同形**（顶层工艺规格键 + {@code processingItems[]} + {@code specialOptions[]}
 * + {@code craftLineId} 樘窗组键），由服务端同一段代码归一化
 * （{@code OrderLineCraftFields.normalize}）并走**同一份**加工费取价
 * （{@code ProcessingFeeCalculator.feesFor}）—— 改单不另造一套加工项语义。</p>
 *
 * <h3>金额字段的「未传」口径（不猜、不清零）</h3>
 * <p>{@code discountAmount} / {@code actualAmount} 未传 ⇒ **沿用订单原值**（不是 0、不是重算值），
 * 随后照常做建单那一条一致性校验「应收 − 优惠 ≈ 实收（容差 0.01）」。改明细会改变应收 ⇒
 * 商家需显式给出新的实收（商家端表单默认带出原值，正常路径不会踩到）。</p>
 */
@Data
public class OrderContentUpdateRequest {

    /** 收货人姓名 */
    @NotBlank(message = "客户姓名不能为空")
    private String customerName;

    /** 联系电话（与建单同一条格式约束：售后联系、客户绑定、物流尾号都读它） */
    @NotBlank(message = "客户电话不能为空")
    @Pattern(regexp = "^1[3-9]\\d{9}$", message = "手机号格式不正确，请输入11位中国大陆手机号")
    private String customerPhone;

    /** 收货地址 */
    private String customerAddress;

    /** 优惠金额；未传 ⇒ 沿用订单原值（见类注释） */
    private BigDecimal discountAmount;

    /** 实收款；未传 ⇒ 沿用订单原值（见类注释） */
    private BigDecimal actualAmount;

    /** 订单明细（**整体替换**语义：提交什么就是改后的全部明细） */
    @NotEmpty(message = "订单明细不能为空")
    @Valid
    private List<Item> items;

    /**
     * 明细行请求（字段集 = 建单行里**可编辑**的那些；{@code subtotal} 刻意缺席，见类注释）。
     */
    @Data
    public static class Item {

        /** 商品ID（可空 = 未挂货号；库存校验据此匹配 SKU） */
        private String productId;

        /** 商品名称 */
        @NotBlank(message = "商品名称不能为空")
        private String productName;

        /**
         * 数量：与建单同口径（下限 1；{@code per_area} 的合法数量是小数，如 2.8m × 3m = 8.4 ㎡）。
         * 它直接驱动库存前置校验 ⇒ 服务端还会**再判一次**（程序化构造的 Bean 不过 Bean Validation）。
         */
        @NotNull(message = "数量不能为空")
        @DecimalMin(value = "1", message = "数量不能小于 1")
        private BigDecimal quantity;

        /** 单价（必须 > 0；服务端同样再判一次） */
        @NotNull(message = "单价不能为空")
        @Positive(message = "单价必须大于 0")
        private BigDecimal unitPrice;

        /** 宽度(米)，非负（负尺寸会进 per_area 面积计价） */
        @DecimalMin(value = "0", message = "宽度不能为负数")
        private BigDecimal width;

        /** 高度(米)，非负 */
        @DecimalMin(value = "0", message = "高度不能为负数")
        private BigDecimal height;

        /** 加工项详情（与建单**逐字同形**，见类注释） */
        private Object processingInfo;

        /** 本行售卖方式偏好（{@code bulk_cut} / {@code full_roll}；{@code null} = 未指定，不猜） */
        private String sellingMethod;
    }
}
