package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.OrderShipmentItem;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.ResultMap;
import org.apache.ibatis.annotations.Select;

import java.util.Collection;
import java.util.List;

/**
 * 发货明细 Mapper（issue #5648）—— 「这一单实际发了多少」的读写入口。
 *
 * <p>标准 CRUD 由 {@code TenantLineInnerInterceptor} 自动注入租户过滤。</p>
 */
@Mapper
public interface OrderShipmentItemMapper extends BaseMapper<OrderShipmentItem> {

    /** 一张发货单的全部明细（按创建序，便于纸面逐行复原）。 */
    @ResultMap("mybatis-plus_OrderShipmentItem")
    @Select("SELECT * FROM order_shipment_items WHERE shipment_id = #{shipmentId} "
            + "AND tenant_id = #{tenantId} AND deleted = 0 ORDER BY created_at ASC, id ASC")
    List<OrderShipmentItem> selectByShipmentId(@Param("shipmentId") String shipmentId,
                                               @Param("tenantId") Long tenantId);

    /** 某订单的全部实发明细（跨多张发货单；新单在前）。 */
    @ResultMap("mybatis-plus_OrderShipmentItem")
    @Select("SELECT * FROM order_shipment_items WHERE order_id = #{orderId} "
            + "AND tenant_id = #{tenantId} AND deleted = 0 ORDER BY created_at DESC, id DESC")
    List<OrderShipmentItem> selectByOrderId(@Param("orderId") String orderId,
                                            @Param("tenantId") Long tenantId);

    /**
     * 一批发货单的明细（issue #5939）—— 发货单**列表**页一次查完，再按发货单分组汇总。
     *
     * <p>为什么批量而不是逐单：列表一屏最多 {@code OrderShipmentService.LIST_LIMIT} 张单，
     * 逐单查就是 N+1（与 {@code InboundOrderQueryMapper} 把聚合放进一次读同一个口径）。</p>
     *
     * <p>租户维与软删维一个字都不能少 —— 与逐单读面同码
     * （判据：{@code OrderShipmentItemMapperTest.batchReadByShipmentIdsIsTenantScopedAndUsesIn}）。</p>
     */
    @ResultMap("mybatis-plus_OrderShipmentItem")
    @Select("""
            <script>
            SELECT * FROM order_shipment_items
             WHERE tenant_id = #{tenantId}
               AND deleted = 0
               AND shipment_id IN
               <foreach collection="shipmentIds" item="sid" open="(" separator="," close=")">#{sid}</foreach>
             ORDER BY created_at ASC, id ASC
            </script>
            """)
    List<OrderShipmentItem> selectByShipmentIds(@Param("shipmentIds") Collection<String> shipmentIds,
                                                @Param("tenantId") Long tenantId);
}
