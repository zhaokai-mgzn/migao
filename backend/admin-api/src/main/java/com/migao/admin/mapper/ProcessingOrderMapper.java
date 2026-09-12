package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingOrder;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 加工单 Mapper（issue #3340）
 */
@Mapper
public interface ProcessingOrderMapper extends BaseMapper<ProcessingOrder> {

    /**
     * 订单当前的活跃加工单（非取消态，租户隔离由 TenantLineInnerInterceptor 注入）
     */
    @Select("SELECT * FROM processing_orders WHERE order_id = #{orderId} AND tenant_id = #{tenantId} " +
            "AND deleted = 0 AND status IN ('generated','issued','in_processing','completed') LIMIT 1")
    ProcessingOrder selectActiveByOrderId(@Param("orderId") String orderId, @Param("tenantId") Long tenantId);

    /**
     * 按加工单号/订单号/订单UUID 解析加工单（租户隔离）
     */
    @Select("SELECT po.* FROM processing_orders po " +
            "LEFT JOIN orders o ON po.order_id = o.id " +
            "WHERE po.tenant_id = #{tenantId} AND po.deleted = 0 " +
            "AND (po.processing_order_no = #{keyword} OR o.order_no = #{keyword} OR po.order_id = #{keyword}) " +
            "ORDER BY po.created_at DESC LIMIT 10")
    List<ProcessingOrder> selectByKeyword(@Param("keyword") String keyword, @Param("tenantId") Long tenantId);

    /**
     * 订单是否已有完成的加工单（shipped 守卫用）
     */
    @Select("SELECT COUNT(1) FROM processing_orders WHERE order_id = #{orderId} AND tenant_id = #{tenantId} " +
            "AND deleted = 0 AND status = 'completed'")
    long countCompletedByOrderId(@Param("orderId") String orderId, @Param("tenantId") Long tenantId);
}
