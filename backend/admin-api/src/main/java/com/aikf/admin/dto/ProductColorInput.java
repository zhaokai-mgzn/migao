package com.aikf.admin.dto;

import lombok.Data;

/**
 * 商品颜色输入 DTO（创建/更新商品时使用）
 *
 * 前端为新增颜色生成的临时 id 可能为负数；后端忽略 id 字段，
 * 由数据库自动生成；id 仅用于前端在 SKU 列表中关联 colorId。
 */
@Data
public class ProductColorInput {

    /**
     * 前端临时颜色ID（负数表示新增），后端用于建立 SKU.colorId 映射
     */
    private Long id;

    /**
     * 颜色名称
     */
    private String colorName;

    /**
     * 主色HEX
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
}
