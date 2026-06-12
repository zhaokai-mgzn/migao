package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 更新快捷回复模板请求 DTO
 * 所有字段均为可选，仅更新传入的字段
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class QuickReplyUpdateRequest {

    private String category;

    private String title;

    private String content;

    private String shortcut;

    private Boolean isPublic;
}
