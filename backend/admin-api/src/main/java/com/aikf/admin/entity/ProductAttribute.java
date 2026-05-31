package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 商品属性实体类
 * 对应表：product_attributes
 * 用于以 attr_key/attr_value 形式存储 brand/material/weight/function/style/craft/pattern 等属性
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("product_attributes")
public class ProductAttribute {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String productId;

    /**
     * 属性键，如 brand/material/weight/function/style/craft/pattern
     */
    private String attrKey;

    /**
     * 属性值
     */
    private String attrValue;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;
}
