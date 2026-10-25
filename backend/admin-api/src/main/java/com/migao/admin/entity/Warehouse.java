package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 仓库（V182，issue #7373 P1-1 段 1）—— 从「文本字段」升级为**实体**：有编码、有类型、有默认仓。
 *
 * <p>为什么值得一张表：改前 `warehouse` 只是文本，写错一个字就是「另一个仓」，对账时两边都对不上，
 * 而且没有「默认仓」概念 —— 新入库的行不知道该落哪。</p>
 */
@Data
@TableName("warehouses")
public class Warehouse {

    /** 门店仓（默认类型）。 */
    public static final String TYPE_STORE = "store";
    /** 加工仓。 */
    public static final String TYPE_PROCESSING = "processing";
    /** 原料仓（V196 / issue #7750）：装布料等原材料 —— 存量默认仓由 V196 回填成它。 */
    public static final String TYPE_MATERIAL = "material";
    /** 成品仓（V196 / issue #7750）：装打包后的成品帘；成品仓位（{@code warehouse_locations}）挂在它下面。 */
    public static final String TYPE_FINISHED = "finished";

    /** 全部合法类型（与表 CHECK 逐字一致；服务层校验用它，不各写一份）。 */
    public static final java.util.List<String> TYPES =
            java.util.List.of(TYPE_STORE, TYPE_PROCESSING, TYPE_MATERIAL, TYPE_FINISHED);

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 仓编码（同租户唯一；单据与对账都认它）。 */
    private String code;

    private String name;

    /** {@link #TYPE_STORE} / {@link #TYPE_PROCESSING} / {@link #TYPE_MATERIAL} / {@link #TYPE_FINISHED}。 */
    private String warehouseType;

    /** 默认仓：同租户**只能有一个**（部分唯一索引兜住，不靠服务层自觉）。 */
    private Boolean isDefault;

    private String status;

    private String remark;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
