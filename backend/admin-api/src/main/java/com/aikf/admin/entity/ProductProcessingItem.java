package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 商品-加工项关联实体
 * 对应表：product_processing_items
 * 用于维护商品与加工项的多对多关系，并支持商品自定义加工价格
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("product_processing_items")
public class ProductProcessingItem {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String productId;

    private String processingItemId;

    private BigDecimal customPrice;

    private Integer sortOrder;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;
}
