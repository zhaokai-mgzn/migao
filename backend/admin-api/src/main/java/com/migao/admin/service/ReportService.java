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

    private static OffsetDateTime startOfDay(String date, ZoneId zone) {
        return LocalDate.parse(date.trim()).atStartOfDay(zone).toOffsetDateTime();
    }
}
