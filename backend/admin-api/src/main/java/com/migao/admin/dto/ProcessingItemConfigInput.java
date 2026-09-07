package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;

/**
 * 商品-加工项配置输入 DTO
 * 用于创建/更新商品时提交加工项关联及自定义价格
 */
@Data
public class ProcessingItemConfigInput {

    /**
     * 加工项 ID（processing_items.id）
     */
    private String processingItemId;

    /**
     * 商品自定义价格（可为 null，使用加工项默认单价）
     */
    private BigDecimal customPrice;

    /**
     * 商品级每米数量（密度覆盖）：NULL=用加工项默认密度，非空=商品专属密度
     */
    private BigDecimal customPerMeterQuantity;
}
