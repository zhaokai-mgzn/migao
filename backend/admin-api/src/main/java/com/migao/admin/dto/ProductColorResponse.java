package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 商品颜色响应 DTO
 */
@Data
public class ProductColorResponse {

    /**
     * 颜色主键（BIGSERIAL）。值可能超过 JS 安全整数 2^53，序列化为字符串
     * 防止前端精度丢失（见 LongIdSerializationTest）。
     */
    @JsonSerialize(using = ToStringSerializer.class)
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
