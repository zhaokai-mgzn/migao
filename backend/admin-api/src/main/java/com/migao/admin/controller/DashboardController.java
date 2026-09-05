package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.*;
import com.migao.admin.mapper.*;
import com.migao.admin.service.ProductService;
import com.migao.admin.security.RequirePermission;
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
@RequirePermission("dashboard:view")
@RestController
@RequestMapping("/api/admin/dashboard")
@RequiredArgsConstructor
public class DashboardController {

    private final ProductMapper productMapper;
    private final OrderMapper orderMapper;
    private final UserMapper userMapper;
    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final SessionMapper sessionMapper;
    private final OrderItemMapper orderItemMapper;
    private final SessionMessageMapper sessionMessageMapper;
    private final ProductSkuMapper productSkuMapper;
    private final ProductService productService;

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
        OffsetDateTime tomorrowStart = todayStart.plusDays(1);
        OffsetDateTime yesterdayStart = todayStart.minusDays(1);
        OffsetDateTime monthStart = LocalDate.now(cst).withDayOfMonth(1).atStartOfDay().atOffset(ZoneOffset.ofHours(8));
        OffsetDateTime lastMonthStart = monthStart.minusMonths(1);

        // #2886 性能优化：订单维度原来 8 次串行 selectCount/selectList → 1 次 SQL FILTER 聚合
        Map<String, Object> orderStats = orderMapper.selectDashboardOrderStats(
                todayStart, tomorrowStart, yesterdayStart, monthStart, lastMonthStart);
        long totalOrders = toLong(orderStats.get("total_orders"));

        // 今日/昨日订单数与销售额（环比）
        long todayOrders = toLong(orderStats.get("today_orders"));
        long yesterdayOrders = toLong(orderStats.get("yesterday_orders"));
        double todayOrdersChange = yesterdayOrders > 0
                ? ((double) (todayOrders - yesterdayOrders) / yesterdayOrders) * 100
                : 0;
        long todaySales = toLong(orderStats.get("today_sales"));
        long yesterdaySales = toLong(orderStats.get("yesterday_sales"));
        double todaySalesChange = yesterdaySales > 0
                ? ((double) (todaySales - yesterdaySales) / yesterdaySales) * 100 : 0;

        // 本月/上月营收（环比）
        long monthRevenue = toLong(orderStats.get("month_revenue"));
        long lastMonthRevenue = toLong(orderStats.get("last_month_revenue"));
        double monthRevenueChange = lastMonthRevenue > 0
                ? ((double) (monthRevenue - lastMonthRevenue) / lastMonthRevenue) * 100
                : 0;

        // #2886：客户维度 2 次串行 count → 1 次 FILTER 聚合
        Map<String, Object> userStats = userMapper.selectDashboardUserStats(todayStart);
        long totalCustomers = toLong(userStats.get("total_customers"));
        long newCustomersToday = toLong(userStats.get("new_customers_today"));

        // 售后工单数
        long totalTickets = afterSalesTicketMapper.selectCount(
                new LambdaQueryWrapper<AfterSalesTicket>()
                        .eq(AfterSalesTicket::getTenantId, tenantId));

        // #2886：活跃会话/AI 会话 2 次串行 count → 1 次 FILTER 聚合
        OffsetDateTime activeThreshold = OffsetDateTime.now(ZoneOffset.ofHours(8)).minusMinutes(30);
        Map<String, Object> sessionStats = sessionMapper.selectDashboardSessionStats(activeThreshold);
        long activeSessions = toLong(sessionStats.get("active_sessions"));
        long aiSessions = toLong(sessionStats.get("ai_sessions"));
        double aiSessionRate = activeSessions > 0
                ? Math.round((double) aiSessions / activeSessions * 1000.0) / 10.0
                : 0;

        // ════════════════════════════════════════
        // 待处理区 3 卡片（#387）
        // ════════════════════════════════════════

        // 待发货订单数（status = 待发货）
        long pendingShipOrders = toLong(orderStats.get("pending_ship"));

        // 含加工待发货订单：#2886 原「全量待发货 ID 拉取 + order_items IN 两次往返」→ JOIN 一次统计
        long processingPendingOrders = orderItemMapper.selectProcessingPendingOrdersCount();

        // 待补库存商品：SKU 库存 ≤ 100（按颜色规格维度）
        // #1396: 口径统一 — 使用 ProductService 统一方法，排除已删除 + 已下架商品下的 SKU
        long lowStockItems = productService.getLowStockSkuCount(tenantId, 100);

        // 商品总数
        long totalProducts = productMapper.selectCount(
                new LambdaQueryWrapper<Product>().eq(Product::getTenantId, tenantId));

        DashboardStatsResponse stats = DashboardStatsResponse.builder()
                .todayOrders(todayOrders)
                .todayOrdersChange(Math.round(todayOrdersChange * 10.0) / 10.0)
                .todaySales(todaySales)
                .todaySalesChange(Math.round(todaySalesChange * 10.0) / 10.0)
                .totalCustomers(totalCustomers)
                .newCustomersToday(newCustomersToday)
                .activeSessions(activeSessions)
                .aiSessionRate(aiSessionRate)
                .monthRevenue(monthRevenue)
                .monthRevenueChange(Math.round(monthRevenueChange * 10.0) / 10.0)
                .totalProducts(totalProducts)
                .totalOrders(totalOrders)
                .totalTickets(totalTickets)
                .pendingShipOrders(pendingShipOrders)
                .processingPendingOrders(processingPendingOrders)
                .lowStockItems(lowStockItems)
                .build();

        return ApiResponse.success(stats);
    }

    /** 聚合结果数值转换：BigDecimal 按原有 setScale(HALF_UP) 口径舍入，避免 decimal 截断 */
    private static long toLong(Object v) {
        if (v == null) {
            return 0L;
        }
        if (v instanceof BigDecimal bd) {
            return bd.setScale(0, java.math.RoundingMode.HALF_UP).longValue();
        }
        if (v instanceof Number n) {
            return n.longValue();
        }
        return Long.parseLong(v.toString());
    }

    // ========== 订单趋势 ==========

    @GetMapping("/order-trend")
    public ApiResponse<List<OrderTrendPointResponse>> getOrderTrend(
            @RequestParam(defaultValue = "7") int days) {
        ZoneId cst = ZoneId.of("Asia/Shanghai");
        OffsetDateTime startDate = LocalDate.now(cst).minusDays(days - 1).atStartOfDay().atOffset(ZoneOffset.ofHours(8));

        List<Map<String, Object>> rawData = orderMapper.selectOrderTrend(startDate);

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
            long amount = row != null && row.get("amount") != null
                    ? ((Number) row.get("amount")).longValue() : 0L;
            result.add(OrderTrendPointResponse.builder()
                    .date(dateStr)
                    .orders(row != null ? ((Number) row.get("orders")).intValue() : 0)
                    .amount(amount)
                    .build());
        }

        return ApiResponse.success(result);
    }

    // ========== 订单状态分布 ==========

    // 真实订单状态 → 中文标签（与 OrderService 状态机 pending/confirmed/producing/shipped/completed/cancelled 对齐）
    private static final Map<String, String> STATUS_LABELS = Map.of(
            "pending", "待付款",
            "confirmed", "待发货",
            "producing", "生产中",
            "shipped", "已发货",
            "completed", "已完成",
            "cancelled", "已取消"
    );

    private static final Map<String, String> STATUS_COLORS = Map.of(
            "pending", "#faad14",
            "confirmed", "#2563eb",
            "producing", "#8b5cf6",
            "shipped", "#06b6d4",
            "completed", "#16a34a",
            "cancelled", "#9ca3af"
    );

    @GetMapping("/order-status")
    public ApiResponse<List<OrderStatusResponse>> getOrderStatusDistribution() {
        List<Map<String, Object>> rawData = orderMapper.selectOrderStatusDistribution();

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

        // #2886 性能优化：客户信息 IN 批量一次（替代原来每会话一次 selectById）
        Set<String> customerIds = sessions.stream()
                .map(Session::getCustomerId)
                .filter(Objects::nonNull)
                .collect(Collectors.toSet());
        Map<String, User> userMap = customerIds.isEmpty() ? Collections.emptyMap()
                : userMapper.selectBatchIds(customerIds).stream()
                        .collect(Collectors.toMap(User::getId, u -> u));

        // #2886 性能优化：最后一条消息 DISTINCT ON 批量一次（替代原来每会话一次 LIMIT 1）
        List<String> sessionIds = sessions.stream().map(Session::getId).collect(Collectors.toList());
        Map<String, String> lastMessageMap = new HashMap<>();
        if (!sessionIds.isEmpty()) {
            for (Map<String, Object> row : sessionMessageMapper.selectLastMessageBySessionIds(sessionIds)) {
                lastMessageMap.put((String) row.get("session_id"), (String) row.get("content"));
            }
        }

        List<ActiveSessionResponse> result = new ArrayList<>();
        for (Session s : sessions) {
            // 获取客户名称
            String customerName = "未知客户";
            if (s.getCustomerId() != null) {
                User customer = userMap.get(s.getCustomerId());
                if (customer != null) {
                    customerName = customer.getNickname() != null ? customer.getNickname() : (customer.getPhone() != null ? customer.getPhone() : "未知客户");
                }
            }

            // 获取最后一条消息
            String lastMessage = lastMessageMap.getOrDefault(s.getId(), "");

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

    // ========== 待处理任务 ==========

    @GetMapping("/pending-tasks")
    public ApiResponse<List<PendingTaskResponse>> getPendingTasks() {
        Long tenantId = TenantContext.getTenantId();

        List<PendingTaskResponse> tasks = new ArrayList<>();

        // 待支付订单
        List<Order> pendingOrders = orderMapper.selectList(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getTenantId, tenantId)
                        .eq(Order::getStatus, "pending")
                        .orderByDesc(Order::getCreatedAt)
                        .last("LIMIT 5"));
        for (Order o : pendingOrders) {
            tasks.add(PendingTaskResponse.builder()
                    .id(String.valueOf(o.getId()))
                    .type("order")
                    .title("订单 " + (o.getOrderNo() != null ? o.getOrderNo() : o.getId()) + " 待支付")
                    .priority("high")
                    .createdAt(o.getCreatedAt() != null ? o.getCreatedAt().toString() : null)
                    .link("/orders/" + o.getId())
                    .build());
        }

        // 待处理售后工单
        List<AfterSalesTicket> openTickets = afterSalesTicketMapper.selectList(
                new LambdaQueryWrapper<AfterSalesTicket>()
                        .eq(AfterSalesTicket::getTenantId, tenantId)
                        .eq(AfterSalesTicket::getStatus, "open")
                        .orderByDesc(AfterSalesTicket::getCreatedAt)
                        .last("LIMIT 5"));
        for (AfterSalesTicket t : openTickets) {
            tasks.add(PendingTaskResponse.builder()
                    .id(String.valueOf(t.getId()))
                    .type("after_sales")
                    .title("售后工单 " + (t.getTicketNo() != null ? t.getTicketNo() : t.getId()) + " 待处理")
                    .priority("medium")
                    .createdAt(t.getCreatedAt() != null ? t.getCreatedAt().toString() : null)
                    .link("/after-sales/" + t.getId())
                    .build());
        }

        // 按创建时间倒序
        tasks.sort((a, b) -> {
            if (a.getCreatedAt() == null) return 1;
            if (b.getCreatedAt() == null) return -1;
            return b.getCreatedAt().compareTo(a.getCreatedAt());
        });

        return ApiResponse.success(tasks);
    }


    // ════════════════════════════════════════
    // 商品销量排行（按订单明细聚合）
    // ════════════════════════════════════════

    @GetMapping("/product-ranking")
    public ApiResponse<List<ProductRankingResponse>> getProductRanking(
            @RequestParam(defaultValue = "day") String period,
            @RequestParam(defaultValue = "10") int limit) {
        ZoneId cst = ZoneId.of("Asia/Shanghai");
        // day: 近7天; month: 近30天（避免当天0点无数据导致"暂无数据"）
        OffsetDateTime periodStart = "month".equals(period)
                ? LocalDate.now(cst).minusDays(30).atStartOfDay().atOffset(ZoneOffset.ofHours(8))
                : LocalDate.now(cst).minusDays(7).atStartOfDay().atOffset(ZoneOffset.ofHours(8));
        OffsetDateTime prevStart = "month".equals(period) ? periodStart.minusDays(30) : periodStart.minusDays(7);

        // #2886 性能优化：本周期聚合一次 SQL（替代原来全量明细拉到 JVM 分组排序 + 每商品一次上期查询）
        List<Map<String, Object>> rankingRows = orderItemMapper.selectProductRanking(periodStart, limit);

        // 上期销量：topN 产品 IN 批量一次
        List<String> productIds = rankingRows.stream()
                .map(r -> (String) r.get("product_id"))
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
        Map<String, Long> prevQtyMap = new HashMap<>();
        if (!productIds.isEmpty()) {
            for (Map<String, Object> row : orderItemMapper.selectPrevPeriodQuantities(productIds, prevStart, periodStart)) {
                prevQtyMap.put((String) row.get("product_id"), ((Number) row.get("qty")).longValue());
            }
        }

        List<ProductRankingResponse> result = new ArrayList<>();
        int rank = 1;
        for (Map<String, Object> row : rankingRows) {
            String pid = (String) row.get("product_id");
            long qty = ((Number) row.get("qty")).longValue();
            long amt = ((Number) row.get("amt")).longValue();
            long prevQty = prevQtyMap.getOrDefault(pid, 0L);
            double dc = prevQty > 0 ? ((double) (qty - prevQty) / prevQty) * 100 : 0;
            result.add(ProductRankingResponse.builder().rank(rank++).productId(pid)
                    .productName((String) row.get("product_name")).salesQty(qty).salesAmount(amt)
                    .qtyDisplay(qty >= 10000 ? String.format("%.1fw", qty / 10000.0) : String.valueOf(qty))
                    .amountDisplay(amt >= 10000 ? String.format("%.1fw", amt / 10000.0) : String.valueOf(amt))
                    .dailyChange(Math.round(dc * 10.0) / 10.0).build());
        }
        return ApiResponse.success(result);
    }

    /**
     * 待发货订单数（status = 待发货）
     */
    @GetMapping("/pending-shipment-count")
    public ApiResponse<Long> getPendingShipmentCount() {
        Long tenantId = TenantContext.getTenantId();
        long count = orderMapper.selectCount(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getTenantId, tenantId)
                        .in(Order::getStatus, "confirmed", "producing"));
        return ApiResponse.success(count);
    }

    /**
     * 含加工待发货订单数（status = 待发货，has_processing 过滤待 DB 加列后启用）
     */
    @GetMapping("/processing-shipment-count")
    public ApiResponse<Long> getProcessingShipmentCount() {
        Long tenantId = TenantContext.getTenantId();
        long count = orderMapper.selectCount(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getTenantId, tenantId)
                        .in(Order::getStatus, "confirmed", "producing"));
        // TODO: 等 orders 表加 has_processing 列后加 .eq(Order::getHasProcessing, true)
        return ApiResponse.success(count);
    }

    // ========== Response DTOs ==========

    @Data
    @Builder
    public static class DashboardStatsResponse {
        private long todayOrders;
        private double todayOrdersChange;
        private long todaySales;
        private double todaySalesChange;        private long totalCustomers;
        private long newCustomersToday;
        private long activeSessions;
        private double aiSessionRate;
        private long monthRevenue;
        private double monthRevenueChange;
        private long totalProducts;
        private long totalOrders;
        private long totalTickets;
        // 待处理区 3 卡片 (#387)
        private long pendingShipOrders;
        private long processingPendingOrders;
        private long lowStockItems;
    }

    @Data
    @Builder
    public static class OrderTrendPointResponse {
        private String date;
        private int orders;
        private long amount;
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

    @Data
    @Builder
    public static class PendingTaskResponse {
        private String id;
        private String type;       // "order" | "after_sales"
        private String title;
        private String priority;   // "high" | "medium" | "low"
        private String createdAt;
        private String link;
    }

    @Data
    @Builder
    public static class ProductRankingResponse {
        private int rank;
        private String productId;
        private String productName;
        private long salesQty;
        private long salesAmount;
        private String qtyDisplay;
        private String amountDisplay;
        private double dailyChange;
    }
}
