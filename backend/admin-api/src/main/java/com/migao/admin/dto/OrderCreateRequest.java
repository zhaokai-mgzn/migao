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
import java.time.LocalDate;
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
     * 收货——物流类型（issue #4872）：{@code express} 快递 / {@code logistics} 物流专线
     * （与 {@code order_logistics.logistics_type} V47 / #3984 同词表）。
     *
     * <p><b>未传 ⇒ 服务端不写该列</b>（落列默认 {@code 'express'}）—— **不猜**调用方的意图。
     * 发货页优先读订单这两个字段，缺省回落客户档案
     * （{@code customer_profiles.default_logistics_type} / {@code default_logistics_company}）。</p>
     *
     * <p>⚠️ 单侧字段（wire 契约）：ai-agent 的 {@code order_create} 工具 schema 目前不采集它
     * ⇒ agent 路径不填、走列默认；登记见 {@code OrderDtoContractTest} 的
     * {@code REGISTERED_SINGLE_SIDED_FIELDS}。</p>
     */
    private String logisticsType;

    /**
     * 收货——物流/快递公司（issue #4872）：如「顺丰」「四季安」。
     * <b>未传 ⇒ 不写</b>（列可空），不填默认值、不猜。
     */
    private String logisticsCompany;

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
     * 订单级**加急标记**（V120，issue #5177）。
     *
     * <p>{@code null} / 不传 ⇒ <b>不加急</b>（服务器**不写该列** ⇒ 落列默认 {@code FALSE}）
     * —— **缺省值不变**：不填的行为与今天**逐字相同**（不启用池化、逐单派、错误文案都不动）。</p>
     *
     * <p>🔴 与售后工单的 {@code priority} **不共享来源、不联动、不派生**（用户裁定：
     * 「加急不能跟售后工单绑定，得在订单上直接做」）。它**只影响是否入池/派单时机**，
     * 不参与任何金额计算（对客价格、售价、成品口径逐值不变）。</p>
     *
     * <p>⚠️ <b>单侧字段（wire 契约）</b>：ai-agent 的 {@code order_create} 工具 schema 目前
     * **不采集**它（agent 路径不填、走列默认 ⇒ 与今天逐字相同）；登记见
     * {@code OrderDtoContractTest} 的 {@code REGISTERED_SINGLE_SIDED_FIELDS}。</p>
     */
    private Boolean isUrgent;

    /**
     * **客户要求到货日**（V120，issue #5177；{@code YYYY-MM-DD}）。
     * {@code null} / 不传 ⇒ **未指定**（不猜、不写列）—— NULL 才是「未指定」的真值，
     * 不用今天/承诺交期顶替。消费者 = 智能派单排序（到货日升序、NULL 排最后）。
     *
     * <p>⚠️ <b>单侧字段（wire 契约）</b>：同 {@link #isUrgent}（agent 工具 schema 不采集，
     * 单侧登记见 {@code OrderDtoContractTest}）。</p>
     */
    private LocalDate requiredDeliveryDate;

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
         * 本行售卖方式（**订单级偏好**，V111）：{@code bulk_cut}(散剪) / {@code full_roll}(整卷)。
         *
         * <p>用户裁定 2026-09-21：「在订单中再体现<b>客户要求优先整卷发货</b>」。它是<b>顾客要求</b>，
         * 不是 SKU 维度（SKU 组合只有 颜色 × 门幅）⇒ 与 {@code processingInfo.sellingMethod}
         * 同义，此处是**列**形态。{@code null} = 下单未指定（**不猜**）。</p>
         */
        private String sellingMethod;

        /**
         * 整卷数（V111）：优先整卷发货时发出的整卷数。
         *
         * <p>⚠️ <b>由服务端按该货号的 {@code products.roll_length_m} 计算</b>
         * （{@code ProductRollAllocation}），调用方**传了也会被覆盖** —— 卷长与数量的函数
         * 只有一个权威实现，不允许客户端各算一套（那会让「同一单两个整卷数」）。
         * 货号未配卷长时**不落该值**（NULL，不猜）。</p>
         */
        private Integer rollCount;

        /**
         * 下单时该货号的「1 卷 = 多少米」快照（V111）：同样由服务端按商品当前值写入，
         * 订单是快照不是视图 ⇒ 货号后来改卷长不改变历史单的分配口径。
         */
        private BigDecimal rollLengthM;

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
