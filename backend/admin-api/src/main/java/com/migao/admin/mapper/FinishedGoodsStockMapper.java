package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.FinishedGoodsStock;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.math.BigDecimal;
import java.util.List;

/**
 * 成品在库（V196，issue #7750）。
 *
 * <p>所有手写 SQL 都标 {@code @InterceptorIgnore(tenantLine = "true")}（与
 * {@code ProductSkuMapper#deductStock} 同源）：它们自己写了 {@code tenant_id}，
 * 而占位那条是 {@code WITH ins AS (INSERT … ON CONFLICT …) SELECT} —— 租户插件二次注入会改出错误 SQL。</p>
 *
 * <p>状态迁移全部用**条件更新**（{@code WHERE status='in_stock'}）：发货与撤销打包可能并发，
 * 读-判-写会让同一行被两条路径各改一次（一条记 shipped、一条记 unpacked，终态取决于谁后写）。
 * 判断与写入压进同一条语句，受影响行数就是「这次到底改到了几行」。</p>
 */
@Mapper
public interface FinishedGoodsStockMapper extends BaseMapper<FinishedGoodsStock> {

    /**
     * **原子占位**：把「这个成品的订单行 + 这个仓位」写成一条在库行；撞唯一索引（仓位被占 /
     * 同一订单行已在库）⇒ <b>0 行 / null</b>、不抛异常（理由同 {@code WarehouseLocationMapper#claimBin}：
     * 唯一冲突会让当前事务 aborted，捕获后再重试是非法路径）。
     *
     * <p>返回新行 id；{@code null} = 没抢到（调用方换下一个空闲仓位）。</p>
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("WITH ins AS ("
            + "INSERT INTO finished_goods_stock "
            + "(tenant_id, warehouse_id, location_id, bin_code, order_id, order_no, order_item_id, "
            + " product_id, product_name, quantity, unit, status, inbound_order_id, "
            + " set_id, set_no, set_index, part_token_id, short_code, deleted) "
            + "VALUES (#{tenantId}, #{warehouseId}, #{locationId}, #{binCode}, #{orderId}, #{orderNo}, "
            + "        #{orderItemId}, #{productId}, #{productName}, #{quantity,jdbcType=NUMERIC}, 'set', "
            + "        'in_stock', #{inboundOrderId}, "
            + "        #{setId,jdbcType=VARCHAR}, #{setNo,jdbcType=VARCHAR}, #{setIndex,jdbcType=INTEGER}, "
            + "        #{partTokenId,jdbcType=VARCHAR}, #{shortCode,jdbcType=VARCHAR}, 0) "
            + "ON CONFLICT DO NOTHING RETURNING id) SELECT id FROM ins")
    Long claimInStock(@Param("tenantId") Long tenantId,
                      @Param("warehouseId") Long warehouseId,
                      @Param("locationId") Long locationId,
                      @Param("binCode") String binCode,
                      @Param("orderId") String orderId,
                      @Param("orderNo") String orderNo,
                      @Param("orderItemId") String orderItemId,
                      @Param("productId") String productId,
                      @Param("productName") String productName,
                      @Param("quantity") BigDecimal quantity,
                      @Param("inboundOrderId") String inboundOrderId,
                      @Param("setId") String setId,
                      @Param("setNo") String setNo,
                      @Param("setIndex") Integer setIndex,
                      @Param("partTokenId") String partTokenId,
                      @Param("shortCode") String shortCode);

    /**
     * V196 形态的占位重载（保留给既有调用方/单测）：套 × 部位五列为空 ⇒ 走「订单行粒度」兜底行
     * （与 V197 之前的语义逐字相同）。
     */
    default Long claimInStock(Long tenantId, Long warehouseId, Long locationId, String binCode,
                              String orderId, String orderNo, String orderItemId, String productId,
                              String productName, BigDecimal quantity, String inboundOrderId) {
        return claimInStock(tenantId, warehouseId, locationId, binCode, orderId, orderNo, orderItemId,
                productId, productName, quantity, inboundOrderId, null, null, null, null, null);
    }

    /** 本单当前在库的成品行（按仓位号排序，界面直接可读）。 */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT * FROM finished_goods_stock "
            + "WHERE tenant_id = #{tenantId} AND order_id = #{orderId} "
            + "  AND status = 'in_stock' AND deleted = 0 ORDER BY bin_code")
    List<FinishedGoodsStock> selectInStockByOrder(@Param("tenantId") Long tenantId,
                                                  @Param("orderId") String orderId);

    /** 在库总览（成品库存页）。 */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT * FROM finished_goods_stock "
            + "WHERE tenant_id = #{tenantId} AND status = 'in_stock' AND deleted = 0 "
            + "ORDER BY bin_code LIMIT 500")
    List<FinishedGoodsStock> selectInStock(@Param("tenantId") Long tenantId);

    /** 发货出库：在库 → 已发货（仓位释放）+ 记出库单；返回受影响行数。 */
    @InterceptorIgnore(tenantLine = "true")
    @Update("UPDATE finished_goods_stock SET status = 'shipped', outbound_order_id = #{outboundOrderId}, "
            + "updated_at = NOW() WHERE tenant_id = #{tenantId} AND order_id = #{orderId} "
            + "AND status = 'in_stock' AND deleted = 0")
    int markShippedByOrder(@Param("tenantId") Long tenantId,
                           @Param("orderId") String orderId,
                           @Param("outboundOrderId") String outboundOrderId);

    /** 撤销打包：在库 → 已撤销（仓位释放）；返回受影响行数。 */
    @InterceptorIgnore(tenantLine = "true")
    @Update("UPDATE finished_goods_stock SET status = 'unpacked', updated_at = NOW() "
            + "WHERE tenant_id = #{tenantId} AND order_id = #{orderId} "
            + "AND status = 'in_stock' AND deleted = 0")
    int markUnpackedByOrder(@Param("tenantId") Long tenantId, @Param("orderId") String orderId);

    /**
     * 按水洗唛（token 或短码）取**在库**行（V197 / issue #7762：一张水洗唛 = 一个仓位）。
     *
     * <p>短码与 token 是同一行的两种表示，故一条 OR 条件即可；两张表都显式写 {@code tenant_id}
     * （不靠拦截器），{@code deleted = 0} 正向相等 ⇒ 撤销的码查不到。</p>
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT f.* FROM finished_goods_stock f "
            + "JOIN processing_set_part_tokens t ON t.id = f.part_token_id "
            + "WHERE f.tenant_id = #{tenantId} AND f.status = 'in_stock' AND f.deleted = 0 "
            + "  AND t.tenant_id = #{tenantId} AND t.deleted = 0 "
            + "  AND (t.token = #{key} OR t.short_code = #{key}) "
            + "ORDER BY f.id DESC LIMIT 1")
    FinishedGoodsStock selectInStockByWashLabel(@Param("tenantId") Long tenantId, @Param("key") String key);

    /** 扫水洗唛出库：在库 → 已发货（按行 id，条件更新 ⇒ 并发只放行一次）；返回受影响行数。 */
    @InterceptorIgnore(tenantLine = "true")
    @Update("UPDATE finished_goods_stock SET status = 'shipped', outbound_order_id = #{outboundOrderId}, "
            + "updated_at = NOW() WHERE tenant_id = #{tenantId} AND id = #{id} "
            + "AND status = 'in_stock' AND deleted = 0")
    int markShippedById(@Param("tenantId") Long tenantId, @Param("id") Long id,
                        @Param("outboundOrderId") String outboundOrderId);

    /**
     * 本租户所有**被在库成品占用**的仓位号（issue #7785 的「仓位管理」列占用态）。
     *
     * <p>刻意**不**复用 {@link #selectInStock}（它带 {@code LIMIT 500}，成品多的租户会把
     * 第 501 件之后的仓位误显示成「空闲」）；这里一条聚合查询、不搬整行数据。</p>
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT DISTINCT bin_code FROM finished_goods_stock "
            + "WHERE tenant_id = #{tenantId} AND status = 'in_stock' AND deleted = 0")
    List<String> selectOccupiedBinCodes(@Param("tenantId") Long tenantId);

    /** 这个仓位号上是否有在库成品（改号 / 删除前的占用判定）。 */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT count(*) FROM finished_goods_stock "
            + "WHERE tenant_id = #{tenantId} AND bin_code = #{binCode} "
            + "AND status = 'in_stock' AND deleted = 0")
    int countInStockByBinCode(@Param("tenantId") Long tenantId, @Param("binCode") String binCode);
}
