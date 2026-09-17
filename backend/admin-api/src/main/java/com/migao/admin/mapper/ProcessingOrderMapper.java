package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingOrder;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;
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

    /**
     * 把**活跃**加工单原子置 completed —— 生产报工「完工」的唯一写路径（issue #4117）。
     *
     * 生产完工 = **加工单**加工完成，**不是**订单状态推进：订单状态机
     * （OrderService.STATUS_TRANSITIONS）不设 producing→completed，且 completed 是终态
     * ⇒ 旧实现用裸 UpdateWrapper 直写订单 completed，会让含加工项订单**既发不了货也回不去**
     * （发货守卫读的正是本表 {@link #countCompletedByOrderId}，而 shipOrderIfApplicable
     * 只在订单 confirmed/producing 时流转）⇒ 把加工单置 completed、订单留在 producing，
     * 发货链才通。
     *
     * 条件 = 活跃集（与 {@link #selectActiveByOrderId} 同口径，排除 cancelled）：
     * 并发取消的加工单不会被复活；已是 completed 时不覆盖首次完工时间（重复报工幂等）。
     */
    @Update("UPDATE processing_orders SET status = 'completed', " +
            "completed_at = COALESCE(completed_at, #{completedAt}), updated_at = #{completedAt} " +
            "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 " +
            "AND status IN ('generated','issued','in_processing','completed')")
    int markCompletedIfActive(@Param("id") String id, @Param("tenantId") Long tenantId,
                              @Param("completedAt") OffsetDateTime completedAt);
}
