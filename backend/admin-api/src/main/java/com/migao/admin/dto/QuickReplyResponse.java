package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 快捷回复模板响应 DTO
 * 用于人工客服工作台的快捷回复管理
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class QuickReplyResponse {

    private String id;

    private String category;

    private String title;

    private String content;

    private String shortcut;

    private Integer usageCount;

    private Boolean isPublic;

    private String createdBy;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;
}
