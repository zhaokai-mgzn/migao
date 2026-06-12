package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 商品颜色响应 DTO
 */
@Data
public class ProductColorResponse {

    private Long id;

    private String productId;

    private String colorName;

    private String mainColorHex;

    private String colorImageUrl;

    private String remark;

    private Integer sortOrder;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime createdAt;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime updatedAt;
}
