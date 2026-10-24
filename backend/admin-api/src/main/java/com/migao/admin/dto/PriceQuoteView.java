package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;

/**
 * 报价读面（issue #7375，P1-3 段 1）。
 *
 * <p>🔴 未定价时 `price` / `amount` 都是 **null**、`source = "unpriced"` ——
 * **不许**给 0（0 元 = 白送；SKU 的 `price` 列 DEFAULT 0 不是价格）。</p>
 *
 * <p>`source` = 命中层级（`protocol` / `vip_level` / `tier` / `standard` / `unpriced`）：
 * 改价争议时它就是第一份证据 —— 「凭什么收这个价」。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class PriceQuoteView {

    private String customerId;

    private Long skuId;

    private BigDecimal quantity;

    /** 命中层级（机器可读；`unpriced` = 四层都没有价） */
    private String source;

    /** 单价；未定价时为 null */
    private BigDecimal price;

    /** 金额 = 单价 × 数量；单价 null 或数量 null 时为 null（不是 0） */
    private BigDecimal amount;

    /** 命中阶梯时的门槛数量（其它层级为 null），用于展示「满 X 享此价」 */
    private BigDecimal tierMinQty;
}
