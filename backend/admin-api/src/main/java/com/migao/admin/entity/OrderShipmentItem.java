package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 发货明细（issue #5648）—— 对应表 {@code order_shipment_items}。
 *
 * <p>🔴 <b>这是「这一单实际发了多少」的<b>唯一真值载体</b></b>（实发套 / 件 / 卷）。
 * 与 {@link OrderItem#getQuantity()}（**下单**数量）是两件事：
 * 「下单 12 米」与「实发 10 米」的差额就是少发 —— 此前没有任何落点能算出它。</p>
 *
 * <p><b>owner 声明（与 #5651 的边界）</b>：本表拥有该真值，issue #5651（A4 加工单 / 销售单
 * 三联纸）只**消费**（读 {@code OrderShipmentService.readShipment}），不得另建第二份投影。</p>
 *
 * <p>三处「缺值不填 0」：{@code setCount} / {@code rollCount} / 单价类派生量 ——
 * 0 与 null 是两个意思（「一件都没发」vs「这一维不适用」），把 null 写成 0 就是编造。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "order_shipment_items", autoResultMap = true)
public class OrderShipmentItem {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String shipmentId;

    private String orderId;

    /** 订单行 id：发货明细挂在**订单行**上（不是商品上）—— 同一商品两行（不同尺寸）必须分得开 */
    private String orderItemId;

    /** 商品名快照（订单行改名/删除后纸面仍可复原） */
    private String productName;

    /** 🔴 实发数量（米 / 套 / 件，与 {@code order_items.quantity} 同口径）—— **不是**下单数量 */
    private BigDecimal shippedQuantity;

    /** 计量单位：米 / 套 / 件（与订单行计价方式同口径，不从订单行推算） */
    private String unit;

    /** 实发套数；仅按套发货时有值，其余为 NULL（缺值不填 0） */
    private Integer setCount;

    /** 实发卷数；仅整卷发货时有值，其余为 NULL（禁止由米数推算卷数） */
    private Integer rollCount;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
