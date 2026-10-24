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

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 仓编码（同租户唯一；单据与对账都认它）。 */
    private String code;

    private String name;

    /** {@link #TYPE_STORE} / {@link #TYPE_PROCESSING}。 */
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
