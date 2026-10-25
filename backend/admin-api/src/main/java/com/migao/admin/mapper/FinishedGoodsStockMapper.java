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
            + " product_id, product_name, quantity, unit, status, inbound_order_id, deleted) "
            + "VALUES (#{tenantId}, #{warehouseId}, #{locationId}, #{binCode}, #{orderId}, #{orderNo}, "
            + "        #{orderItemId}, #{productId}, #{productName}, #{quantity,jdbcType=NUMERIC}, 'set', "
            + "        'in_stock', #{inboundOrderId}, 0) "
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
                      @Param("inboundOrderId") String inboundOrderId);

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
}
