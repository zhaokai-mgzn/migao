package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 出库单视图（V196，issue #7750）—— 列表与详情**同一形状**（{@link #items} 列表时为 null）。
 *
 * <p>与入库单的读面同款：列表带聚合（行数 / 总数量），详情带逐行明细。字段名与
 * {@code OutboundOrderQueryMapper} 的 SELECT 别名一一对应（MyBatis 按别名映射）。</p>
 */
@Data
public class OutboundOrderView {

    private String id;

    /** 出库单号 CK-yyyyMMdd-NNNN（租户内唯一） */
    private String outboundNo;

    /** fabric 布料 / finished 成品 */
    private String bizCategory;

    /** manual 手工出库 / ship 发货出库 */
    private String source;

    private Long warehouseId;

    private String warehouse;

    private LocalDate outboundDate;

    /** 恒为 posted（出库单没有草稿态，见 V196 头注） */
    private String status;

    private BigDecimal totalAmount;

    /** 成品出库：来源订单（布料手工单为空） */
    private String orderId;

    private String orderNo;

    private String remark;

    private OffsetDateTime postedAt;

    private String postedBy;

    private OffsetDateTime createdAt;

    /** 明细行数（列表聚合） */
    private Integer itemCount;

    /** 明细总数量（列表聚合） */
    private BigDecimal totalQuantity;

    /** 明细（详情才有） */
    private List<Item> items;

    @Data
    public static class Item {

        private Long id;

        /** 布料行：SKU；成品行为空 */
        private Long skuId;

        private String skuCode;

        private String productName;

        /** 成品行：来源订单行 + 出库仓位 */
        private String orderItemId;

        private Long locationId;

        private String binCode;

        private BigDecimal quantity;

        /** m = 米 / set = 套 */
        private String unit;

        private BigDecimal unitCost;

        private BigDecimal amount;

        private String remark;
    }
}
