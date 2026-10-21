package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.OrderMarginReportView;
import com.migao.admin.entity.Order;
import com.migao.admin.mapper.OrderMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;

/**
 * 报表中心（issue #7376，P1-4 段 1）：**只读**、复用既有算好的口径、不新增写面。
 *
 * <h3>段 1 范围</h3>
 * <ul>
 *   <li>✅ <b>订单毛利报表</b>：逐单 + 合计（复用 {@link OrderMarginService} 的同一份计算，
 *       不在这里重算面料/加工口径）；</li>
 *   <li>✅ <b>数据范围</b>：与 P0-4 同口径（`self` 时只看本人创建的单）；</li>
 *   <li>🚫 库存周转/滞销、员工业绩、应收账龄报表化 —— 段 2（账龄已有独立端点，
 *       报表化只需加合计与分组，但那要新增分组读面）。</li>
 * </ul>
 *
 * <h3>三条纪律（都写进判据）</h3>
 * <ol>
 *   <li><b>合计 = 明细之和</b>：逐单算完再求和，不写第二条聚合 SQL（两条口径必然漂移）；</li>
 *   <li><b>空数据 ≠ 0</b>：没有命中订单时合计为 {@code null}、`hasData=false`；</li>
 *   <li><b>成本未知单独计数</b>：缺进价/未定价报工的单**不进毛利合计**，但计数要让读者知道合计少算了。</li>
 * </ol>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ReportService {

    private static final int MAX_ROWS = 500;

    private final OrderMapper orderMapper;

    /** 库存周转/滞销（段 2）：批次 + 出库流水（复用时序，不新造「最后出库日」列 —— 那是会漂的派生值）。 */
    private final com.migao.admin.mapper.StockBatchMapper stockBatchMapper;
    private final com.migao.admin.mapper.StockBatchConsumptionMapper stockBatchConsumptionMapper;
    private final OrderMarginService orderMarginService;
    private final com.migao.admin.time.BusinessClock businessClock;

    /**
     * 订单毛利报表。
     *
     * @param startDate      下单日期起（可空）
     * @param endDate        下单日期止（可空）
     * @param scopeOwnerId   P0-4 数据范围：非空 ⇒ 只看该用户创建的单（{@code self} 范围）
     */
    public OrderMarginReportView orderMargins(String startDate, String endDate, String scopeOwnerId) {
        LambdaQueryWrapper<Order> wrapper = new LambdaQueryWrapper<Order>()
                .orderByDesc(Order::getCreatedAt)
                .last("LIMIT " + MAX_ROWS);
        if (StringUtils.hasText(scopeOwnerId)) {
            wrapper.eq(Order::getCreatedBy, scopeOwnerId);
        }
        ZoneId zone = businessClock.zone();
        if (StringUtils.hasText(startDate)) {
            wrapper.ge(Order::getCreatedAt, startOfDay(startDate, zone));
        }
        if (StringUtils.hasText(endDate)) {
            wrapper.lt(Order::getCreatedAt, startOfDay(endDate, zone).plusDays(1));
        }

        List<OrderMarginReportView.Row> rows = new ArrayList<>();
        List<BigDecimal> revenues = new ArrayList<>();
        List<BigDecimal> refunds = new ArrayList<>();
        List<BigDecimal> fabrics = new ArrayList<>();
        List<BigDecimal> labors = new ArrayList<>();
        List<BigDecimal> margins = new ArrayList<>();
        int unknownCost = 0;

        for (Order order : orderMapper.selectList(wrapper)) {
            var margin = orderMarginService.margin(order.getId());
            boolean known = margin.isCostKnown();
            if (!known) {
                // 成本未知**不进合计**（把未知当 0 会让毛利虚高）—— 但计数，让读者知道少算了多少
                unknownCost++;
            } else {
                revenues.add(margin.getRevenue());
                refunds.add(margin.getRefunded());
                fabrics.add(margin.getFabricCost());
                labors.add(margin.getLaborCost());
                margins.add(margin.getGrossMargin());
            }
            rows.add(OrderMarginReportView.Row.builder()
                    .orderId(margin.getOrderId())
                    .orderNo(margin.getOrderNo())
                    .status(margin.getStatus())
                    .revenue(margin.getRevenue())
                    .refunded(margin.getRefunded())
                    .fabricCost(margin.getFabricCost())
                    .laborCost(margin.getLaborCost())
                    .grossMargin(margin.getGrossMargin())
                    .costKnown(known)
                    .build());
        }

        boolean hasData = !rows.isEmpty();
        OrderMarginReportView.Totals totals = hasData
                ? OrderMarginReportView.Totals.builder()
                        .revenue(ReportTotals.sum(revenues))
                        .refunded(ReportTotals.sum(refunds))
                        .fabricCost(ReportTotals.sum(fabrics))
                        .laborCost(ReportTotals.sum(labors))
                        .grossMargin(ReportTotals.sum(margins))
                        .build()
                : null;   // 🔴 空数据 ⇒ null（不是 0）

        return OrderMarginReportView.builder()
                .startDate(startDate)
                .endDate(endDate)
                .hasData(hasData)
                .rows(rows)
                .totals(totals)
                .unknownCostOrders(unknownCost)
                .build();
    }

    /**
     * 库存周转与滞销报表（issue #7376 段 2）。
     *
     * <p>取数**不新造派生列**：「上次出库日」现从 `stock_batch_consumptions` 的扣减行里聚合
     * （`reason='processing_order'` 且 `delta<0`）—— 落一列就会漂（扣料路径不止一条）。
     * 从未出库的批次用**入库日**起算（否则「一直没人动」的货永远进不了滞销清单）。</p>
     *
     * @param thresholdDays 滞销阈值（可空 ⇒ 默认 90 天）
     * @param warehouseCode 仓编码过滤（可空 ⇒ 全部仓）
     */
    public com.migao.admin.dto.InventoryReportView inventoryAging(Integer thresholdDays, String warehouseCode) {
        int threshold = thresholdDays == null || thresholdDays <= 0
                ? InventoryAgePolicy.SLOW_MOVING_DAYS : thresholdDays;
        LocalDate today = businessClock.today();

        LambdaQueryWrapper<com.migao.admin.entity.StockBatch> batchQuery =
                new LambdaQueryWrapper<com.migao.admin.entity.StockBatch>()
                        .gt(com.migao.admin.entity.StockBatch::getQuantity, BigDecimal.ZERO)
                        .orderByAsc(com.migao.admin.entity.StockBatch::getBatchNo);
        if (StringUtils.hasText(warehouseCode)) {
            batchQuery.eq(com.migao.admin.entity.StockBatch::getWarehouse, warehouseCode.trim());
        }

        java.util.Map<Long, LocalDate> lastOutbound = new java.util.HashMap<>();
        for (com.migao.admin.entity.StockBatchConsumption row : stockBatchConsumptionMapper.selectList(
                new LambdaQueryWrapper<com.migao.admin.entity.StockBatchConsumption>()
                        .lt(com.migao.admin.entity.StockBatchConsumption::getDelta, BigDecimal.ZERO))) {
            if (row.getBatchId() == null || row.getCreatedAt() == null) {
                continue;
            }
            LocalDate day = LocalDate.ofInstant(row.getCreatedAt().toInstant(), businessClock.zone());
            LocalDate existing = lastOutbound.get(row.getBatchId());
            if (existing == null || day.isAfter(existing)) {
                lastOutbound.put(row.getBatchId(), day);
            }
        }

        List<com.migao.admin.dto.InventoryReportView.Row> rows = new ArrayList<>();
        List<BigDecimal> onHands = new ArrayList<>();
        List<BigDecimal> slowOnHands = new ArrayList<>();
        int slowBatches = 0;
        int undetermined = 0;

        for (com.migao.admin.entity.StockBatch batch : stockBatchMapper.selectList(batchQuery)) {
            // 从未出库 ⇒ 用入库日起算（`received_date` 可空 ⇒ 再退到创建时间）
            LocalDate anchor = lastOutbound.get(batch.getId());
            if (anchor == null) {
                anchor = batch.getReceivedDate() != null
                        ? batch.getReceivedDate()
                        : (batch.getCreatedAt() == null ? null
                        : LocalDate.ofInstant(batch.getCreatedAt().toInstant(), businessClock.zone()));
            }
            InventoryAgePolicy.Decision decision =
                    InventoryAgePolicy.evaluate(batch.getQuantity(), anchor, today, threshold);
            if (decision.daysSinceMovement() < 0) {
                undetermined++;
            }
            onHands.add(batch.getQuantity());
            if (decision.slowMoving()) {
                slowBatches++;
                slowOnHands.add(batch.getQuantity());
            }
            rows.add(com.migao.admin.dto.InventoryReportView.Row.builder()
                    .batchId(batch.getId())
                    .batchNo(batch.getBatchNo())
                    .skuCode(batch.getSkuCode())
                    .warehouse(batch.getWarehouse())
                    .onHand(batch.getQuantity())
                    .lastMovementDate(anchor == null ? null : anchor.toString())
                    .daysSinceMovement(decision.daysSinceMovement())
                    .slowMoving(decision.slowMoving())
                    .reason(decision.reason())
                    .build());
        }

        boolean hasData = !rows.isEmpty();
        return com.migao.admin.dto.InventoryReportView.builder()
                .slowMovingDays(threshold)
                .hasData(hasData)
                .rows(rows)
                .totals(hasData ? com.migao.admin.dto.InventoryReportView.Totals.builder()
                        .onHand(ReportTotals.sum(onHands))
                        .slowMovingOnHand(ReportTotals.sum(slowOnHands))
                        .slowMovingBatches(slowBatches)
                        .build() : null)
                .undeterminedRows(undetermined)
                .build();
    }

    /**
     * 员工业绩报表（issue #7376 段 3）：按**制单人**归集订单数 / 收入 / 退款 / 客单价。
     *
     * <p>口径三条：① **没有制单人的订单单独成档**（存量订单 / C 端自助单）—— 摊给某人就是凭空加分；
     * ② 客单价 = 收入 / 单数，单数为 0 ⇒ {@code null}（不做 0 除）；③ 合计 = 各行之和。</p>
     *
     * <p>⚠️ **退款本段不给**：退款真值在 `finance_transactions`（每单一次查询 = N+1），本段先只做
     * 「单数 + 收入 + 客单价」。宁可少一列，也不放一个恒为 0 的假字段（那会被读成「这人没退过款」）。</p>
     *
     * @param startDate    下单日期起（可空）
     * @param endDate      下单日期止（可空）
     * @param scopeOwnerId P0-4 数据范围：非空 ⇒ 只统计本人创建的单（业绩报表里就是「只看自己的业绩」）
     */
    public com.migao.admin.dto.StaffPerformanceView staffPerformance(String startDate, String endDate,
                                                                    String scopeOwnerId) {
        LambdaQueryWrapper<Order> wrapper = new LambdaQueryWrapper<Order>()
                .orderByDesc(Order::getCreatedAt)
                .last("LIMIT " + MAX_ROWS);
        if (StringUtils.hasText(scopeOwnerId)) {
            wrapper.eq(Order::getCreatedBy, scopeOwnerId);
        }
        ZoneId zone = businessClock.zone();
        if (StringUtils.hasText(startDate)) {
            wrapper.ge(Order::getCreatedAt, startOfDay(startDate, zone));
        }
        if (StringUtils.hasText(endDate)) {
            wrapper.lt(Order::getCreatedAt, startOfDay(endDate, zone).plusDays(1));
        }

        // 按制单人归集（保持首次出现顺序，便于人读日志）
        java.util.Map<String, List<Order>> byStaff = new java.util.LinkedHashMap<>();
        int unattributed = 0;
        for (Order order : orderMapper.selectList(wrapper)) {
            if (!StringUtils.hasText(order.getCreatedBy())) {
                unattributed++;
                continue;
            }
            byStaff.computeIfAbsent(order.getCreatedBy(), k -> new ArrayList<>()).add(order);
        }

        List<com.migao.admin.dto.StaffPerformanceView.Row> rows = new ArrayList<>();
        List<BigDecimal> revenues = new ArrayList<>();
        List<BigDecimal> refunds = new ArrayList<>();
        int totalOrders = 0;
        for (java.util.Map.Entry<String, List<Order>> entry : byStaff.entrySet()) {
            BigDecimal revenue = BigDecimal.ZERO;
            for (Order order : entry.getValue()) {
                revenue = revenue.add(order.getTotalAmount() == null ? BigDecimal.ZERO : order.getTotalAmount());
            }
            int count = entry.getValue().size();
            revenues.add(revenue);
            totalOrders += count;
            rows.add(com.migao.admin.dto.StaffPerformanceView.Row.builder()
                    .staffId(entry.getKey())
                    .staffName(entry.getValue().get(0).getCreatedByName())
                    .orderCount(count)
                    .revenue(revenue.setScale(2, java.math.RoundingMode.HALF_UP))
                    .avgOrderValue(count == 0 ? null
                            : revenue.divide(BigDecimal.valueOf(count), 2, java.math.RoundingMode.HALF_UP))
                    .build());
        }

        boolean hasData = !rows.isEmpty();
        return com.migao.admin.dto.StaffPerformanceView.builder()
                .startDate(startDate)
                .endDate(endDate)
                .hasData(hasData)
                .rows(rows)
                .totals(hasData ? com.migao.admin.dto.StaffPerformanceView.Totals.builder()
                        .orderCount(totalOrders)
                        .revenue(ReportTotals.sum(revenues))
                        .build() : null)
                .unattributedOrders(unattributed)
                .build();
    }

    private static OffsetDateTime startOfDay(String date, ZoneId zone) {
        return LocalDate.parse(date.trim()).atStartOfDay(zone).toOffsetDateTime();
    }
}
