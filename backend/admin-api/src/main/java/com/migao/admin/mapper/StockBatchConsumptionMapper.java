package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.StockBatchConsumption;
import lombok.Data;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.math.BigDecimal;
import java.util.Collection;
import java.util.List;

/**
 * 批次消耗台账 Mapper（V116，issue #5145 阶段 1）。
 *
 * <p>写入一律走 {@code StockBatchConsumptionService}（它保证 delta 与 before/after 三者自洽、
 * 且与加工单生成/作废**同一事务**）；本接口的只读汇总两条是给**余量派生**与**对账读面**用的。</p>
 */
@Mapper
public interface StockBatchConsumptionMapper extends BaseMapper<StockBatchConsumption> {

    /**
     * 逐批次汇总消耗（Σdelta；负数 = 净扣减）。
     *
     * <p>余量 = {@code stock_batches.quantity + Σdelta} ⇒ 这里只回**一个数**，余量公式不在 SQL 里再写一份
     * （两处公式必然漂移；漂移的表现是「列表里的余量」与「对账读面的余量」不一致）。</p>
     */
    @Select("<script>"
            + "SELECT batch_id, COALESCE(SUM(delta), 0) AS delta_sum "
            + "FROM stock_batch_consumptions "
            + "WHERE tenant_id = #{tenantId} AND deleted = 0 "
            + "AND batch_id IN <foreach collection='batchIds' item='id' open='(' separator=',' close=')'>#{id}</foreach> "
            + "GROUP BY batch_id"
            + "</script>")
    List<BatchDeltaSum> sumDeltaByBatchIds(@Param("tenantId") Long tenantId,
                                           @Param("batchIds") Collection<Long> batchIds);

    /**
     * 逐 SKU 汇总批次消耗（对账读面：{@code Σ批次余量} 的扣减腿 + 排料节省腿）。
     *
     * <p>{@code sku_id IS NULL} 的行不参与（无法归属到某个 SKU 的批次扣减读不出「属于谁」）——
     * 本单的批次只由入库产生、入库必有 SKU（{@code InboundOrderService.post} 传 {@code sku.getId()}），
     * 故该分支现实上为空；真出现时对账读面的 {@code reconciled} 会判 false（不静默）。</p>
     *
     * <p>{@code formulaSum}（V119，issue #5158）= 同一批行的**公式口径**净额。它与 {@code deltaSum}
     * 同粒度、同谓词、同一次扫描 ⇒ 对账读面可以把差额拆成
     * 「已售未派（{@code soldDeducted − formulaSum}）」与「排料节省（{@code formulaSum − dispatched}）」
     * 两项，而两项相加**逐值等于**拆之前的那个总解释项（不是两次查询凑出来的近似）。</p>
     */
    @Select("SELECT sku_id, COALESCE(SUM(delta), 0) AS delta_sum, "
            + "COALESCE(SUM(formula_meters), 0) AS formula_sum "
            + "FROM stock_batch_consumptions "
            + "WHERE tenant_id = #{tenantId} AND deleted = 0 AND sku_id IS NOT NULL "
            + "GROUP BY sku_id")
    List<SkuDeltaSum> sumDeltaBySku(@Param("tenantId") Long tenantId);

    /** 逐批次汇总行（列别名 → 驼峰由 `map-underscore-to-camel-case` 映射） */
    @Data
    class BatchDeltaSum {
        private Long batchId;
        private BigDecimal deltaSum;
    }

    /** 逐 SKU 汇总行（{@code formulaSum} = 公式口径净额，V119 / issue #5158） */
    @Data
    class SkuDeltaSum {
        private Long skuId;
        private BigDecimal deltaSum;
        private BigDecimal formulaSum;
    }
}
