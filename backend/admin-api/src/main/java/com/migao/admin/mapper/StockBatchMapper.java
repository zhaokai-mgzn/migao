package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.StockBatch;
import lombok.Data;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * StockBatch Mapper（V111，issue #5034）
 */
@Mapper
public interface StockBatchMapper extends BaseMapper<StockBatch> {

    /**
     * 逐批次回「来源组」（issue #5159 判据 2：存量导入批次必须单列成组）。
     *
     * <p>来源 = 批次所属入库单的 {@code inbound_orders.source ∈ {purchase, opening}}（V117 / #5148）。
     * 批次行上的 {@code inbound_order_id} 可能为空（历史形态）⇒ 回 {@code unknown}
     * ——<b>不并进 purchase</b>：把「不知道从哪来的批次」算进「切换后采购」会让指标②虚高，
     * 而账面上看不出（本仓明令禁止的形态）。</p>
     *
     * <p><b>只回两个字段</b>：本查询的职责就是「批次 → 来源」，余量与物料口径一律复用
     * {@code StockBatchConsumptionService} 的既有实现（两处各算一份余量必然漂移）。</p>
     */
    @Select("SELECT b.id AS batch_id, COALESCE(o.source, 'unknown') AS source "
            + "FROM stock_batches b "
            + "LEFT JOIN inbound_orders o ON o.id = b.inbound_order_id "
            + "WHERE b.tenant_id = #{tenantId} AND b.deleted = 0")
    List<BatchSourceRow> listBatchSources(@Param("tenantId") Long tenantId);

    /** 逐批次来源行（列别名 → 驼峰由 `map-underscore-to-camel-case` 映射） */
    @Data
    class BatchSourceRow {
        private Long batchId;
        private String source;
    }
}
