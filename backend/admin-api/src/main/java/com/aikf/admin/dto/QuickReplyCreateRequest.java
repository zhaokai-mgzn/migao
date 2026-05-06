package com.aikf.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 创建快捷回复模板请求 DTO
 * 用于人工客服工作台的快捷回复管理
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class QuickReplyCreateRequest {

    @NotBlank(message = "分类不能为空")
    private String category;

    @NotBlank(message = "标题不能为空")
    private String title;

    @NotBlank(message = "内容不能为空")
    private String content;

    private String shortcut;

    @Builder.Default
    private Boolean isPublic = true;
}
