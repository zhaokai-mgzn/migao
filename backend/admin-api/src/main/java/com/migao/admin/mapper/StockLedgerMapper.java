package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.StockLedger;
import lombok.Data;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.math.BigDecimal;
import java.util.List;

/**
 * 库存流水/台账 Mapper（V53，issue #4055）：SKU 级库存变更事实账
 */
@Mapper
public interface StockLedgerMapper extends BaseMapper<StockLedger> {

    /**
     * 逐 SKU 汇总台账（对账读面，V116 / issue #5145 阶段 1）。
     *
     * <p>三列是「{@code Σ批次余量} 与 {@code product_skus.stock} 的差额为什么是这个数」的
     * 分解腿（推导见 {@code StockBatchConsumptionService#reconcile}）：</p>
     * <ul>
     *   <li>{@code soldDeducted} = 销售账已扣净额 = {@code Σ(-delta)} 且 {@code reason='order'}
     *       （取消/退款回补也走 {@code order} ⇒ 自动净额化）；</li>
     *   <li>{@code otherDelta} = 销售账以外的净额（{@code aftersales} 退货回补 / {@code manual} 手工调整）——
     *       {@code inbound} **不计入**（入库同时产生批次行，已在「入库总米数」那一腿）；</li>
     *   <li>{@code totalDelta} = {@code Σdelta}（全部来源）⇒ {@code stock - totalDelta}
     *       就是「台账之外形成的库存」（存量/建品直接写 stock）。</li>
     * </ul>
     */
    @Select("SELECT sku_id, "
            + "COALESCE(SUM(CASE WHEN reason = 'order' THEN -delta ELSE 0 END), 0) AS sold_deducted, "
            + "COALESCE(SUM(CASE WHEN reason NOT IN ('order', 'inbound') THEN delta ELSE 0 END), 0) AS other_delta, "
            + "COALESCE(SUM(delta), 0) AS total_delta "
            + "FROM stock_ledger_entries "
            + "WHERE tenant_id = #{tenantId} AND deleted = 0 AND sku_id IS NOT NULL "
            + "GROUP BY sku_id")
    List<SkuLedgerSum> sumBySku(@Param("tenantId") Long tenantId);

    /** 逐 SKU 台账汇总行（列别名 → 驼峰由 `map-underscore-to-camel-case` 映射） */
    @Data
    class SkuLedgerSum {
        private Long skuId;
        private BigDecimal soldDeducted;
        private BigDecimal otherDelta;
        private BigDecimal totalDelta;
    }
}