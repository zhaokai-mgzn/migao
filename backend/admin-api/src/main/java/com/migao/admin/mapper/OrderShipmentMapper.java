package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.OrderShipment;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.ResultMap;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 发货单 Mapper（issue #5648）。
 *
 * <p>标准 CRUD 由 {@code TenantLineInnerInterceptor} 自动注入租户过滤 ⇒
 * {@code selectById} 天然看不见别的租户的发货单（跨租户 = 查不到 ⇒ NOT_FOUND，零写）。</p>
 *
 * <p>🔴 手写 {@code @Select} 必须显式绑 {@code @ResultMap("mybatis-plus_OrderShipment")}：
 * 否则 {@code photo_refs} / {@code recognition}（JSONB）以 JSON **字符串**落到 {@code Object} 字段上
 * （同 {@code OrderLogisticsMapper} / {@code ProcessingOrderMapper} 的实测口径 ——
 * 该形态曾让加工项守卫静默失效）。</p>
 */
@Mapper
public interface OrderShipmentMapper extends BaseMapper<OrderShipment> {

    /** 某订单的全部发货单（新的在前）—— 读面的唯一来源。 */
    @ResultMap("mybatis-plus_OrderShipment")
    @Select("SELECT * FROM order_shipments WHERE order_id = #{orderId} AND tenant_id = #{tenantId} "
            + "AND deleted = 0 ORDER BY created_at DESC")
    List<OrderShipment> selectByOrderId(@Param("orderId") String orderId, @Param("tenantId") Long tenantId);

    /** 幂等键查重（唯一索引 {@code uk_order_shipments_idem} 的读面；无键 ⇒ null）。 */
    @ResultMap("mybatis-plus_OrderShipment")
    @Select("SELECT * FROM order_shipments WHERE tenant_id = #{tenantId} "
            + "AND client_request_id = #{clientRequestId} AND deleted = 0 LIMIT 1")
    OrderShipment selectByClientRequestId(@Param("tenantId") Long tenantId,
                                          @Param("clientRequestId") String clientRequestId);
}
