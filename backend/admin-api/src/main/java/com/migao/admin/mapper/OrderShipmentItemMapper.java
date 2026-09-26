package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.OrderShipmentItem;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.ResultMap;
import org.apache.ibatis.annotations.Select;

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
}
