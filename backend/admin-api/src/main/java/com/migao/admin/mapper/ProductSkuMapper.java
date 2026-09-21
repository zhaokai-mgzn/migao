package com.migao.admin.mapper;

import com.migao.admin.entity.ProductSku;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import java.math.BigDecimal;

/**
 * 商品SKU Mapper 接口
 */
@Mapper
public interface ProductSkuMapper extends BaseMapper<ProductSku> {

    @Update("UPDATE product_skus SET stock = GREATEST(COALESCE(stock, 0) - #{quantity}, 0) " +
            "WHERE id = #{skuId}")
    int deductStock(@Param("skuId") Long skuId, @Param("quantity") int quantity);

    @Update("UPDATE product_skus SET stock = COALESCE(stock, 0) + #{quantity} " +
            "WHERE id = #{skuId}")
    int restoreStock(@Param("skuId") Long skuId, @Param("quantity") int quantity);

    /**
     * 入库：加库存 + 写移动加权平均成本 + 记最近批次号（V111，issue #5034）。
     *
     * <p><b>均价由调用方（{@code InboundOrderService}）算好后传入</b>，不在 SQL 里重算 ——
     * 加权平均的公式只有一处实现（{@code InboundOrderService.movingAverage}），
     * 落库值与落台账的成本快照**必然同源**；两边各写一份公式迟早会漂移，
     * 而漂移的表现是「台账里的 avg_cost_after 与 SKU 上的 avg_cost 不一致」——
     * 一条只在事后对账时才看得见的账实不符。</p>
     *
     * <p>均价是<b>条件更新</b>：{@code newAvgCost IS NULL}（本行未记单价且此前无均价）时
     * 保持 NULL —— 不用 0 冒充「成本为零」。{@code cost_amount} 只在均价非 NULL 时算。</p>
     *
     * @param newAvgCost 变更后的移动加权平均成本（null = 成本仍未知）
     */
    @Update("UPDATE product_skus SET "
            + "stock = COALESCE(stock, 0) + #{quantity}, "
            + "avg_cost = #{newAvgCost}, "
            + "cost_amount = CASE WHEN #{newAvgCost} IS NULL THEN NULL "
            + "                   ELSE ROUND((COALESCE(stock, 0) + #{quantity}) * #{newAvgCost}, 4) END, "
            + "latest_batch_no = #{batchNo} "
            + "WHERE id = #{skuId}")
    int receiveStock(@Param("skuId") Long skuId, @Param("quantity") int quantity,
                     @Param("newAvgCost") BigDecimal newAvgCost, @Param("batchNo") String batchNo);

    @Update("UPDATE product_skus SET sales_count = COALESCE(sales_count, 0) + #{quantity} " +
            "WHERE id = #{skuId}")
    void increaseSalesCount(@Param("skuId") Long skuId, @Param("quantity") int quantity);

    @Update("UPDATE product_skus SET sales_count = GREATEST(COALESCE(sales_count, 0) - #{quantity}, 0) " +
            "WHERE id = #{skuId}")
    void decreaseSalesCount(@Param("skuId") Long skuId, @Param("quantity") int quantity);
}
