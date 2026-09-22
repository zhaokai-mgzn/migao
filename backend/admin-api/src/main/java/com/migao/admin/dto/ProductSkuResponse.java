package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 商品SKU响应 DTO
 */
@Data
public class ProductSkuResponse {

    /**
     * SKU 主键（BIGSERIAL）。值可能超过 JS 安全整数 2^53，序列化为字符串
     * 防止前端精度丢失导致订单扣库存链路失败（见 LongIdSerializationTest）。
     */
    @JsonSerialize(using = ToStringSerializer.class)
    private Long id;

    private String productId;

    /**
     * 颜色主键（BIGSERIAL），同样可能超过 2^53，序列化为字符串。
     */
    @JsonSerialize(using = ToStringSerializer.class)
    private Long colorId;

    private String colorName;

    /**
     * 规格尺寸
     *
     * <p>⚠️ 本 DTO **不再有** {@code sellingMethod} —— 用户裁定 2026-09-21：
     * SKU 组合只有 颜色 × 门幅，售卖方式已上移为商品级
     * {@code ProductResponse.sellingMethods}（V111 迁移删列）。</p>
     */
    private String doorWidth;

    /**
     * 价格
     */
    private BigDecimal price;

    /**
     * 库存
     */
    private BigDecimal stock;

    /**
     * SKU编码
     */
    private String skuCode;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime createdAt;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime updatedAt;
}
