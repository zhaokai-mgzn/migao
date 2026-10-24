package com.migao.admin.dto;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * 创建采购单请求（issue #7369 段 4）。
 *
 * <p>没有 `status` 字段：新建单一律 `ordered`，之后只能由收货 / 关闭推进 ——
 * 状态可写就会出现「单据说没收齐、实际收齐了」的两面口径。</p>
 *
 * @param supplierId   供应商档案 id
 * @param orderDate    下单日（可空 ⇒ 业务今天）
 * @param expectedDate 预计到货日（可空）
 * @param remark       备注
 * @param items        明细（至少一行）
 */
public record PurchaseOrderCreateRequest(String supplierId,
                                         LocalDate orderDate,
                                         LocalDate expectedDate,
                                         String remark,
                                         List<Item> items) {

    /**
     * 一行明细。
     *
     * @param skuId     采购的 SKU
     * @param quantity  数量（> 0）
     * @param unitPrice 单价（≥ 0，最多两位小数 —— 钱只有两位小数的物理意义）
     * @param productId 商品 id（可空，按 sku 反查即可；给了就顺带校验同租户）
     */
    public record Item(String skuId, BigDecimal quantity, BigDecimal unitPrice, String productId) {
    }
}
