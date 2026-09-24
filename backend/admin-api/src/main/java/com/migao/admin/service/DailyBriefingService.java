package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.*;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/**
 * 智能每日经营简报服务（issue #3468，设计文档 docs/design/daily-briefing-design.md v0.2）
 *
 * 核心职责：
 * 1. 聚合经营指标快照（复用看板聚合 SQL，纯数字 + 脱敏事实，无客户 PII）；
 * 2. 调 ai-agent LLM 生成四区块简报（昨日回顾/今日必办/风险预警/优化建议）；
 * 3. 数字回填校验（红线 4）：LLM 输出每条目的 metrics 引用与快照对账，不一致丢弃；
 * 4. 落库 daily_briefings（tenant_id + biz_date 唯一，RLS 隔离）；
 * 5. 企业开关读写（红线 3：关闭 = 不生成 + LLM 熔断）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DailyBriefingService {

    private final DailyBriefingMapper dailyBriefingMapper;
    private final TenantMapper tenantMapper;
    private final OrderMapper orderMapper;
    private final UserMapper userMapper;
    private final SessionMapper sessionMapper;
    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final OrderItemMapper orderItemMapper;
    private final OrderLogisticsMapper orderLogisticsMapper;
    private final ProductSkuMapper productSkuMapper;
    private final ProductMapper productMapper;
    private final ProductService productService;
    private final BriefingGenerateClient briefingGenerateClient;
    private final ObjectMapper objectMapper;
    private final StringRedisTemplate redisTemplate;

    /** 数字对账容差：metrics value 与快照值之差绝对值 ≤ 容差即视为一致（浮点/舍入） */
    private static final double METRIC_TOLERANCE = 0.001;

    /**
     * 业务时区（简报"今日"口径）：包级可见，供同包测试断言复用同一常量，
     * 避免测试另写一份 "Asia/Shanghai" 造成两处漂移（issue #3796）。
     */
    static final ZoneId CST = ZoneId.of("Asia/Shanghai");
    private static final ZoneOffset CST_OFFSET = ZoneOffset.ofHours(8);

    /**
     * 分布式生成锁 TTL（秒，issue #3957）：覆盖一次完整 LLM 生成耗时；
     * 实例崩溃后锁自动到期放行，DB 唯一键 (tenant_id, biz_date) 兜底防重复记录。
     * 包级可见，供同包测试断言锁 TTL 与实现同源。
     */
    static final long BRIEFING_LOCK_TTL_SECONDS = 600L;

    // ==================== 行级快照（族 3 跨域视图内核，issue #5358）====================

    /**
     * 行级数组的**行数上限**：有界，不得全表拖（截断方向刻意取「最该看的那一头」——
     * 订单按 `created_at` 升序 = 最久未发优先；SKU 按 `stock` 升序 = 最缺货优先；退货按时间倒序 = 最近优先）。
     * 500 行 ≫ 单租户单日的待发货单 / 库存告急 SKU / 退货量级。
     */
    static final int SNAPSHOT_ROW_LIMIT = 500;

    /**
     * 行数组的**取数**上限 = {@link #SNAPSHOT_ROW_LIMIT} + 1：多取一行只为**判定是否被截断**
     * （多出来的那行不进快照）。
     *
     * <p>🔴 为什么要判定：有界是热路径必须的，但**静默截断会新开一个少报面** —— 看不见的行不会命中 ⇒
     * 「没发现」被读成「没问题」，正是本单要治的形态（#5348）。截断事实经 `row_meta` 显式交给引擎，
     * 由引擎落成规则的 `incomplete` 状态（空命中不得读成没问题）。</p>
     */
    static final int SNAPSHOT_ROW_FETCH_LIMIT = SNAPSHOT_ROW_LIMIT + 1;

    /** 退货行窗口（天）：覆盖连续退货规则的观察窗口（默认 7 天）并留足余量。 */
    static final int SNAPSHOT_RETURN_WINDOW_DAYS = 90;

    /** 库存告急口径（与 `dashboard-jump.low-stock` 同源：库存 ≤ 100）—— 计数与行数组共用一份，避免两处口径。 */
    static final int LOW_STOCK_THRESHOLD = 100;

    /** 「该发货而未发货」的订单状态 —— 与聚合指标 `pending_ship_orders` 同一口径。 */
    static final List<String> UNSHIPPED_STATUSES = List.of("confirmed", "producing");

    /** 退货事实的来源：售后工单里的**退货**类型（全仓无独立退货流水表）。 */
    static final String RETURN_TICKET_TYPE = "return";

    /**
     * 快照行数组的**自描述**：本次装配真的给出了哪些行数组、每个数组有哪些字段。
     *
     * <p>引擎（`app/briefing/proactive.py::proactive_status`）拿它 × 每条规则的输入契约算
     * **逐规则接线状态** ——「没数据」与「没问题」的分界就在这里，两侧各只有一份声明。</p>
     *
     * <p>`orders` 行的 `cost_amount`（issue #5348，2026-09-24 接通）：**Σ(行数量 × 该行 SKU 的
     * `avg_cost`)** —— 成本不在 `orders` 表上，而在 `product_skus.avg_cost`（移动加权）。逐行解析
     * SKU（① `order_items.processing_info.skuId` → ② 该商品**唯一** SKU → ③ 不可解析）；
     * 🔴 **任一行不可判定 ⇒ 该订单行 `cost_amount = NULL`**（整单不可判定，**不出部分和**）。
     * `NULL` = **成本未知**，不是「成本为 0」（沿用 `avg_cost` 既有口径：不猜 0）。</p>
     *
     * <p>🔴 **刻意缺席**（如实登记为「未接线」，**不是「命中 0 条」**）：`price_changes`
     * **整个数组不装配** —— 全仓无改价流水表 ⇒ 改价幅度规则接不通（另立 issue）。</p>
     */
    static final Map<String, List<String>> SNAPSHOT_ROW_FIELDS = snapshotRowFields();

    private static Map<String, List<String>> snapshotRowFields() {
        Map<String, List<String>> fields = new LinkedHashMap<>();
        fields.put("orders", List.of("order_no", "status", "customer_id", "created_at",
                "shipped_at", "sale_amount", "cost_amount"));
        fields.put("skus", List.of("sku_id", "product_id", "product_name", "stock"));
        fields.put("returns", List.of("return_no", "customer_id", "product_id", "returned_at", "amount"));
        return fields;
    }

    /** 一批快照行 + 它**是否被行数上限截断**（截断必须显式：见 {@link #SNAPSHOT_ROW_FETCH_LIMIT}）。 */
    record RowBatch(List<Map<String, Object>> rows, boolean truncated) {
    }

    /** 行数组的元信息（`row_meta`）：行数上限 / 实际行数 / 是否被截断 —— 引擎据此把「本次不完整」说出来。 */
    static Map<String, Object> rowMeta(RowBatch orders, RowBatch skus, RowBatch returns) {
        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("orders", rowMetaEntry(orders));
        meta.put("skus", rowMetaEntry(skus));
        meta.put("returns", rowMetaEntry(returns));
        return meta;
    }

    private static Map<String, Object> rowMetaEntry(RowBatch batch) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("limit", SNAPSHOT_ROW_LIMIT);
        entry.put("count", batch.rows().size());
        entry.put("truncated", batch.truncated());
        return entry;
    }

    // ==================== 企业开关（红线 3）====================

    /**
     * 读取简报配置（开关 + 生成时刻）
     */
    public Map<String, Object> getConfig(Long tenantId) {
        Tenant tenant = tenantMapper.selectById(tenantId);
        if (tenant == null) {
            throw BusinessException.notFound("租户");
        }
        Map<String, Object> config = new HashMap<>();
        config.put("enabled", Boolean.TRUE.equals(tenant.getBriefingEnabled()));
        config.put("generateTime", StringUtils.hasText(tenant.getBriefingGenerateTime())
                ? tenant.getBriefingGenerateTime() : "06:00");
        return config;
    }

    /**
     * 更新简报配置。开启瞬间立即生成当日简报（不等次日定时）；
     * 关闭即熔断（调度跳过 + 生成入口拦截）。
     */
    @Transactional
    public Map<String, Object> updateConfig(Long tenantId, boolean enabled, String generateTime) {
        Tenant tenant = tenantMapper.selectById(tenantId);
        if (tenant == null) {
            throw BusinessException.notFound("租户");
        }
        // 生成时刻格式校验 HH:mm
        if (StringUtils.hasText(generateTime) && !generateTime.matches("^([01]\\d|2[0-3]):[0-5]\\d$")) {
            throw new BusinessException("VALIDATION_ERROR", "生成时刻格式不正确，应为 HH:mm", 422);
        }
        tenant.setBriefingEnabled(enabled);
        if (StringUtils.hasText(generateTime)) {
            tenant.setBriefingGenerateTime(generateTime);
        }
        tenantMapper.updateById(tenant);
        log.info("更新简报配置 tenantId={} enabled={} generateTime={}", tenantId, enabled, generateTime);

        // 开启瞬间立即生成当日简报（设计文档 §2.3：让管理员当天就看到效果）
        if (enabled) {
            try {
                generateForTenant(tenantId);
            } catch (Exception e) {
                log.warn("开启简报后立即生成失败 tenantId={}: {}", tenantId, e.getMessage());
            }
        }
        return getConfig(tenantId);
    }

    // ==================== 简报查询 ====================

    /**
     * 查询今日简报（未生成返回 null，前端展示引导空态）
     */
    public DailyBriefing getTodayBriefing(Long tenantId) {
        return getBriefingByDate(tenantId, LocalDate.now(CST));
    }

    /**
     * 查询指定日期简报
     */
    public DailyBriefing getBriefingByDate(Long tenantId, LocalDate bizDate) {
        return dailyBriefingMapper.selectOne(
                new LambdaQueryWrapper<DailyBriefing>()
                        .eq(DailyBriefing::getTenantId, tenantId)
                        .eq(DailyBriefing::getBizDate, bizDate)
                        .last("LIMIT 1"));
    }

    // ==================== 生成流程 ====================

    /**
     * 为租户生成当日简报（定时任务/手动触发/开启瞬间共用）。
     * 开关关闭 → 直接返回 null（熔断）；生成失败 → 落 failed 记录（不展示假数据）。
     *
     * 分布式集群安全（issue #3957）：多实例同时调度/手动触发时，同一租户同一天
     * 只允许一个实例执行生成——Redis SET NX EX 锁（key=租户×业务日期）；
     * DB 唯一键 (tenant_id, biz_date) 兜底，Redis 不可用 fail-open 放行不阻断简报。
     */
    @Transactional
    public DailyBriefing generateForTenant(Long tenantId) {
        Tenant tenant = tenantMapper.selectById(tenantId);
        if (tenant == null) {
            log.warn("简报生成跳过：租户不存在 tenantId={}", tenantId);
            return null;
        }
        // 红线 3：开关即熔断
        if (!Boolean.TRUE.equals(tenant.getBriefingEnabled())) {
            log.info("简报生成跳过：租户未开启 tenantId={}", tenantId);
            return null;
        }

        String lockKey = "briefing:gen:" + tenantId + ":" + LocalDate.now(CST);
        boolean locked = tryAcquireGenerationLock(lockKey);
        if (!locked) {
            log.info("简报生成跳过：另一实例正在生成或当日已生成 tenantId={}", tenantId);
            return null;
        }
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            // 锁的生命周期须盖过受保护写入（daily_briefings insert 随事务提交）：
            // 事务提交/回滚完成后再释放锁，否则「先放锁、后提交」窗口内另一实例
            // 读不到记录会重复生成（issue #3957 集群互斥语义）。
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCompletion(int status) {
                    releaseGenerationLock(lockKey);
                }
            });
        } else {
            // 无事务上下文（单测等）→ 立即释放，DB 唯一键兜底
            releaseGenerationLock(lockKey);
        }
        // 定时任务线程无 JWT Filter，聚合 SQL / 落库依赖 TenantContext 注入租户
        // （TenantLineInnerInterceptor 从 TenantContext 取 tenant_id），须显式设置。
        Long previousTenantId = TenantContext.getTenantId();
        TenantContext.setTenantId(tenantId);
        try {
            return doGenerate(tenantId);
        } finally {
            if (previousTenantId != null) {
                TenantContext.setTenantId(previousTenantId);
            } else {
                TenantContext.clear();
            }
        }
    }

    /** 获取当日生成锁（SET NX EX）。Redis 不可用 → fail-open 返回 true（DB 唯一键兜底）。 */
    private boolean tryAcquireGenerationLock(String lockKey) {
        try {
            return Boolean.TRUE.equals(redisTemplate.opsForValue()
                    .setIfAbsent(lockKey, "1", BRIEFING_LOCK_TTL_SECONDS, TimeUnit.SECONDS));
        } catch (Exception e) {
            log.warn("简报生成锁不可用（Redis 异常），fail-open 放行: {}", e.getMessage());
            return true;
        }
    }

    /** 释放生成锁。Redis 异常仅告警（TTL 兜底自动放行）。 */
    private void releaseGenerationLock(String lockKey) {
        try {
            redisTemplate.delete(lockKey);
        } catch (Exception e) {
            log.warn("简报生成锁释放失败（Redis 异常，TTL 兜底）: {}", e.getMessage());
        }
    }

    /** generateForTenant 的实际逻辑（TenantContext 已就绪） */
    private DailyBriefing doGenerate(Long tenantId) {
        LocalDate today = LocalDate.now(CST);
        // 当日已生成 → 幂等跳过（唯一键 (tenant_id, biz_date) 兜底）
        DailyBriefing existing = getBriefingByDate(tenantId, today);
        if (existing != null) {
            return existing;
        }

        // 1) 聚合快照（确定性层）
        Map<String, Object> snapshot = aggregateSnapshot(tenantId);
        Map<String, Number> metrics = extractMetrics(snapshot);

        // 2) LLM 组织层
        // 🔴 提示词只喂**聚合指标 + 脱敏事实**：行级数组是规则引擎 / 按需视图的输入（族 3），
        // 不进 LLM 上下文 —— 否则每条简报都要把上千行 JSON 塞进去（ai-agent 侧虽有 6000 字符预算，
        // 那也只会把它截成半截 JSON：既涨成本，又给模型一堆与组织简报无关的行）。
        JsonNode briefing = briefingGenerateClient.generate(tenantId, promptSnapshot(snapshot));

        DailyBriefing record = DailyBriefing.builder()
                .tenantId(tenantId)
                .bizDate(today)
                .sourceSnapshot(snapshot)
                .generatedAt(OffsetDateTime.now())
                .build();

        if (briefing == null) {
            // 红线 4：LLM 失败不展示假数据，落 failed 记录
            record.setContent(Map.of());
            record.setVerifyStatus("failed");
            dailyBriefingMapper.insert(record);
            log.warn("简报生成失败（LLM 不可用/降级）tenantId={}", tenantId);
            return record;
        }

        // 3) 数字回填校验层（红线 4）：逐条对账，不一致丢弃
        VerifyResult vr = verifyAndFilter(briefing, metrics);
        record.setContent(vr.content);
        record.setVerifyStatus(vr.status);
        dailyBriefingMapper.insert(record);
        log.info("简报生成完成 tenantId={} status={} todo={} risks={} suggestions={}",
                tenantId, vr.status, vr.todoKept, vr.risksKept, vr.suggestionsKept);
        return record;
    }

    // ==================== 聚合快照（确定性层）====================

    /**
     * 聚合经营指标快照：纯数字 + 脱敏事实（工单号/订单号），无客户 PII。
     * 复用看板聚合 SQL（selectDashboardOrderStats 等，租户由拦截器注入）。
     */
    Map<String, Object> aggregateSnapshot(Long tenantId) {
        OffsetDateTime todayStart = LocalDate.now(CST).atStartOfDay().atOffset(CST_OFFSET);
        OffsetDateTime tomorrowStart = todayStart.plusDays(1);
        OffsetDateTime yesterdayStart = todayStart.minusDays(1);
        OffsetDateTime monthStart = LocalDate.now(CST).withDayOfMonth(1).atStartOfDay().atOffset(CST_OFFSET);
        OffsetDateTime lastMonthStart = monthStart.minusMonths(1);

        Map<String, Object> orderStats = orderMapper.selectDashboardOrderStats(
                todayStart, tomorrowStart, yesterdayStart, monthStart, lastMonthStart);
        Map<String, Object> userStats = userMapper.selectDashboardUserStats(todayStart);
        OffsetDateTime activeThreshold = OffsetDateTime.now(CST_OFFSET).minusMinutes(30);
        Map<String, Object> sessionStats = sessionMapper.selectDashboardSessionStats(activeThreshold);

        long pendingShip = toLong(orderStats.get("pending_ship"));
        long lowStock = productService.getLowStockSkuCount(tenantId, LOW_STOCK_THRESHOLD);
        long processingPending = orderItemMapper.selectProcessingPendingOrdersCount();
        long totalTickets = afterSalesTicketMapper.selectCount(
                new LambdaQueryWrapper<AfterSalesTicket>()
                        .eq(AfterSalesTicket::getTenantId, tenantId));
        // 待处理工单（pending）+ 超时工单（pending/processing 且 deadline 已过）
        long pendingTickets = afterSalesTicketMapper.selectCount(
                new LambdaQueryWrapper<AfterSalesTicket>()
                        .eq(AfterSalesTicket::getTenantId, tenantId)
                        .eq(AfterSalesTicket::getStatus, "pending"));
        long overdueTickets = afterSalesTicketMapper.selectCount(
                new LambdaQueryWrapper<AfterSalesTicket>()
                        .eq(AfterSalesTicket::getTenantId, tenantId)
                        .in(AfterSalesTicket::getStatus, "pending", "processing")
                        .isNotNull(AfterSalesTicket::getDeadline)
                        .lt(AfterSalesTicket::getDeadline, OffsetDateTime.now()));

        Map<String, Number> metrics = new LinkedHashMap<>();
        metrics.put("today_orders", toLong(orderStats.get("today_orders")));
        metrics.put("yesterday_orders", toLong(orderStats.get("yesterday_orders")));
        metrics.put("today_sales", toLong(orderStats.get("today_sales")));
        metrics.put("yesterday_sales", toLong(orderStats.get("yesterday_sales")));
        metrics.put("month_revenue", toLong(orderStats.get("month_revenue")));
        metrics.put("last_month_revenue", toLong(orderStats.get("last_month_revenue")));
        metrics.put("pending_ship_orders", pendingShip);
        metrics.put("processing_pending_orders", processingPending);
        metrics.put("low_stock_items", lowStock);
        metrics.put("total_tickets", totalTickets);
        metrics.put("pending_tickets", pendingTickets);
        metrics.put("overdue_tickets", overdueTickets);
        metrics.put("active_sessions", toLong(sessionStats.get("active_sessions")));
        metrics.put("ai_sessions", toLong(sessionStats.get("ai_sessions")));
        metrics.put("total_customers", toLong(userStats.get("total_customers")));
        metrics.put("new_customers_today", toLong(userStats.get("new_customers_today")));
        // 衍生指标（确定性计算，非 LLM 编造）
        double todayOrders = metrics.get("today_orders").doubleValue();
        double yesterdayOrders = metrics.get("yesterday_orders").doubleValue();
        metrics.put("orders_change_pct", yesterdayOrders > 0
                ? Math.round((todayOrders - yesterdayOrders) / yesterdayOrders * 1000.0) / 10.0 : 0.0);
        double activeSessions = metrics.get("active_sessions").doubleValue();
        double aiSessions = metrics.get("ai_sessions").doubleValue();
        metrics.put("ai_session_rate_pct", activeSessions > 0
                ? Math.round(aiSessions / activeSessions * 1000.0) / 10.0 : 0.0);

        // 脱敏事实条目（业务标识，无客户信息）
        List<Map<String, Object>> facts = new ArrayList<>();
        if (pendingShip > 0) {
            facts.add(Map.of("type", "order", "title", pendingShip + " 个订单待发货",
                    "link", "/orders?status=待发货"));
        }
        if (processingPending > 0) {
            facts.add(Map.of("type", "order", "title", processingPending + " 个含加工订单待发货",
                    "link", "/orders?category=含加工订单&status=待发货"));
        }
        if (lowStock > 0) {
            facts.add(Map.of("type", "product", "title", lowStock + " 个商品库存偏低",
                    "link", "/products?low_stock=true"));
        }
        if (overdueTickets > 0) {
            facts.add(Map.of("type", "ticket", "title", overdueTickets + " 个售后工单已超时",
                    "link", "/after-sales"));
        } else if (pendingTickets > 0) {
            facts.add(Map.of("type", "ticket", "title", pendingTickets + " 个售后工单待处理",
                    "link", "/after-sales"));
        }

        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("metrics", metrics);
        snapshot.put("facts", facts);
        // 行级数组（族 3 跨域视图内核，issue #5358）：有界 + 租户隔离（显式带 tenantId，
        // 叠加 TenantLineInnerInterceptor 的 tenant_id 注入 —— 与既有工单查询同口径）。
        // 🔴 `price_changes` **不装配**（全仓无改价流水表）⇒ 该数组不存在，见 SNAPSHOT_ROW_FIELDS。
        RowBatch orders = assembleOrderRows(tenantId);
        RowBatch skus = assembleSkuRows(tenantId);
        RowBatch returns = assembleReturnRows(tenantId, todayStart.minusDays(SNAPSHOT_RETURN_WINDOW_DAYS));
        snapshot.put("row_fields", SNAPSHOT_ROW_FIELDS);
        // 截断必须显式（`row_meta`）：有界不许变成静默少报 —— 看不见的行不命中，会被读成「没问题」。
        snapshot.put("row_meta", rowMeta(orders, skus, returns));
        // 租户级**事实**（issue #5348）：该租户是否在做成本核算 —— 判据 = 是否存在
        // `avg_cost IS NOT NULL` 的 SKU（可从事实推出 ⇒ 不引入人工配置项）。引擎据此把
        // 「低于成本价」落成 `not_enabled`（系统**有**、该租户**没开**），而不是 `not_wired`。
        snapshot.put("cost_accounting", costsAreTracked(tenantId));
        snapshot.put("orders", orders.rows());
        snapshot.put("skus", skus.rows());
        snapshot.put("returns", returns.rows());
        return snapshot;
    }

    /**
     * `orders` 行：**当前仍待发货**的订单（population 与聚合指标 `pending_ship_orders` 同口径），
     * 按 `created_at` 升序取前 {@link #SNAPSHOT_ROW_LIMIT} 条 —— 最久未发的先保留。
     *
     * <p>`shipped_at` 取该订单物流记录里最晚的发货时刻：引擎把它当「已发货」的第二判据，
     * 状态漂移（状态还是待发货、物流其实已发出）时不至于误报。</p>
     */
    RowBatch assembleOrderRows(Long tenantId) {
        List<Order> orders = orderMapper.selectList(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId)
                .in(Order::getStatus, UNSHIPPED_STATUSES)
                .orderByAsc(Order::getCreatedAt)
                .last("LIMIT " + SNAPSHOT_ROW_FETCH_LIMIT));
        // 多取的那一行只用来判定截断（见 SNAPSHOT_ROW_FETCH_LIMIT），不进快照
        boolean truncated = orders.size() > SNAPSHOT_ROW_LIMIT;
        if (truncated) {
            orders = orders.subList(0, SNAPSHOT_ROW_LIMIT);
        }
        if (orders.isEmpty()) {
            return new RowBatch(new ArrayList<>(), truncated);
        }
        Map<String, OffsetDateTime> shippedAt = shippedAtByOrder(tenantId, orders);
        // 逐订单成本（#5348）：键缺席 = **成本未知**（该行 `cost_amount` 落 NULL），不是 0。
        Map<String, BigDecimal> costs = costByOrder(tenantId, orders);
        List<Map<String, Object>> rows = new ArrayList<>(orders.size());
        for (Order order : orders) {
            rows.add(orderRow(order, shippedAt.get(order.getId()), costs.get(order.getId())));
        }
        return new RowBatch(rows, truncated);
    }

    /**
     * 行里的时刻一律落 **ISO-8601 字符串**。
     *
     * <p>🔴 快照最终落 `daily_briefings.source_snapshot`（JSONB），走的是 MyBatis-Plus
     * `JacksonTypeHandler` —— 它的 ObjectMapper 是**裸 `new ObjectMapper()`（没有 JavaTimeModule）**：
     * 快照里出现 `OffsetDateTime` 会在 insert 时抛 `InvalidDefinitionException`
     * （「Java 8 date/time type not supported by default」，本机实测）。
     * ⇒ 快照只放 JSON 原生类型（字符串 / 数字 / 布尔 / null / 列表 / 映射），时刻用 ISO 串；
     * 引擎侧（`_day`）本来就按 ISO 串解析。</p>
     */
    static String iso(OffsetDateTime value) {
        return value == null ? null : value.toString();
    }

    /** 订单行（键名逐字 = 快照契约；与 `SNAPSHOT_ROW_FIELDS` 的等价由单测机械钉住）。 */
    static Map<String, Object> orderRow(Order order, OffsetDateTime shippedAt, BigDecimal costAmount) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("order_no", order.getOrderNo());
        row.put("status", order.getStatus());
        row.put("customer_id", order.getUserId());
        row.put("created_at", iso(order.getCreatedAt()));
        row.put("shipped_at", iso(shippedAt));
        // 成交金额：实付优先、缺省回落总额。
        row.put("sale_amount",
                order.getActualAmount() != null ? order.getActualAmount() : order.getTotalAmount());
        // 订单成本（#5348）：Σ 行成本；**任一行不可判定 ⇒ null**（整单不可判定，口径见 costByOrder）。
        // 🔴 该键**恒在**（值可为 null）：null 是「成本未知（不可判定）」，不是「缺字段」——
        // 缺字段会被引擎读成「系统没接线（not_wired）」，那是另一回事。
        row.put("cost_amount", costAmount);
        return row;
    }

    private Map<String, OffsetDateTime> shippedAtByOrder(Long tenantId, List<Order> orders) {
        List<String> orderIds = orders.stream()
                .map(Order::getId).filter(StringUtils::hasText).distinct().toList();
        Map<String, OffsetDateTime> shippedAt = new HashMap<>();
        if (orderIds.isEmpty()) {
            return shippedAt;
        }
        for (OrderLogistics logistics : orderLogisticsMapper.selectList(
                new LambdaQueryWrapper<OrderLogistics>()
                        .eq(OrderLogistics::getTenantId, tenantId)
                        .in(OrderLogistics::getOrderId, orderIds)
                        // 入参 id 已由上面那步有界（≤ SNAPSHOT_ROW_LIMIT 个），这里再加一道硬上限：
                        // 父级上限将来放宽时，本查询不会跟着无界。
                        .last("LIMIT " + SNAPSHOT_ROW_LIMIT))) {
            if (logistics.getShippedAt() != null) {
                shippedAt.merge(logistics.getOrderId(), logistics.getShippedAt(),
                        (a, b) -> a.isAfter(b) ? a : b);
            }
        }
        return shippedAt;
    }

    // ==================== 订单成本（低于成本价，issue #5348）====================

    /**
     * 该租户是否在做成本核算（issue #5348 的**租户级事实**）。
     *
     * <p>判据 = **是否存在 `avg_cost IS NOT NULL` 的 SKU** —— 它**从事实推出**，不引入人工配置项
     * （用户裁定 2026-09-24：存量库存 `avg_cost = NULL` 表示「用户不做成本核算」，这是**受支持的形态**，
     * 不是错误）。`false` ⇒ 引擎把「低于成本价」落成 `not_enabled`（系统**有**、该租户**没开**）。</p>
     */
    boolean costsAreTracked(Long tenantId) {
        Long withCost = productSkuMapper.selectCount(new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getTenantId, tenantId)
                .isNotNull(ProductSku::getAvgCost));
        return withCost != null && withCost > 0;
    }

    /**
     * 逐订单成本（issue #5348）。**键缺席 = 成本未知（不可判定）**，不是 0。
     *
     * <p>冻结判据：① 逐订单行解析 SKU（`processing_info.skuId` → 该商品**唯一** SKU → 不可解析）；
     * ② 行成本 = `quantity × avg_cost`；③ 订单成本 = **Σ 行成本**；
     * ④ 🔴 **任一行不可解析、或该行 `avg_cost` 为 NULL ⇒ 整单未知（不出部分和）**。</p>
     *
     * <p>为什么不出部分和：部分和 = **把未知行当 0**（`avg_cost` 既有口径明写「不猜 0」），
     * 它给出的是成本的**下界**而不是成本 ⇒ 据此报出的亏损额必然少报，而「没超成本」这个结论也站不住
     * （未知的那些行可能把整单推过线）。宁可**整单不判定**，也不给一个会误导商家去砍价的数。</p>
     */
    Map<String, BigDecimal> costByOrder(Long tenantId, List<Order> orders) {
        Map<String, BigDecimal> costs = new HashMap<>();
        List<String> orderIds = orders.stream()
                .map(Order::getId).filter(StringUtils::hasText).distinct().toList();
        if (orderIds.isEmpty()) {
            return costs;
        }
        List<OrderItem> items = orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getTenantId, tenantId)
                .in(OrderItem::getOrderId, orderIds));
        if (items.isEmpty()) {
            return costs;   // 没有订单行 ⇒ 成本无从算起（未知，不是 0）
        }
        Map<String, List<ProductSku>> skusByProduct = costSkusByProduct(tenantId, items);
        Map<String, List<OrderItem>> linesByOrder = new LinkedHashMap<>();
        for (OrderItem item : items) {
            if (StringUtils.hasText(item.getOrderId())) {
                linesByOrder.computeIfAbsent(item.getOrderId(), key -> new ArrayList<>()).add(item);
            }
        }
        linesByOrder.forEach((orderId, lines) -> {
            BigDecimal total = orderCost(lines, skusByProduct);
            if (total != null) {
                costs.put(orderId, total);
            }
        });
        return costs;
    }

    /**
     * 订单成本 = **Σ 行成本**；任一行不可判定 ⇒ `null`（**整单不可判定**，不出部分和）。
     *
     * <p>静态纯函数（无 I/O）：判据 2（保守性）的**注入式红证**就直接打在它身上 ——
     * 把返回值改成「部分和」（= 未知行当 0）时，测试里那条断言必须变红。</p>
     */
    static BigDecimal orderCost(List<OrderItem> lines, Map<String, List<ProductSku>> skusByProduct) {
        if (lines.isEmpty()) {
            return null;    // 空行集 = 成本未知（不是「成本为 0」）
        }
        BigDecimal total = BigDecimal.ZERO;
        for (OrderItem line : lines) {
            BigDecimal lineCost = lineCost(line, skusByProduct);
            if (lineCost == null) {
                return null;    // 🔴 保守：宁可整单不判定，也不出一个会低估成本的部分和
            }
            total = total.add(lineCost);
        }
        return total;
    }

    /**
     * 行成本 = `quantity × avg_cost`；`null` = 该行**成本未知**（不可判定）。
     *
     * <p>SKU 解析优先级（冻结判据）：① `processing_info.skuId` → ② 该商品**唯一** SKU（商品只有 1 个
     * SKU ⇒ 无歧义）→ ③ 不可解析。声明的 `skuId` 已失效（不在本商品的 SKU 集里）时退回 ② ——
     * 与 `OrderService.matchSkuId` 的「陈旧 `skuId` 先校验、再回退键族」同口径。</p>
     */
    static BigDecimal lineCost(OrderItem line, Map<String, List<ProductSku>> skusByProduct) {
        BigDecimal quantity = line.getQuantity();
        if (quantity == null) {
            return null;    // 数量未知 ⇒ 该行成本未知
        }
        List<ProductSku> skus = skusByProduct.getOrDefault(line.getProductId(), List.of());
        ProductSku sku = null;
        Long declared = declaredSkuId(line.getProcessingInfo());
        if (declared != null) {
            sku = skus.stream().filter(candidate -> declared.equals(candidate.getId()))
                    .findFirst().orElse(null);
        }
        if (sku == null && skus.size() == 1) {
            sku = skus.get(0);      // ② 该商品只有 1 个 SKU ⇒ 无歧义
        }
        if (sku == null || sku.getAvgCost() == null) {
            return null;            // ③ 不可解析 / 成本价 NULL ⇒ 未知（**不猜 0**）
        }
        return quantity.multiply(sku.getAvgCost());
    }

    /**
     * `order_items.processing_info` 里的 `skuId`（键族见 `OrderService.matchSkuId`）。
     *
     * <p>JSONB 里的数字可能是 `Long` / `Integer` / 字符串，一律按数值解析；无该键或非数值 ⇒ `null`
     * （**不猜**：猜错的成本会直接被当成真值去判「低于成本」）。</p>
     */
    static Long declaredSkuId(Object processingInfo) {
        if (!(processingInfo instanceof Map<?, ?> info)) {
            return null;
        }
        Object raw = info.get("skuId");
        if (raw instanceof Number number) {
            return number.longValue();
        }
        if (raw instanceof String text && StringUtils.hasText(text)) {
            try {
                return Long.valueOf(text.trim());
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return null;
    }

    /**
     * 本次订单行涉及的商品 → 这些商品的**全部** SKU（供「唯一 SKU」判定与取 `avg_cost`）。
     *
     * <p>🔴 查询撞上行数上限 ⇒ 返回空表（= 所有行都不可解析 ⇒ 所有订单成本未知）：截断会让
     * 「该商品只有一个 SKU」的判定**失真**（第二个 SKU 可能正好在被截掉的那部分里）⇒ 那时给出的
     * 成本可能张冠李戴，宁可全部不判定。</p>
     */
    private Map<String, List<ProductSku>> costSkusByProduct(Long tenantId, List<OrderItem> items) {
        List<String> productIds = items.stream()
                .map(OrderItem::getProductId).filter(StringUtils::hasText).distinct().toList();
        if (productIds.isEmpty()) {
            return Map.of();
        }
        List<ProductSku> skus = productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getTenantId, tenantId)
                .in(ProductSku::getProductId, productIds)
                .last("LIMIT " + SNAPSHOT_ROW_FETCH_LIMIT));
        if (skus.size() > SNAPSHOT_ROW_LIMIT) {
            return Map.of();
        }
        Map<String, List<ProductSku>> byProduct = new LinkedHashMap<>();
        for (ProductSku sku : skus) {
            if (StringUtils.hasText(sku.getProductId())) {
                byProduct.computeIfAbsent(sku.getProductId(), key -> new ArrayList<>()).add(sku);
            }
        }
        return byProduct;
    }

    /**
     * `skus` 行：**库存最低的前 N 个在售 SKU**（`stock >= 0`，按库存升序截断 ⇒ 保留的正是最该看的）。
     *
     * <p>刻意**不按阈值预筛**：`low_stock_threshold` 可由租户配置覆盖（引擎侧 `ProactiveConfig`），
     * 快照若按默认 100 截断，租户把阈值调高后就会**静默漏报** —— 那正是本单要治的
     * 「没数据被读成没问题」；阈值过滤留给引擎，装配层只负责把行按有界方式给全。</p>
     */
    RowBatch assembleSkuRows(Long tenantId) {
        List<ProductSku> skus = productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getTenantId, tenantId)
                .ge(ProductSku::getStock, 0)
                .orderByAsc(ProductSku::getStock)
                .last("LIMIT " + SNAPSHOT_ROW_FETCH_LIMIT));
        boolean truncated = skus.size() > SNAPSHOT_ROW_LIMIT;
        if (truncated) {
            skus = skus.subList(0, SNAPSHOT_ROW_LIMIT);
        }
        if (skus.isEmpty()) {
            return new RowBatch(new ArrayList<>(), truncated);
        }
        Map<String, String> names = onSaleProductNames(tenantId, skus);
        List<Map<String, Object>> rows = new ArrayList<>(skus.size());
        for (ProductSku sku : skus) {
            String productName = names.get(sku.getProductId());
            if (productName == null) {
                continue;   // 下架/已删商品下的 SKU 不进快照（与聚合指标 low_stock_items 同口径）
            }
            rows.add(skuRow(sku, productName));
        }
        return new RowBatch(rows, truncated);
    }

    /** SKU 行（键名逐字 = 快照契约；与 `SNAPSHOT_ROW_FIELDS` 的等价由单测机械钉住）。 */
    static Map<String, Object> skuRow(ProductSku sku, String productName) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("sku_id", sku.getId());
        row.put("product_id", sku.getProductId());
        row.put("product_name", productName);
        row.put("stock", sku.getStock());
        return row;
    }

    /** 在售商品 id → 名称（下架/已删商品不入表 ⇒ 其 SKU 不进快照）。 */
    private Map<String, String> onSaleProductNames(Long tenantId, List<ProductSku> skus) {
        List<String> productIds = skus.stream()
                .map(ProductSku::getProductId).filter(StringUtils::hasText).distinct().toList();
        Map<String, String> names = new HashMap<>();
        if (productIds.isEmpty()) {
            return names;
        }
        for (Product product : productMapper.selectList(new LambdaQueryWrapper<Product>()
                .eq(Product::getTenantId, tenantId)
                .eq(Product::getStatus, "on_sale")
                .in(Product::getId, productIds)
                // 同上：id 入参已有界，这里再加一道硬上限（父级放宽时本查询不跟着无界）
                .last("LIMIT " + SNAPSHOT_ROW_LIMIT))) {
            names.put(product.getId(), product.getName());
        }
        return names;
    }

    /**
     * `returns` 行：**退货工单**流水（全仓无独立退货流水表，退货事实落在 `after_sales_tickets`）。
     * 行字段按契约：`return_no` ← 工单号、`returned_at` ← **工单发起时刻**（退货发起即事件日）、
     * `amount` ← 退款金额。
     *
     * <p>`product_id` **不猜**：工单本身没有商品列，只有该工单关联订单的商品**唯一**时才回填；
     * 多商品订单给 `null` ⇒ 那些行仍参与「同一客户」维度的连续退货判定，商品维度不可用
     * （如实登记，不假装全覆盖）。</p>
     */
    RowBatch assembleReturnRows(Long tenantId, OffsetDateTime windowStart) {
        List<AfterSalesTicket> tickets = afterSalesTicketMapper.selectList(
                new LambdaQueryWrapper<AfterSalesTicket>()
                        .eq(AfterSalesTicket::getTenantId, tenantId)
                        .eq(AfterSalesTicket::getTicketType, RETURN_TICKET_TYPE)
                        .ge(AfterSalesTicket::getCreatedAt, windowStart)
                        .orderByDesc(AfterSalesTicket::getCreatedAt)
                        .last("LIMIT " + SNAPSHOT_ROW_FETCH_LIMIT));
        boolean truncated = tickets.size() > SNAPSHOT_ROW_LIMIT;
        if (truncated) {
            tickets = tickets.subList(0, SNAPSHOT_ROW_LIMIT);
        }
        if (tickets.isEmpty()) {
            return new RowBatch(new ArrayList<>(), truncated);
        }
        Map<String, String> singleProduct = singleProductByOrder(tenantId, tickets);
        List<Map<String, Object>> rows = new ArrayList<>(tickets.size());
        for (AfterSalesTicket ticket : tickets) {
            rows.add(returnRow(ticket, singleProduct.get(ticket.getOrderId())));
        }
        return new RowBatch(rows, truncated);
    }

    /** 退货行（键名逐字 = 快照契约；与 `SNAPSHOT_ROW_FIELDS` 的等价由单测机械钉住）。 */
    static Map<String, Object> returnRow(AfterSalesTicket ticket, String productId) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("return_no", ticket.getTicketNo());
        row.put("customer_id", ticket.getCustomerId());
        row.put("product_id", productId);
        row.put("returned_at", iso(ticket.getCreatedAt()));
        row.put("amount", ticket.getRefundAmount());
        return row;
    }

    /** 每张订单的**唯一**商品 id：多商品订单不入表（`product_id` 回填 null，不猜）。 */
    private Map<String, String> singleProductByOrder(Long tenantId, List<AfterSalesTicket> tickets) {
        List<String> orderIds = tickets.stream()
                .map(AfterSalesTicket::getOrderId).filter(StringUtils::hasText).distinct().toList();
        Map<String, String> single = new HashMap<>();
        if (orderIds.isEmpty()) {
            return single;
        }
        Map<String, Set<String>> products = new HashMap<>();
        for (OrderItem item : orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getTenantId, tenantId)
                .in(OrderItem::getOrderId, orderIds))) {
            if (StringUtils.hasText(item.getProductId())) {
                products.computeIfAbsent(item.getOrderId(), key -> new LinkedHashSet<>())
                        .add(item.getProductId());
            }
        }
        products.forEach((orderId, ids) -> {
            if (ids.size() == 1) {
                single.put(orderId, ids.iterator().next());
            }
        });
        return single;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Number> extractMetrics(Map<String, Object> snapshot) {
        Map<String, Number> metrics = new HashMap<>();
        Object raw = snapshot.get("metrics");
        if (raw instanceof Map<?, ?> m) {
            for (Map.Entry<?, ?> e : m.entrySet()) {
                Object v = e.getValue();
                if (v instanceof Number n) {
                    metrics.put(String.valueOf(e.getKey()), n);
                }
            }
        }
        return metrics;
    }

    /**
     * LLM 提示词用的快照视图：**只含** `metrics` + `facts`（红线 4 的「纯数字 + 脱敏事实」口径）。
     *
     * <p>行级数组（`orders` / `skus` / `returns` 与 `row_fields` / `row_meta`）**出提示词**：它们是
     * 规则引擎与按需视图的输入，落库快照里在、提示词里不在 —— 两件事各取所需，不是两份口径
     * （提示词视图是落库快照的**子集**，唯一来源仍是 {@link #aggregateSnapshot}）。</p>
     */
    static Map<String, Object> promptSnapshot(Map<String, Object> snapshot) {
        Map<String, Object> prompt = new LinkedHashMap<>();
        prompt.put("metrics", snapshot.get("metrics"));
        prompt.put("facts", snapshot.get("facts"));
        return prompt;
    }

    // ==================== 数字回填校验层（红线 4）====================

    /** 校验结果：过滤后的 content + verify_status + 各区块保留数 */
    record VerifyResult(Object content, String status, int todoKept, int risksKept, int suggestionsKept) {
    }

    /**
     * 校验 LLM 输出的每条目：其 metrics 引用的 (key, value) 必须与快照一致，
     * key 不在快照或 value 不一致 → 丢弃该条；全部被丢弃 → status=failed。
     * summary 文本中的数字也必须能在快照中找到（P2-2：LLM 在自由文本里编数字
     * 无法被 metrics 引用机制拦截，故对 summary 提取数字做对账）。
     */
    VerifyResult verifyAndFilter(JsonNode briefing, Map<String, Number> metrics) {
        ObjectNode content = objectMapper.createObjectNode();
        String summary = briefing.path("summary").asText("");
        // summary 数字对账：提取文本中的数字（整数/小数），任一数字不在快照 → summary 降级为空
        // （防 LLM 在 summary 自由文本中编造经营数字，红线 4 覆盖到自由文本层）
        if (!summaryNumbersMatchSnapshot(summary, metrics)) {
            log.warn("简报 summary 含快照外数字，已降级为空（防编造）: {}", summary);
            summary = "";
        }
        content.put("summary", summary);
        content.set("review", keepReview(briefing.path("review"), metrics));

        ArrayNode todo = keepItems(briefing.path("todo"), metrics);
        ArrayNode risks = keepItems(briefing.path("risks"), metrics);
        ArrayNode suggestions = keepItems(briefing.path("suggestions"), metrics);
        content.set("todo", todo);
        content.set("risks", risks);
        content.set("suggestions", suggestions);

        String status;
        if (todo.isEmpty() && risks.isEmpty() && suggestions.isEmpty()) {
            status = "failed";
        } else if (todo.size() < briefing.path("todo").size()
                || risks.size() < briefing.path("risks").size()
                || suggestions.size() < briefing.path("suggestions").size()) {
            status = "partial";
        } else {
            status = "verified";
        }
        return new VerifyResult(content, status, todo.size(), risks.size(), suggestions.size());
    }

    /** review 区块：数值必须与快照一致，否则丢弃 */
    private ArrayNode keepReview(JsonNode review, Map<String, Number> metrics) {
        ArrayNode kept = objectMapper.createArrayNode();
        if (!review.isArray()) {
            return kept;
        }
        for (JsonNode item : review) {
            JsonNode metricRef = item.path("metrics");
            if (metricRef.isArray() && metricRef.size() > 0) {
                // review 带 metrics 引用 → 对账
                if (!allMetricsMatch(metricRef, metrics)) {
                    continue;
                }
            } else {
                // review 无 metrics 引用：数值型 value 必须在快照中存在相同值，否则丢弃
                JsonNode valueNode = item.path("value");
                if (valueNode.isNumber() && !valueExistsInSnapshot(valueNode.doubleValue(), metrics)) {
                    continue;
                }
            }
            kept.add(item);
        }
        return kept;
    }

    /** todo/risks/suggestions 区块：必须带 metrics 引用且全部对账通过，否则丢弃 */
    private ArrayNode keepItems(JsonNode items, Map<String, Number> metrics) {
        ArrayNode kept = objectMapper.createArrayNode();
        if (!items.isArray()) {
            return kept;
        }
        for (JsonNode item : items) {
            JsonNode metricRef = item.path("metrics");
            if (!metricRef.isArray() || metricRef.size() == 0) {
                continue;   // 无引用 = 无法对账 = 丢弃
            }
            if (!allMetricsMatch(metricRef, metrics)) {
                continue;   // 引用与快照不一致 = 丢弃
            }
            kept.add(item);
        }
        return kept;
    }

    private boolean allMetricsMatch(JsonNode metricRef, Map<String, Number> metrics) {
        for (JsonNode m : metricRef) {
            String key = m.path("key").asText("");
            if (!m.path("value").isNumber()) {
                return false;
            }
            Number snapshotValue = metrics.get(key);
            if (snapshotValue == null) {
                return false;   // key 不在快照 = LLM 编造
            }
            if (Math.abs(m.path("value").doubleValue() - snapshotValue.doubleValue()) > METRIC_TOLERANCE) {
                return false;   // value 与快照不一致 = LLM 编造
            }
        }
        return true;
    }

    private boolean valueExistsInSnapshot(double value, Map<String, Number> metrics) {
        for (Number n : metrics.values()) {
            if (Math.abs(n.doubleValue() - value) <= METRIC_TOLERANCE) {
                return true;
            }
        }
        return false;
    }

    /** summary 文本数字对账：提取所有数字，任一不在快照中 → false（防自由文本编造） */
    private boolean summaryNumbersMatchSnapshot(String summary, Map<String, Number> metrics) {
        if (summary == null || summary.isEmpty()) {
            return true;   // 空 summary 无需对账
        }
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("\\d+(?:\\.\\d+)?").matcher(summary);
        while (m.find()) {
            try {
                double num = Double.parseDouble(m.group());
                if (!valueExistsInSnapshot(num, metrics)) {
                    return false;
                }
            } catch (NumberFormatException e) {
                return false;
            }
        }
        return true;
    }

    // ==================== 定时生成 ====================

    /**
     * 扫描所有已开启租户，到生成时刻且当日未生成 → 生成。
     * 定时任务每分钟调用（BriefingScheduler）；关闭租户直接跳过（熔断）。
     */
    public int generateDueTenants() {
        List<Tenant> enabledTenants = tenantMapper.selectList(
                new LambdaQueryWrapper<Tenant>()
                        .eq(Tenant::getBriefingEnabled, true));
        LocalTime now = LocalTime.now(CST);
        LocalDate today = LocalDate.now(CST);
        int generated = 0;
        for (Tenant tenant : enabledTenants) {
            String timeStr = StringUtils.hasText(tenant.getBriefingGenerateTime())
                    ? tenant.getBriefingGenerateTime() : "06:00";
            LocalTime generateTime;
            try {
                generateTime = LocalTime.parse(timeStr);
            } catch (Exception e) {
                generateTime = LocalTime.parse("06:00");
            }
            // 未到生成时刻 → 跳过（生成时刻后一直可补生成，直到当日有简报）
            if (now.isBefore(generateTime)) {
                continue;
            }
            // 调度线程无 JWT Filter，幂等预检也查租户隔离表 daily_briefings：
            // TenantLineInnerInterceptor 在无 TenantContext 时抛
            // "Tenant context not initialized"（issue #3957，生产每轮调度整体夭折），
            // 须与 generateForTenant 一样显式设置租户上下文（内层再设同值为幂等 no-op）。
            Long previousTenantId = TenantContext.getTenantId();
            TenantContext.setTenantId(tenant.getId());
            try {
                if (getBriefingByDate(tenant.getId(), today) != null) {
                    continue;   // 当日已生成
                }
                try {
                    DailyBriefing briefing = generateForTenant(tenant.getId());
                    if (briefing != null && !"failed".equals(briefing.getVerifyStatus())) {
                        generated++;
                    }
                } catch (Exception e) {
                    log.error("定时生成简报失败 tenantId={}: {}", tenant.getId(), e.getMessage());
                }
            } finally {
                if (previousTenantId != null) {
                    TenantContext.setTenantId(previousTenantId);
                } else {
                    TenantContext.clear();
                }
            }
        }
        return generated;
    }

    // ==================== 工具方法 ====================

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
}
