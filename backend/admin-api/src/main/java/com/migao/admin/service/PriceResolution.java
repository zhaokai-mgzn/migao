package com.migao.admin.service;

import java.math.BigDecimal;
import java.util.List;

/**
 * 价格解析（issue #7375，P1-3 段 1）—— **纯函数**：给定四层价格本，说出「这个客户买这个 SKU，
 * 数量这么多，该按哪个价、凭哪一条」。
 *
 * <h3>为什么必须在服务端算</h3>
 * <p>改前下单价格**只来自前端传值**：同一件货三个客户等级拿同一个价，「给老客户便宜 5%」靠业务员手改数字，
 * 改错了没人留痕。价格是毛利的第一变量（P0-3 的毛利就建在售价上），所以判定必须落在服务端，且**留痕**。</p>
 *
 * <h3>优先级（唯一顺序，别的地方不许再写一套）</h3>
 * <ol>
 *   <li><b>协议价</b>（客户 × SKU）：最具体的商业承诺，最高优先；</li>
 *   <li><b>等级价</b>（VIP 等级 × SKU）；</li>
 *   <li><b>阶梯价</b>（SKU + 数量区间，闭区间命中）；</li>
 *   <li><b>SKU 标准价</b>（`product_skus.price`）。</li>
 * </ol>
 *
 * <h3>未定价 ≠ ¥0.00</h3>
 * <p>四层都没有 ⇒ {@link Source#UNPRICED} 且 `price = null`。**绝不用 0 代替** ——
 * SKU 的 `price` 列有 `DEFAULT 0`，把 0 当价格等于白送；判据见 {@code PriceResolutionTest#unpricedIsNeverZero}。</p>
 */
public final class PriceResolution {

    /** 价格来源：上屏要能自述「凭哪一条算的」（改价争议的第一份证据）。 */
    public enum Source {
        PROTOCOL, VIP_LEVEL, TIER, STANDARD, UNPRICED
    }

    /**
     * @param price      解析出的单价（`UNPRICED` 时为 null）
     * @param source     命中层级
     * @param tierMinQty 命中阶梯时的下限（其它层级为 null，便于前端展示「满 X 享此价」）
     */
    public record Result(BigDecimal price, Source source, BigDecimal tierMinQty) {

        public boolean priced() {
            return source != Source.UNPRICED && price != null;
        }
    }

    /** 阶梯区间（闭区间；`maxQty == null` = 无上限）。 */
    public record Tier(BigDecimal minQty, BigDecimal maxQty, BigDecimal price) {
    }

    private PriceResolution() {
    }

    /**
     * 解析单价。
     *
     * @param protocolPrice 协议价（null = 没有协议价）
     * @param vipLevelPrice 等级价（null = 该等级没有专属价）
     * @param tiers         该 SKU 的阶梯价表（可空/乱序，内部按区间命中，不假设顺序）
     * @param standardPrice SKU 标准价（null 或 &lt;= 0 都算「没有标准价」——`DEFAULT 0` 不是价格）
     * @param quantity      购买数量（null ⇒ 阶梯价不参与，因为区间无法判定）
     */
    public static Result resolve(BigDecimal protocolPrice,
                                 BigDecimal vipLevelPrice,
                                 List<Tier> tiers,
                                 BigDecimal standardPrice,
                                 BigDecimal quantity) {
        if (positive(protocolPrice)) {
            return new Result(scale(protocolPrice), Source.PROTOCOL, null);
        }
        if (positive(vipLevelPrice)) {
            return new Result(scale(vipLevelPrice), Source.VIP_LEVEL, null);
        }
        Tier hit = matchTier(tiers, quantity);
        if (hit != null) {
            return new Result(scale(hit.price()), Source.TIER, hit.minQty());
        }
        if (positive(standardPrice)) {
            return new Result(scale(standardPrice), Source.STANDARD, null);
        }
        // 四层皆无 ⇒ 未定价（**不是 0**）
        return new Result(null, Source.UNPRICED, null);
    }

    /** 命中区间：按 `minQty` **降序**取第一个包含数量的档（多档重叠时给「门槛更高、价更低」的那档）。 */
    private static Tier matchTier(List<Tier> tiers, BigDecimal quantity) {
        if (tiers == null || tiers.isEmpty() || quantity == null || quantity.signum() <= 0) {
            return null;
        }
        return tiers.stream()
                .filter(t -> t != null && t.minQty() != null && positive(t.price()))
                .filter(t -> quantity.compareTo(t.minQty()) >= 0)
                .filter(t -> t.maxQty() == null || quantity.compareTo(t.maxQty()) <= 0)
                .max(java.util.Comparator.comparing(Tier::minQty))
                .orElse(null);
    }

    private static boolean positive(BigDecimal value) {
        return value != null && value.signum() > 0;
    }

    private static BigDecimal scale(BigDecimal value) {
        return value.setScale(2, java.math.RoundingMode.HALF_UP);
    }
}
