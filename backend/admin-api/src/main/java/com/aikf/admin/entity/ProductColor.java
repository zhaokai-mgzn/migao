package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 商品颜色实体类
 * 对应表：product_colors
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("product_colors")
public class ProductColor {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String productId;

    /**
     * 主色名称（如"红色"、"米白"）
     */
    private String colorName;

    /**
     * 色值 #FFFFFF
     */
    private String mainColorHex;

    /**
     * 颜色图片URL
     */
    private String colorImageUrl;

    /**
     * 备注
     */
    private String remark;

    /**
     * 排序
     */
    private Integer sortOrder;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
