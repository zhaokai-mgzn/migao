package com.migao.admin.dto;

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
     * 商品标题搜索
     */
    private String name;

    /**
     * 商品ID搜索
     */
    private String productId;

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

    /**
     * 货号搜索
     */
    private String skuCode;

    /**
     * 创建时间起始（格式：yyyy-MM-dd）
     */
    private String createdFrom;

    /**
     * 创建时间截止（格式：yyyy-MM-dd）
     */
    private String createdTo;

    /**
     * 开始日期（兼容别名）
     */
    private String startDate;

    /**
     * 结束日期（兼容别名）
     */
    private String endDate;

    /**
     * 排序字段: stock/salesCount/salesAmount/createdAt
     */
    private String sortBy;

    /**
     * 排序方向: asc/desc
     */
    private String sortOrder;
}
