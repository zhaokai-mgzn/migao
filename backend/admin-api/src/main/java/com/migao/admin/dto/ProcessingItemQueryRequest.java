package com.migao.admin.dto;

import lombok.Data;

/**
 * 加工项查询请求 DTO
 */
@Data
public class ProcessingItemQueryRequest {

    /**
     * 关键词搜索（加工项名称）
     */
    private String keyword;

    /**
     * 加工分类ID
     */
    private String categoryId;

    /**
     * 适用商品分类ID（issue #2964）：按「适用商品分类」过滤加工项——
     * 命中 applicable_product_categories 包含该分类，或 applicable_product_categories 为空（=适用所有分类）
     */
    private String applicableProductCategoryId;

    /**
     * 状态：active（启用）、inactive（禁用）
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
}
