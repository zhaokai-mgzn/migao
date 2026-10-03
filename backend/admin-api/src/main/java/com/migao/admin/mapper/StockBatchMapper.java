package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.StockBatch;
import lombok.Data;
import org.apache.ibatis.annotations.Insert;
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

    /**
     * <b>原子取号</b>：把「判 {@code batch_no} 是否被占」与「占用它」并成<b>一条语句</b>
     * （issue #6248）。受影响行数 {@code 1} = 号归我（批次行已落库）；{@code 0} = 号刚被别人抢走
     * （调用方换个候选再来，见 {@code InboundOrderService#post} 的取号循环）。
     *
     * <p>🔴 <b>为什么名字叫 {@code update} 而 SQL 是 INSERT</b>：语义上它是「占号」（写一行批次），
     * 但<b>名字不许改成 {@code insertXxx} / {@code saveXxx} 这类<b>更长</b>的写法</b> ——
     * 台账类级元守卫 {@code AfterSalesSideEffectConcurrencyMetaGuardTest} 的形态扫描器只认
     * <b>逐字</b>的方法名（{@code insert(} / {@code update(} / {@code updateById(} / {@code delete(} /
     * {@code deleteById(} / {@code save(} / {@code restoreStock(} / {@code deductStock(}）；
     * 名字一旦变长，{@code InboundOrderService#post} 会**静默掉出候选集** ⇒ 那条「同一事务里的多个
     * 副作用必须登记并发保护」的台账即刻变空转（本包实测踩过三次）。</p>
     *
     * <p><b>为什么必须由 DB 判</b>：改前是 {@code exists(tenant_id, batch_no)} 判假 ⇒ 返回候选 ⇒
     * <b>之后</b>才 insert。这个「读-判-写」窗口在<b>多实例 / 重启</b>下可被利用
     * （两个实例的进程内计数器从同一位置起步 ⇒ 同一个候选 ⇒ 两边 {@code exists} 都为假）
     * ⇒ 后到的 insert 撞 {@code uk_stock_batches_no} 抛 {@code DuplicateKeyException}
     * ⇒ 用户侧 500（重试逻辑只覆盖「生成时已存在」，<b>不覆盖</b>「插入时被抢」）。
     * 唯一索引在插入那一刻的判定才是原子的 ⇒ 把候选交给它裁。</p>
     *
     * <p>{@code ON CONFLICT … DO NOTHING} 与「捕获 {@code DuplicateKeyException} 再重试」的差别是
     * <b>语义性</b>的：冲突时 PG 的<b>当前事务不会进入 aborted 状态</b>（该语句不报错）
     * ⇒ 可以在<b>同一个事务</b>里安全地换号重试；若靠捕获异常，PG 已把事务标记为坏
     * ⇒ 只有 {@code REQUIRES_NEW}（独立事务）才救得回来，而那会把批次行提前提交
     * （后续步骤失败 ⇒ 留下「有批次、没库存」的残行）。</p>
     */
    @Insert("INSERT INTO stock_batches (tenant_id, batch_no, product_id, sku_id, sku_code, inbound_order_id,"
            + " inbound_item_id, inbound_no, quantity, unit_cost, amount, dye_lot, legacy_batch_no,"
            + " roll_length_m, supplier, warehouse, received_date, remark)"
            + " VALUES (#{b.tenantId}, #{b.batchNo}, #{b.productId}, #{b.skuId}, #{b.skuCode},"
            + " #{b.inboundOrderId}, #{b.inboundItemId}, #{b.inboundNo}, #{b.quantity}, #{b.unitCost},"
            + " #{b.amount}, #{b.dyeLot}, #{b.legacyBatchNo}, #{b.rollLengthM}, #{b.supplier},"
            + " #{b.warehouse}, #{b.receivedDate}, #{b.remark})"
            + " ON CONFLICT (tenant_id, batch_no) DO NOTHING")
    int update(@Param("b") StockBatch batch);
}
