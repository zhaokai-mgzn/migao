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

    /**
     * 逐 (时间桶 × 来源组 × 物料) 汇总省料（issue #5159 L2 看板的汇总腿 / 判据 1）。
     *
     * <p>🔴 <b>金额腿在 SQL 里就按「逐行」取整再求和</b>：
     * {@code SUM(ROUND((formula_meters - planned_meters) * unit_cost, 2))} 与实体的
     * {@code getSavedAmount()}（{@code saved.multiply(unitCost).setScale(2, HALF_UP)}）<b>逐值相等</b>
     * —— 都是「每一行先按分取整、再相加」。若改成「整段求和再取整」，分组求和与逐单求和会差几分钱，
     * 那就是判据 1 明令禁止的<b>两套口径</b>。
     * （两列均受 CHECK 约束非负 ⇒ PG 的 {@code ROUND(numeric,2)} 与 {@code HALF_UP} 同结果。）</p>
     *
     * <p>米数腿：{@code SUM(formula_meters - planned_meters)} 与逐行 {@code getSavedMeters()} 的求和
     * 逐值相等（{@code NUMERIC(12,1)} 精确十进制，无中间取整）。</p>
     *
     * <p>{@code saved_amount_sum} <b>不 COALESCE</b>：全组行都没有均价时它必须是 {@code NULL}
     * ——「读不出金额」与「省了 0 元」是两件事（判据 4）。{@code known_cost_lines} 让读面能区分
     * 「金额为 0」与「没有一行有均价」。</p>
     *
     * @param tz 时区（{@code Asia/Shanghai}；{@code created_at} 是 TIMESTAMPTZ，必须显式定时区，
     *           否则同一批行在 UTC 与本地下会落到不同的月份 —— 跨月边界上就是两个数）
     * @param fmt PG {@code to_char} 的时间格式（月 {@code YYYY-MM} / ISO 周 {@code IYYY-"W"IW}）
     */
    @Select("SELECT to_char(c.created_at AT TIME ZONE #{tz}, #{fmt}) AS period, "
            + "COALESCE(o.source, 'unknown') AS source, c.product_id, c.sku_code, "
            + "COALESCE(SUM(c.formula_meters), 0) AS formula_sum, "
            + "COALESCE(SUM(c.planned_meters), 0) AS planned_sum, "
            + "SUM(ROUND((c.formula_meters - c.planned_meters) * c.unit_cost, 2)) AS saved_amount_sum, "
            + "COUNT(*) AS line_count, "
            + "COUNT(*) FILTER (WHERE c.unit_cost IS NOT NULL) AS known_cost_lines "
            + "FROM stock_batch_consumptions c "
            + "LEFT JOIN stock_batches b ON b.id = c.batch_id "
            + "LEFT JOIN inbound_orders o ON o.id = b.inbound_order_id "
            + "WHERE c.tenant_id = #{tenantId} AND c.deleted = 0 "
            + "GROUP BY 1, 2, 3, 4 "
            + "ORDER BY 1, 2, 3, 4")
    List<SavingSum> sumSavingByPeriodCohortMaterial(@Param("tenantId") Long tenantId,
                                                    @Param("tz") String tz,
                                                    @Param("fmt") String fmt);

    /**
     * 逐 (时间桶 × 来源组) 汇总<b>入库米数</b>（issue #5159 指标②「入库/采购总米数」）。
     *
     * <p>只走入库事实账：{@code stock_batches}（一行 = 一条入库明细 = 一卷的入库量）
     * join {@code inbound_orders}。时间桶取 {@code o.inbound_date}（<b>业务日期</b>，
     * 可回填历史单 ⇒ 与 {@code created_at} 的「录入时间」不是一回事，这也是 V111 把它们分成两列的理由）。
     * {@code inbound_date} 是 {@code DATE} ⇒ <b>无时区问题</b>（不做 {@code AT TIME ZONE}）。</p>
     *
     * <p>🔴 <b>{@code opening} 单列</b>（判据 2）：期初建账的入库量不是「这个月的采购」，
     * 是切换前的历史包袱 —— 混进②会让指标②永远被历史量压着，改善看不出来。
     * 本查询按 {@code source} 分组回，由读面决定谁进②、谁单列；<b>不在这里替调用方合并</b>。</p>
     */
    @Select("SELECT to_char(o.inbound_date, #{fmt}) AS period, o.source AS source, "
            + "COALESCE(SUM(b.quantity), 0) AS meters, "
            + "COUNT(*) AS batch_count "
            + "FROM stock_batches b "
            + "JOIN inbound_orders o ON o.id = b.inbound_order_id "
            + "WHERE b.tenant_id = #{tenantId} AND b.deleted = 0 AND o.deleted = 0 "
            + "GROUP BY 1, 2 "
            + "ORDER BY 1, 2")
    List<InboundSum> sumInboundMetersByPeriodSource(@Param("tenantId") Long tenantId,
                                                    @Param("fmt") String fmt);

    /**
     * 逐时间桶汇总<b>产出面积</b>（L3 的分母，issue #5159）。
     *
     * <p>口径 = 同期派工明细覆盖的<b>窗户面积</b>（{@code order_items.width × height}；两列注释即「米」）。
     * 分子（消耗米数）与分母取自<b>同一批扣减行</b> ⇒ 比值天然同集，不是跨表拼出来的两个数。</p>
     *
     * <p>🔴 <b>按 {@code order_item_id} 去重</b>：同一明细行可能有多行扣减（拆多批次 / 作废后重新生成）
     * ⇒ 不去重会把同一个窗户的面积算两次、分母虚高、单位产出消耗虚低（= 把效率说好了）。
     * 子查询里 {@code GROUP BY period, order_item_id} 只取一次面积，外层再按时间桶求和。</p>
     *
     * <p>只取 {@code planned_meters > 0} 的行 = <b>派料</b>行（回补行是负的：它既不是产出，也不是消耗）。</p>
     */
    @Select("SELECT t.period AS period, SUM(t.area_m2) AS area_m2, COUNT(*) AS output_lines "
            + "FROM (SELECT to_char(c.created_at AT TIME ZONE #{tz}, #{fmt}) AS period, "
            + "             c.order_item_id AS item_id, "
            + "             COALESCE(MAX(i.width), 0) * COALESCE(MAX(i.height), 0) AS area_m2 "
            + "        FROM stock_batch_consumptions c "
            + "        LEFT JOIN order_items i ON i.id = c.order_item_id "
            + "       WHERE c.tenant_id = #{tenantId} AND c.deleted = 0 AND c.planned_meters > 0 "
            + "       GROUP BY 1, 2) t "
            + "GROUP BY t.period "
            + "ORDER BY t.period")
    List<AreaSum> sumOutputAreaByPeriod(@Param("tenantId") Long tenantId,
                                        @Param("tz") String tz,
                                        @Param("fmt") String fmt);

    /** 逐批次汇总行（列别名 → 驼峰由 `map-underscore-to-camel-case` 映射） */
    @Data
    class BatchDeltaSum {
        private Long batchId;
        private BigDecimal deltaSum;
    }

    /** 逐 (时间桶 × 来源 × 物料) 的省料汇总行（issue #5159） */
    @Data
    class SavingSum {
        private String period;
        /** 来源组：{@code purchase} / {@code opening} / {@code unknown}（{@code inbound_orders.source}） */
        private String source;
        private String productId;
        private String skuCode;
        private BigDecimal formulaSum;
        private BigDecimal plannedSum;
        /** Σ 逐行 {@code ROUND(saved_meters × unit_cost, 2)}；**全组无均价时为 NULL**（不冒充 0） */
        private BigDecimal savedAmountSum;
        private Integer lineCount;
        /** 有均价的扣减行数（{@code savedAmountSum} 的覆盖范围） */
        private Integer knownCostLines;
    }

    /** 逐 (时间桶 × 来源) 的入库汇总行（issue #5159 指标②） */
    @Data
    class InboundSum {
        private String period;
        private String source;
        private BigDecimal meters;
        private Integer batchCount;
    }

    /** 逐时间桶的产出面积行（issue #5159 L3 分母） */
    @Data
    class AreaSum {
        private String period;
        private BigDecimal areaM2;
        /** 去重后的明细行数（{@code (时间桶 × order_item_id)} 的个数） */
        private Integer outputLines;
    }

    /** 逐 SKU 汇总行（{@code formulaSum} = 公式口径净额，V119 / issue #5158） */
    @Data
    class SkuDeltaSum {
        private Long skuId;
        private BigDecimal deltaSum;
        private BigDecimal formulaSum;
    }
}
