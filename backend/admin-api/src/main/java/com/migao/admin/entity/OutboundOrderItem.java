package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 出库单明细（V196，issue #7750）。
 *
 * <p>两种行共用一个形状：布料行 = SKU + 米数（{@link #skuId} / {@link #quantity}），
 * 成品行 = 订单行 + 仓位 + 套数（{@link #orderItemId} / {@link #binCode}）。
 * 不拆两张明细表：明细的读面/展示/导出只有一套（与 V194「统一单据」口径同源）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("outbound_order_items")
public class OutboundOrderItem {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String outboundOrderId;

    /** 布料行：SKU 主键（无 FK：SKU 会被硬删重建，同入库单明细） */
    private Long skuId;

    private String productId;

    /** 货号快照（布料行） */
    private String skuCode;

    /** 品名快照（成品行必有；布料行可空） */
    private String productName;

    /** 成品行：来源订单 */
    private String orderId;

    /** 成品行：来源订单明细（一个成品订单行 = 一个仓位） */
    private String orderItemId;

    /** 成品行：出库的仓位引用 */
    private Long locationId;

    /** 仓位号快照 */
    private String binCode;

    /** 出库数量（布料 = 米；成品 = 套） */
    private BigDecimal quantity;

    /** m = 米 / set = 套 */
    private String unit;

    /** 出库单价（布料 = 出库时的移动加权均价；成品无成本 ⇒ NULL，不伪造 0） */
    private BigDecimal unitCost;

    /** 行金额 = quantity × unitCost；成本未知 ⇒ NULL */
    private BigDecimal amount;

    private String remark;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
