package com.aikf.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 上传文件信息 DTO
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class UploadedFileInfo {

    /**
     * 文件唯一标识（UUID）
     */
    private String id;

    /**
     * 文件访问 URL
     */
    private String url;

    /**
     * 原始文件名
     */
    private String name;

    /**
     * 文件大小（字节）
     */
    private Long size;

    /**
     * 文件 MIME 类型
     */
    private String type;

    /**
     * 创建时间
     */
    private LocalDateTime createdAt;
}
