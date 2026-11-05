package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.FollowStatusStatsResponse;
import com.migao.admin.dto.OrderStatisticsResponse;
import com.migao.admin.entity.Order;
import com.migao.admin.mapper.OrderMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

/**
 * 订单**统计与跟进读取**族（issue #8681，P2-1e 第五批）：实现点从 {@link OrderService} 搬来，
 * 方法体（含 COUNT 查询口径与字段映射）逐字跟随，没有任何口径改写。
 *
 * <p><b>为什么单开一个服务，而不是并进 {@link OrderQueryService}</b>：后者现取 **755** 行，
 * 本族约 90 行 ⇒ 并进去会越过 **800** 行的新类阈值（issue #8681 的判据 4「新类 &lt; 800 行」）。
 * 三个方法都只读 {@code OrderMapper}、且是同一个「统计 / 跟进」语义族 ⇒ 同址收在某处，
 * 不制造「统计逻辑分散在三个文件」的第二份口径。</p>
 *
 * <p><b>返工点已销账</b>（issue #8681，P2-1e 第七批）：同族的写面 {@code updateFollowStatus} 搬进
 * {@link OrderEntityWriteService} 的同时，读面 {@code getFollowStatus} 也从本类<b>合并回</b>同一处 ——
 * 「跟进状态」的读与写同址收口，不再分处两个文件。本类只剩两个<b>统计</b>入口
 * （{@code getOrderStatistics} / {@code getFollowStatusStats}）。</p>
 *
 * <p><b>看管</b>：门面的三条同名转发已删除且不许回来（{@code OrderFacadeForwarderRetirementTest} 的退休面 +
 * 具名消费方清单）；本类内部口径由 {@code OrderStatsServiceTest} 逐条钉住。</p>
 */
@Service
@RequiredArgsConstructor
public class OrderStatsService {

    private final OrderMapper orderMapper;

    /**
     * 获取订单统计（使用 COUNT 查询，避免全量加载到内存）
     */
    public OrderStatisticsResponse getOrderStatistics(Long tenantId) {
        long total = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId));
        long pending = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, OrderStatusTransitions.PENDING));
        long confirmed = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, OrderStatusTransitions.CONFIRMED));
        long producing = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, OrderStatusTransitions.PRODUCING));
        long shipped = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, OrderStatusTransitions.SHIPPED));
        long completed = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, OrderStatusTransitions.COMPLETED));
        long cancelled = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, OrderStatusTransitions.CANCELLED));

        return OrderStatisticsResponse.builder()
                .totalCount(total)
                .pendingCount(pending)
                .confirmedCount(confirmed)
                .producingCount(producing)
                .shippedCount(shipped)
                .completedCount(completed)
                .cancelledCount(cancelled)
                .unpaidCount(pending)
                .paidCount(confirmed + producing + shipped + completed)
                .refundedCount(cancelled) // 退款订单即已取消的订单
                .build();
    }

    /**
     * 获取跟进状态统计（使用 COUNT 查询，避免全量加载到内存）
     */
    public FollowStatusStatsResponse getFollowStatusStats(Long tenantId) {
        long total = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId));
        long following = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getFollowStatus, "following"));
        long completedFollow = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getFollowStatus, "completed"));
        // pending = total - following - completed（含 null 值）
        long pendingFollow = total - following - completedFollow;

        return FollowStatusStatsResponse.builder()
                .pending(pendingFollow)
                .following(following)
                .completed(completedFollow)
                .total(total)
                .build();
    }

}
