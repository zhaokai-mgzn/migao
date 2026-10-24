package com.migao.admin.service;

import java.math.BigDecimal;

/**
 * 下单定价的**判据与留痕标签**（issue #7375，P1-3 段 2）。
 *
 * <h3>只在「价格本命中」时覆盖客户端价（刻意收窄）</h3>
 * <p>解析结果若是 {@link PriceResolution.Source#STANDARD} 或 {@code UNPRICED}，说明**没有价格本依据**：
 * 客户端那个数就是表单上业务员看到并确认的价格。覆盖它等于凭空改单，且会让存量订单一夜之间全部变价。
 * 覆盖只发生在<b>协议价 / 等级价 / 阶梯价</b>命中时 —— 那正是「承诺过的价」。</p>
 */
public final class OrderPriceOverride {

    /** 未参与服务端解析的行（没有 SKU / SKU 定位不到）| 标签写进 `order_items.price_source`。 */
    public static final String CLIENT_SOURCE = "client";

    private OrderPriceOverride() {
    }

    /** 该层级是否应当覆盖客户端价。 */
    public static boolean shouldOverride(PriceResolution.Source source) {
        return source == PriceResolution.Source.PROTOCOL
                || source == PriceResolution.Source.VIP_LEVEL
                || source == PriceResolution.Source.TIER;
    }

    /** 落库用的来源标签（机器可读，不写中文）。 */
    public static String sourceLabel(PriceResolution.Source source) {
        return switch (source) {
            case PROTOCOL -> "price_book_protocol";
            case VIP_LEVEL -> "price_book_vip_level";
            case TIER -> "price_book_tier";
            case STANDARD -> "sku_standard_price";
            case UNPRICED -> "no_price_book";
        };
    }

    /**
     * 留痕金额：**只在真被改写时**记录客户端原价（未被改写 ⇒ null，避免把「一样的价」写成「改过」）。
     */
    public static BigDecimal clientPriceWhenOverridden(BigDecimal clientPrice,
                                                      BigDecimal serverPrice,
                                                      boolean overridden) {
        if (!overridden) {
            return null;
        }
        return clientPrice;
    }
}
