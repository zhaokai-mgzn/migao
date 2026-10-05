package com.migao.admin.dto;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.math.BigDecimal;

/**
 * 「识别结果命中的既有 SKU」一行（issue #5052 P1，设计 §6.3 的 SKU 匹配门禁）。
 *
 * <p>🔴 本类的每一条都**来自 {@code product_skus} 的实读**（{@code product_skus} 是库存唯一真值，
 * issue #4038）—— 服务端**不构造**任何 SKU。零命中 ⇒ 列表为空数组，
 * 页面提示「没找到这个品名 + 色号，请人工从已有商品里选」（拒绝入库、**不自动建品**）。</p>
 *
 * <p>为什么把 {@code stock} 一起带出来：工人要在收货台上当场判断「是不是这一卷」，
 * 而库存读数与商品详情页**同源**（都是 {@code product_skus.stock}，不另算一份）。</p>
 */
@Data
public class WorkerInboundSkuMatch {

    /**
     * SKU ID（库存权威粒度）。
     *
     * <p>🔴 雪花号（≈2.1e18）**超过 JS 安全整数 2^53**，序列化为字符串防止前端精度丢失
     * （本字段是 issue #6340 的主犯：工人端 recognize 出参按 JSON number 发出 ⇒ 页面
     * {@code JSON.parse} 当场吞掉末两位 ⇒ 回传时服务端查不到该 SKU）。见 {@code LongIdSerializationTest}。</p>
     */
    @JsonSerialize(using = ToStringSerializer.class)
    private Long skuId;

    /** 商品 ID */
    private String productId;

    /** 商品名（取自 {@code products.name}，用于人工核对） */
    private String productName;

    /** 货号（{@code product_skus.sku_code}） */
    private String skuCode;

    /** 色号 + 颜色名（{@code product_skus.color_name}） */
    private String colorName;

    /** 门幅（{@code product_skus.door_width}） */
    private String doorWidth;

    /** 当前库存（米）：{@code product_skus.stock} 的实读值，原样透传 */
    private BigDecimal stock;
}
