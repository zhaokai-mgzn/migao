package com.aikf.admin.controller;

import com.aikf.admin.config.TenantContext;
import com.aikf.admin.dto.ApiResponse;
import com.aikf.admin.entity.*;
import com.aikf.admin.mapper.*;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.Builder;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.*;
import java.util.stream.Collectors;

/**
 * 数据看板控制器
 * 提供 Dashboard 统计数据接口
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/dashboard")
@RequiredArgsConstructor
public class DashboardController {

    private final ProductMapper productMapper;
    private final OrderMapper orderMapper;
    private final UserMapper userMapper;
    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final SessionMapper sessionMapper;
    private final SessionMessageMapper sessionMessageMapper;

    /**
     * 获取 Dashboard 统计数据
     *
     * GET /api/admin/dashboard/stats
     */
    @GetMapping("/stats")
    public ApiResponse<DashboardStatsResponse> getStats() {
        Long tenantId = TenantContext.getTenantId();
        log.info("获取 Dashboard 统计数据: tenantId={}", tenantId);

        // 今日起止时间（使用中国标准时间 UTC+8）
        ZoneId cst = ZoneId.of("Asia/Shanghai");
        OffsetDateTime todayStart = LocalDate.now(cst).atStartOfDay().atOffset(ZoneOffset.ofHours(8));
        OffsetDateTime yesterdayStart = todayStart.minusDays(1);

        // 商品总数
        long totalProducts = productMapper.selectCount(
                new LambdaQueryWrapper<Product>().eq(Product::getTenantId, tenantId));

        // 订单总数
        long totalOrders = orderMapper.selectCount(
                new LambdaQueryWrapper<Order>().eq(Order::getTenantId, tenantId));

        // 今日订单数
        long todayOrders = orderMapper.selectCount(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getTenantId, tenantId)
                        .ge(Order::getCreatedAt, todayStart));

        // 昨日订单数（用于环比）
        long yesterdayOrders = orderMapper.selectCount(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getTenantId, tenantId)
                        .ge(Order::getCreatedAt, yesterdayStart)
                        .lt(Order::getCreatedAt, todayStart));

        // 订单环比变化
        double todayOrdersChange = yesterdayOrders > 0
                ? ((double) (todayOrders - yesterdayOrders) / yesterdayOrders) * 100
                : 0;

        // 客户总数（role=customer 的用户）
        long totalCustomers = userMapper.selectCount(
                new LambdaQueryWrapper<User>()
                        .eq(User::getTenantId, tenantId)
                        .eq(User::getRole, "customer"));

        // 今日新增客户
        long newCustomersToday = userMapper.selectCount(
                new LambdaQueryWrapper<User>()
                        .eq(User::getTenantId, tenantId)
                        .eq(User::getRole, "customer")
                        .ge(User::getCreatedAt, todayStart));

        // 售后工单数
        long totalTickets = afterSalesTicketMapper.selectCount(
                new LambdaQueryWrapper<AfterSalesTicket>()
                        .eq(AfterSalesTicket::getTenantId, tenantId));

        // 本月营收（已确认+已完成订单的总金额）
        LocalDate now = LocalDate.now(cst);
        OffsetDateTime monthStart = now.withDayOfMonth(1).atStartOfDay().atOffset(ZoneOffset.ofHours(8));
        List<Order> monthOrders = orderMapper.selectList(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getTenantId, tenantId)
                        .ge(Order::getCreatedAt, monthStart)
                        .in(Order::getStatus, "confirmed", "producing", "shipped", "completed"));
        // 使用 BigDecimal 累加避免精度丢失（longValue() 会截断小数）
        BigDecimal monthRevenueBd = monthOrders.stream()
                .map(o -> o.getTotalAmount() != null ? o.getTotalAmount() : BigDecimal.ZERO)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
        long monthRevenue = monthRevenueBd.setScale(0, java.math.RoundingMode.HALF_UP).longValue();

        // 上月营收（环比）
        OffsetDateTime lastMonthStart = monthStart.minusMonths(1);
        List<Order> lastMonthOrders = orderMapper.selectList(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getTenantId, tenantId)
                        .ge(Order::getCreatedAt, lastMonthStart)
                        .lt(Order::getCreatedAt, monthStart)
                        .in(Order::getStatus, "confirmed", "producing", "shipped", "completed"));
        BigDecimal lastMonthRevenueBd = lastMonthOrders.stream()
                .map(o -> o.getTotalAmount() != null ? o.getTotalAmount() : BigDecimal.ZERO)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
        long lastMonthRevenue = lastMonthRevenueBd.setScale(0, java.math.RoundingMode.HALF_UP).longValue();
        double monthRevenueChange = lastMonthRevenue > 0
                ? ((double) (monthRevenue - lastMonthRevenue) / lastMonthRevenue) * 100
                : 0;

        // 活跃会话数（最近30分钟内有更新的会话）
        OffsetDateTime activeThreshold = OffsetDateTime.now(ZoneOffset.ofHours(8)).minusMinutes(30);
        long activeSessions = sessionMapper.selectCount(
                new LambdaQueryWrapper<Session>()
                        .eq(Session::getTenantId, tenantId)
                        .ge(Session::getUpdatedAt, activeThreshold));

        // AI 会话占比
        long aiSessions = sessionMapper.selectCount(
                new LambdaQueryWrapper<Session>()
                        .eq(Session::getTenantId, tenantId)
                        .ge(Session::getUpdatedAt, activeThreshold)
                        .eq(Session::getAiEnabled, true));
        double aiSessionRate = activeSessions > 0
                ? Math.round((double) aiSessions / activeSessions * 1000.0) / 10.0
                : 0;

        DashboardStatsResponse stats = DashboardStatsResponse.builder()
                .todayOrders(todayOrders)
                .todayOrdersChange(Math.round(todayOrdersChange * 10.0) / 10.0)
                .totalCustomers(totalCustomers)
                .newCustomersToday(newCustomersToday)
                .activeSessions(activeSessions)
                .aiSessionRate(aiSessionRate)
                .monthRevenue(monthRevenue)
                .monthRevenueChange(Math.round(monthRevenueChange * 10.0) / 10.0)
                .totalProducts(totalProducts)
                .totalOrders(totalOrders)
                .totalTickets(totalTickets)
                .build();

        return ApiResponse.success(stats);
    }

    // ========== 订单趋势 ==========

    @GetMapping("/order-trend")
    public ApiResponse<List<OrderTrendPointResponse>> getOrderTrend(
            @RequestParam(defaultValue = "7") int days) {
        Long tenantId = TenantContext.getTenantId();
        ZoneId cst = ZoneId.of("Asia/Shanghai");
        OffsetDateTime startDate = LocalDate.now(cst).minusDays(days - 1).atStartOfDay().atOffset(ZoneOffset.ofHours(8));

        List<Map<String, Object>> rawData = orderMapper.selectOrderTrend(tenantId, startDate);

        // 构建日期到数据的映射
        Map<String, Map<String, Object>> dataMap = new LinkedHashMap<>();
        for (Map<String, Object> row : rawData) {
            dataMap.put(row.get("date").toString(), row);
        }

        // 填充所有日期（含无数据日期）
        List<OrderTrendPointResponse> result = new ArrayList<>();
        for (int i = days - 1; i >= 0; i--) {
            String dateStr = LocalDate.now().minusDays(i).toString();
            Map<String, Object> row = dataMap.get(dateStr);
            result.add(OrderTrendPointResponse.builder()
                    .date(dateStr)
                    .orders(row != null ? ((Number) row.get("orders")).intValue() : 0)
                    .build());
        }

        return ApiResponse.success(result);
    }

    // ========== 订单状态分布 ==========

    private static final Map<String, String> STATUS_LABELS = Map.of(
            "pending", "待付款",
            "confirmed", "已确认",
            "producing", "生产中",
            "shipped", "已发货",
            "completed", "已完成",
            "cancelled", "已取消"
    );

    private static final Map<String, String> STATUS_COLORS = Map.of(
            "pending", "#faad14",
            "confirmed", "#2563eb",
            "producing", "#7c3aed",
            "shipped", "#06b6d4",
            "completed", "#16a34a",
            "cancelled", "#9ca3af"
    );

    @GetMapping("/order-status")
    public ApiResponse<List<OrderStatusResponse>> getOrderStatusDistribution() {
        Long tenantId = TenantContext.getTenantId();
        List<Map<String, Object>> rawData = orderMapper.selectOrderStatusDistribution(tenantId);

        List<OrderStatusResponse> result = rawData.stream().map(row -> {
            String status = (String) row.get("status");
            return OrderStatusResponse.builder()
                    .status(status)
                    .label(STATUS_LABELS.getOrDefault(status, status))
                    .count(((Number) row.get("count")).intValue())
                    .color(STATUS_COLORS.getOrDefault(status, "#9ca3af"))
                    .build();
        }).collect(Collectors.toList());

        return ApiResponse.success(result);
    }

    // ========== 最近订单 ==========

    @GetMapping("/recent-orders")
    public ApiResponse<List<RecentOrderResponse>> getRecentOrders(
            @RequestParam(defaultValue = "5") int limit) {
        Long tenantId = TenantContext.getTenantId();

        List<Order> orders = orderMapper.selectList(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getTenantId, tenantId)
                        .orderByDesc(Order::getCreatedAt)
                        .last("LIMIT " + limit));

        List<RecentOrderResponse> result = orders.stream().map(o ->
                RecentOrderResponse.builder()
                        .id(o.getId())
                        .orderNo(o.getOrderNo())
                        .customerName(o.getCustomerName())
                        .totalAmount(o.getTotalAmount())
                        .status(o.getStatus())
                        .createdAt(o.getCreatedAt() != null ? o.getCreatedAt().toString() : null)
                        .build()
        ).collect(Collectors.toList());

        return ApiResponse.success(result);
    }

    // ========== 活跃会话 ==========

    @GetMapping("/active-sessions")
    public ApiResponse<List<ActiveSessionResponse>> getActiveSessions(
            @RequestParam(defaultValue = "5") int limit) {
        Long tenantId = TenantContext.getTenantId();

        List<Session> sessions = sessionMapper.selectList(
                new LambdaQueryWrapper<Session>()
                        .eq(Session::getTenantId, tenantId)
                        .orderByDesc(Session::getUpdatedAt)
                        .last("LIMIT " + limit));

        List<ActiveSessionResponse> result = new ArrayList<>();
        for (Session s : sessions) {
            // 获取客户名称
            String customerName = "未知客户";
            if (s.getCustomerId() != null) {
                User customer = userMapper.selectById(s.getCustomerId());
                if (customer != null) {
                    customerName = customer.getNickname() != null ? customer.getNickname() : (customer.getPhone() != null ? customer.getPhone() : "未知客户");
                }
            }

            // 获取最后一条消息
            String lastMessage = "";
            List<SessionMessage> messages = sessionMessageMapper.selectList(
                    new LambdaQueryWrapper<SessionMessage>()
                            .eq(SessionMessage::getSessionId, s.getId())
                            .orderByDesc(SessionMessage::getCreatedAt)
                            .last("LIMIT 1"));
            if (!messages.isEmpty()) {
                lastMessage = messages.get(0).getContent();
            }

            // 计算持续时间
            String duration = "";
            if (s.getStartedAt() != null) {
                long minutes = java.time.Duration.between(s.getStartedAt(), OffsetDateTime.now(ZoneOffset.UTC)).toMinutes();
                duration = minutes + "分钟";
            }

            result.add(ActiveSessionResponse.builder()
                    .id(s.getId())
                    .customerName(customerName)
                    .channel(s.getChannel() != null ? s.getChannel() : "web")
                    .lastMessage(lastMessage)
                    .duration(duration)
                    .isAI(Boolean.TRUE.equals(s.getAiEnabled()))
                    .startedAt(s.getStartedAt() != null ? s.getStartedAt().toString() : null)
                    .build());
        }

        return ApiResponse.success(result);
    }

    // ========== Response DTOs ==========

    @Data
    @Builder
    public static class DashboardStatsResponse {
        private long todayOrders;
        private double todayOrdersChange;
        private long totalCustomers;
        private long newCustomersToday;
        private long activeSessions;
        private double aiSessionRate;
        private long monthRevenue;
        private double monthRevenueChange;
        private long totalProducts;
        private long totalOrders;
        private long totalTickets;
    }

    @Data
    @Builder
    public static class OrderTrendPointResponse {
        private String date;
        private int orders;
    }

    @Data
    @Builder
    public static class OrderStatusResponse {
        private String status;
        private String label;
        private int count;
        private String color;
    }

    @Data
    @Builder
    public static class RecentOrderResponse {
        private String id;
        private String orderNo;
        private String customerName;
        private BigDecimal totalAmount;
        private String status;
        private String createdAt;
    }

    @Data
    @Builder
    public static class ActiveSessionResponse {
        private String id;
        private String customerName;
        private String channel;
        private String lastMessage;
        private String duration;
        private boolean isAI;
        private String startedAt;
    }
}
