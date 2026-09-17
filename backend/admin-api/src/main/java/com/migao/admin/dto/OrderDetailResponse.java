package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 订单详情响应 DTO
 *
 * <p>{@code @JsonIgnoreProperties(ignoreUnknown = true)}（issue #4037）：幂等回放时服务端
 * 会在快照 JSON 里带上 {@code replayed: true} 标记（见 {@code ClientRequestIdService.replay}），
 * 这里**显式**声明"多出来的键不影响反序列化"，不依赖 Spring Boot 默认值 ——
 * 免得哪天默认被收紧后回放路径**静默变 500**。</p>
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class OrderDetailResponse {

    /**
     * 幂等回放标记（issue #4037）：{@code true} = 本次响应来自「同键回放」，
     * 服务端**没有**新建记录；首次执行时不出现该键（{@code NON_NULL}）。
     *
     * <p>为什么必须是**真字段**而不是"在快照 JSON 里塞一个键"：Jackson 反序列化时
     * 未声明的键会被丢弃（本类还显式声明了 {@code ignoreUnknown=true}）⇒ 标记会被**静默丢掉**，
     * 响应里永远不会出现它，而调用方（ai-agent）就分不出「首次执行」与「同键回放」，
     * 会把一次重试播报成两笔订单（观察性缺陷）。</p>
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private Boolean replayed;

    /**
     * 订单ID
     */
    private String id;

    /**
     * 订单号
     */
    private String orderNo;

    /**
     * 客户姓名
     */
    private String customerName;

    /**
     * 客户电话
     */
    private String customerPhone;

    /**
     * 客户地址
     */
    private String customerAddress;

    /**
     * 总金额（商品小计 + 加工费）
     */
    private BigDecimal totalAmount;

    /**
     * 实收款（当前 = totalAmount，后续支持优惠时可调整）
     */
    private BigDecimal actualAmount;

    /**
     * 优惠金额（应收 totalAmount 与实收 actualAmount 的差额）
     */
    private BigDecimal discountAmount;

    /**
     * 累计已退款金额（>0 表示"已退款"）
     */
    private BigDecimal refundAmount;

    /**
     * 最近一次退款时间
     */
    private OffsetDateTime refundAt;

    /**
     * 加工费合计（所有订单明细加工项金额之和）
     */
    private BigDecimal processingFee;

    /**
     * 订单状态
     */
    private String status;

    /**
     * 备注
     */
    private String remark;

    /**
     * 关闭/取消原因
     */
    private String closeReason;

    /**
     * 订单明细列表
     */
    private List<OrderItemResponse> items;

    /**
     * 加工项列表（聚合所有订单明细的加工项，便于前端单独展示）
     */
    private List<ProcessingItemBrief> processingItems;

    /**
     * 物流信息
     */
    private LogisticsInfo logistics;

    /**
     * 创建时间
     */
    private OffsetDateTime createdAt;

    /**
     * 更新时间
     */
    private OffsetDateTime updatedAt;


    /**
     * 订单明细响应 DTO
     */
    @Data
    public static class OrderItemResponse {

        /**
         * 明细ID
         */
        private String id;

        /**
         * 商品ID
         */
        private String productId;

        /**
         * 商品名称
         */
        private String productName;

        /**
         * 商品货号（SKU 编号，用于采购商品列展示）
         */
        private String skuCode;

        /**
         * 数量（口径按计价方式：per_meter=米数 / per_set=1 / per_area=宽×高㎡，可为小数）
         */
        private BigDecimal quantity;

        /**
         * 单价
         */
        private BigDecimal unitPrice;

        /**
         * 宽度(米)
         */
        private BigDecimal width;

        /**
         * 高度(米)
         */
        private BigDecimal height;

        /**
         * 加工项详情
         */
        private Object processingInfo;

        /**
         * 小计
         */
        private BigDecimal subtotal;

        /**
         * 金额 = unitPrice * quantity（前端展示用，后端从 unitPrice 与 quantity 计算）
         */
        private BigDecimal amount;

        /**
         * 创建时间
         */
        private OffsetDateTime createdAt;
    }

    /**
     * 加工项简要响应 DTO
     */
    @Data
    public static class ProcessingItemBrief {

        /**
         * 加工项ID
         */
        private String id;

        /**
         * 加工项名称
         */
        private String name;

        /**
         * 单价
         */
        private BigDecimal unitPrice;

        /**
         * 数量（口径按计价方式：per_meter=米数 / per_set=1 / per_area=宽×高㎡，可为小数）
         */
        private BigDecimal quantity;

        /**
         * 金额 = unitPrice * quantity
         */
        private BigDecimal amount;
    }

    /**
     * 物流信息响应 DTO
     */
    @Data
    public static class LogisticsInfo {

        private String id;

        private String logisticsCompany;

        private String trackingNo;

        /** 物流类型：express 快递 / logistics 物流专线（四季安等，issue #3984，V47） */
        private String logisticsType;

        /**
         * 发货人姓名（发货单纸面「经手人」，issue #3768）。
         * ⚠️ 仅供 B 端发货单/订单详情展示；**不得**透传给 C 端顾客——
         * C 端物流链路（customer_logistics_track）按白名单字段构造返回，不读取本字段。
         */
        private String shipperName;

        private String status;

        private Object trackingInfo;

        private OffsetDateTime shippedAt;

        private OffsetDateTime deliveredAt;
    }
}
