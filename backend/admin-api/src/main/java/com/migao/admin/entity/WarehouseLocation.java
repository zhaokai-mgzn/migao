package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 仓位（V196，issue #7750）—— 成品仓里的货位：区域 + 仓位号。
 *
 * <p>为什么值得一张表：改前「仓位」只是 {@code inbound_orders.warehouse} 里的一个自由文本，
 * 写错一个字就是「另一个位置」；而「这件成品在哪」是仓管与发货都要回答的问题
 * （用户 2026-10-25 逐字：「自动给当前的成品进行成品仓区域分配仓位号」）。</p>
 *
 * <p>唯一性口径 = {@code (tenant_id, bin_code)}（租户内唯一，不是仓内唯一）：
 * 仓位号的用途是扫码 / 口头指位，跨仓同号会让这句话有歧义。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("warehouse_locations")
public class WarehouseLocation {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long warehouseId;

    /** 区域编码（成品仓默认 A 区；新增号段只在本区域内顺延） */
    private String zoneCode;

    /** 区域名称（展示用） */
    private String zoneName;

    /** 仓位号（如 A-01）：同租户唯一 —— 扫码与口头指位都认它 */
    private String binCode;

    /** active / inactive */
    private String status;

    private String remark;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
