package com.aikf.admin.mapper;

import com.aikf.admin.entity.Order;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

/**
 * 订单 Mapper 接口
 */
@Mapper
public interface OrderMapper extends BaseMapper<Order> {

    @Select("SELECT DATE(created_at) as date, COUNT(*) as orders, COALESCE(SUM(total_amount), 0) as amount " +
            "FROM orders WHERE tenant_id = #{tenantId} AND deleted = 0 AND created_at >= #{startDate} " +
            "GROUP BY DATE(created_at) ORDER BY date")
    List<Map<String, Object>> selectOrderTrend(@Param("tenantId") Long tenantId,
                                               @Param("startDate") OffsetDateTime startDate);

    @Select("SELECT status, COUNT(*) as count FROM orders " +
            "WHERE tenant_id = #{tenantId} AND deleted = 0 GROUP BY status")
    List<Map<String, Object>> selectOrderStatusDistribution(@Param("tenantId") Long tenantId);
}
