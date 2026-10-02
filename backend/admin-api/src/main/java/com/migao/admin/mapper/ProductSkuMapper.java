package com.migao.admin.mapper;

import com.migao.admin.entity.ProductSku;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import java.math.BigDecimal;

/**
 * 商品SKU Mapper 接口
 *
 * <p><b>数量参数一律 {@link BigDecimal}（V115 / issue #5063）</b>：库存列已由 {@code INTEGER}
 * 升级为 {@code NUMERIC(12,1)}（1 位小数 = 0.1 米粒度）。这里<b>不得</b>再出现 {@code int} /
 * {@code intValue()} 形参 —— 传 {@code int} 会强迫调用方在边界上取整，而那种取整是静默的
 * （买 2.7 米扣 2 米、0.7 米凭空消失），正是本单要治的形态。
 * 「多少位小数算合法」的唯一判据在 {@code com.migao.admin.service.StockQuantity}。</p>
 */
@Mapper
public interface ProductSkuMapper extends BaseMapper<ProductSku> {

    @Update("UPDATE product_skus SET stock = GREATEST(COALESCE(stock, 0) - #{quantity}, 0) " +
            "WHERE id = #{skuId}")
    int deductStock(@Param("skuId") Long skuId, @Param("quantity") BigDecimal quantity);

    @Update("UPDATE product_skus SET stock = COALESCE(stock, 0) + #{quantity} " +
            "WHERE id = #{skuId}")
    int restoreStock(@Param("skuId") Long skuId, @Param("quantity") BigDecimal quantity);

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
     * <p><b>每个 {@code newAvgCost} 绑定都必须带 {@code jdbcType=NUMERIC}（issue #5975）</b>：
     * {@code CASE WHEN ? IS NULL} 里的 {@code ?} <b>没有列 / cast 作为类型锚点</b> —— 实参为
     * <b>NULL</b> 时 PG 收到的是 <i>unspecified</i> 类型参数，直接抛
     * {@code ERROR: could not determine data type of parameter $3} ⇒ {@code BadSqlGrammarException}
     * ⇒ 接口 500。而「新 SKU 首次入库 + 明细不记单价」（入库页明示允许留空）恰好<b>必然</b>
     * 走 null 实参（{@code InboundOrderService.movingAverage} 在无进价且此前无均价时原样返回
     * {@code beforeAvg} = NULL）⇒ 商家按页面提示操作时，新 SKU 的第一次过账必然失败。
     * 显式 jdbcType 让 PG 拿到参数类型，不再依赖推断。真库判据 =
     * {@code com.migao.admin.service.ProductSkuReceiveStockNullCostRealDbTest}。</p>
     *
     * @param newAvgCost 变更后的移动加权平均成本（null = 成本仍未知）
     */
    @Update("UPDATE product_skus SET "
            + "stock = COALESCE(stock, 0) + #{quantity}, "
            + "avg_cost = #{newAvgCost,jdbcType=NUMERIC}, "
            + "cost_amount = CASE WHEN #{newAvgCost,jdbcType=NUMERIC} IS NULL THEN NULL "
            + "                   ELSE ROUND((COALESCE(stock, 0) + #{quantity}) * #{newAvgCost,jdbcType=NUMERIC}, 4) END, "
            + "latest_batch_no = #{batchNo} "
            + "WHERE id = #{skuId}")
    int receiveStock(@Param("skuId") Long skuId, @Param("quantity") BigDecimal quantity,
                     @Param("newAvgCost") BigDecimal newAvgCost, @Param("batchNo") String batchNo);

    @Update("UPDATE product_skus SET sales_count = COALESCE(sales_count, 0) + #{quantity} " +
            "WHERE id = #{skuId}")
    void increaseSalesCount(@Param("skuId") Long skuId, @Param("quantity") BigDecimal quantity);

    @Update("UPDATE product_skus SET sales_count = GREATEST(COALESCE(sales_count, 0) - #{quantity}, 0) " +
            "WHERE id = #{skuId}")
    void decreaseSalesCount(@Param("skuId") Long skuId, @Param("quantity") BigDecimal quantity);
}
