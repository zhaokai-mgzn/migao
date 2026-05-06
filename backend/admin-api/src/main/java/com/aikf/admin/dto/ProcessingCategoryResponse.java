package com.aikf.admin.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 加工分类响应 DTO
 */
@Data
public class ProcessingCategoryResponse {

    /**
     * 分类ID
     */
    private String id;

    /**
     * 分类名称
     */
    private String name;

    /**
     * 排序号
     */
    private Integer sortOrder;

    /**
     * 状态
     */
    private String status;

    /**
     * 分类下的加工项数量
     */
    private Long itemCount;

    /**
     * 创建时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime createdAt;

    /**
     * 更新时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime updatedAt;
}
