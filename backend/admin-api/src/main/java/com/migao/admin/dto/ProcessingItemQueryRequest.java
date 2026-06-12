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
     * 分类ID
     */
    private String categoryId;

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
