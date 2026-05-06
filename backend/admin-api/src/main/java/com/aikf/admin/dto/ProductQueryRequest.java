package com.aikf.admin.dto;

import lombok.Data;

/**
 * 商品查询请求 DTO
 */
@Data
public class ProductQueryRequest {

    /**
     * 关键词搜索（商品名称）
     */
    private String keyword;

    /**
     * 分类ID
     */
    private String categoryId;

    /**
     * 状态：on_sale（上架）、off_sale（下架）
     */
    private String status;

    /**
     * 页码，默认 1
     */
    private Long page = 1L;

    /**
     * 每页大小，默认 20
     */
    private Long size = 20L;

    /**
     * 低库存筛选：库存低于该值的商品
     */
    private Integer stockBelow;
}
