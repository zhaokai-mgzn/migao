package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
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
 * 成品在库（V196，issue #7750；V197 / #7762 拆到套×部位；V198 / #7791 一仓可多件）——
 * 一行 = 一件打包后的成品（含仓位号）。
 *
 * <h3>粒度</h3>
 * <p>V197 起按「套 × 部位」逐行在库（一张水洗唛 = 一行），V198 起一个仓位可放多件到区域容量
 * （默认 10 件）；同套装/部位仍只允许一行在库（{@code uk_finished_goods_set_part_in_stock}）。</p>
 *
 * <h3>三态（DB CHECK 兜住）</h3>
 * <ul>
 *   <li>{@link #STATUS_IN_STOCK} —— 在库：可以多件同仓（到 {@code warehouse_locations.capacity}）；
 *       容量由分配事务的行锁 + 件数复核闸住，不再有 bin 唯一索引；</li>
 *   <li>{@link #STATUS_SHIPPED} —— 已发货出库（由成品出库单写入）；</li>
 *   <li>{@link #STATUS_UNPACKED} —— 撤销打包（入库单作废，仓位释放）。</li>
 * </ul>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("finished_goods_stock")
public class FinishedGoodsStock {

    /** 在库（占用仓位） */
    public static final String STATUS_IN_STOCK = "in_stock";
    /** 已发货出库（仓位释放） */
    public static final String STATUS_SHIPPED = "shipped";
    /** 撤销打包（仓位释放，入库单作废） */
    public static final String STATUS_UNPACKED = "unpacked";

    /** 单位 · 套（成品帘的计量单位） */
    public static final String UNIT_SET = "set";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long warehouseId;

    private Long locationId;

    /** 仓位号快照（分配那一刻写死） */
    private String binCode;

    private String orderId;

    private String orderNo;

    /** 成品订单行（V197 起：一个订单行 × 套 × 部位 = 一个在库行） */
    private String orderItemId;

    /** 所属套（{@code processing_order_sets.id}）；{@code NULL} = V196 遗留的订单行粒度行 */
    private String setId;

    /** 套号快照 */
    private String setNo;

    /** 第几套（1 起；标签「第 N 套 / 共 M 套」用） */
    private Integer setIndex;

    /** 部位码行（{@code processing_set_part_tokens.id}）—— 一张水洗唛 = 一个仓位 */
    private String partTokenId;

    /** 水洗唛短码快照（印在纸上的可抄入口） */
    private String shortCode;

    private String productId;

    private String productName;

    private BigDecimal quantity;

    /** {@link #UNIT_SET} */
    private String unit;

    /** {@link #STATUS_IN_STOCK} / {@link #STATUS_SHIPPED} / {@link #STATUS_UNPACKED} */
    private String status;

    /** 进货的成品入库单（打包时自动建） */
    private String inboundOrderId;

    /**
     * 入库单号（只读投影：join {@code inbound_orders} 得来；本列不在 {@code finished_goods_stock} 表里）。
     *
     * <p>{@link #inboundOrderId} 存的是单据 **id**（{@code InboundOrder.id} 是 ASSIGN_UUID ⇒ 32 位 UUID），
     * 商家要看的单号（{@code RK-…}）在 {@code inbound_orders.inbound_no}（issue #7792）。</p>
     */
    @TableField(exist = false)
    private String inboundNo;

    /** 出货的成品出库单（发货时自动建） */
    private String outboundOrderId;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
