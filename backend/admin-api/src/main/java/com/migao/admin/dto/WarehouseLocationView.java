package com.migao.admin.dto;

import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 仓位档案视图（issue #7785）—— 成品仓的可管理货位。
 *
 * <p>{@code occupied} 由 {@code finished_goods_stock} 的**在库行**反推，而不是仓位表上的
 * 标志列：标志列就是第二份真相，发货 / 撤销打包漏改一次就永久占位（与
 * {@code WarehouseLocationService#nextFreeBin} 同一口径）。占用中的仓位不允许改号 / 删除，
 * 前端据此禁用对应动作。</p>
 */
@Data
public class WarehouseLocationView {

    private Long id;

    private Long warehouseId;

    /** 区域编码（成品仓默认 A） */
    private String zoneCode;

    /** 区域名称（展示用） */
    private String zoneName;

    /** 仓位号（如 A-01）：租户内唯一 */
    private String binCode;

    /** active / inactive */
    private String status;

    private String remark;

    /** 是否有在库成品占着它（按 {@code bin_code} 关联 in_stock 行） */
    private Boolean occupied;

    private OffsetDateTime createdAt;
}
