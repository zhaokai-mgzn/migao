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
 * <h3>口径声明（黄金策的「页面上下文」把本类 javadoc 当**唯一真值源**引用，issue #7376）</h3>
 * <p>四张报表共用四条口径：</p>
 * <ol>
 *   <li><b>合计 = 明细之和</b>（同一份函数复算，不写第二条聚合 SQL）；</li>
 *   <li><b>没有数据 ≠ 0</b>：无命中记录时合计为 {@code null}、`hasData=false`；</li>
 *   <li><b>未知不填 0</b>：未定价的返工 / 未采集的报废料 / 未发生的退款，一律记未知并单列计数；</li>
 *   <li><b>数据范围同 P0-4</b>：`self` 范围只统计本人创建的单据。</li>
 * </ol>
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

    /** 质量成本（段 4）：返工报工 + 退款流水（都是既有真值源，不新造表）。 */
    private final com.migao.admin.mapper.ProductionWorkLogMapper productionWorkLogMapper;
    private final com.migao.admin.mapper.FinanceTransactionMapper financeTransactionMapper;
    private final com.migao.admin.mapper.StockBatchConsumptionMapper stockBatchConsumptionMapper;
    private final OrderMarginService orderMarginService;
    private final com.migao.admin.time.BusinessClock businessClock;
    /** 账龄真值源（P0-2）：报表中心不重算分档/账期，只把它的底稿套上报表口径（issue #7376 段 5）。 */
    private final CustomerService customerService;
    /** 返工按客户/工序归集的桥：报工行只有 `processing_order_id`，客户要经「加工单 → 订单」才拿得到。 */
    private final com.migao.admin.mapper.ProcessingOrderMapper processingOrderMapper;

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

    /**
     * **质量成本报表**（issue #7377，P1-5 段 1）：返工工时 / 报废料 / 赔付三项分列。
     *
     * <p>🔴 三种「未知」的处理各不相同，都不许折成 0：</p>
     * <ul>
     *   <li>返工报工**未定价**（`price_state='unpriced'`）⇒ 金额不计入，单独计行数；</li>
     *   <li>**报废料**本仓未采集（质检只到成品帘级，没有到批次）⇒ 该项恒未知；</li>
     *   <li>窗口内**没有退款流水** ⇒ 赔付未知（不是「赔付 0」的结论）。</li>
     * </ul>
     */
    public com.migao.admin.dto.QualityCostView qualityCost(String startDate, String endDate) {
        List<com.migao.admin.dto.QualityCostView.Component> components = new ArrayList<>();
        // 🔴 窗口过滤：本方法一直收着 startDate/endDate 却**没用**（issue #7377 段 5 修）——
        // 「参数收了不用」比没有参数更坏：调用方以为筛过了，实际拿到的是全量。
        LocalDate from = parseDay(startDate);
        LocalDate to = parseDay(endDate);
        List<com.migao.admin.entity.ProductionWorkLog> reworkLogs = new ArrayList<>();
        for (com.migao.admin.entity.ProductionWorkLog log : productionWorkLogMapper.selectList(
                new LambdaQueryWrapper<com.migao.admin.entity.ProductionWorkLog>()
                        .eq(com.migao.admin.entity.ProductionWorkLog::getWorkType, "rework"))) {
            if (inWindow(workDay(log), from, to)) {
                reworkLogs.add(log);
            }
        }

        BigDecimal reworkAmount = BigDecimal.ZERO;
        int unpriced = 0;
        for (com.migao.admin.entity.ProductionWorkLog log : reworkLogs) {
            if ("unpriced".equals(log.getPriceState()) || log.getUnitPrice() == null) {
                unpriced++;
                continue;   // 🔴 未定价**不计金额**（未定价 ≠ 0 元工时）
            }
            BigDecimal qty = log.getQty() == null ? BigDecimal.ZERO : log.getQty();
            reworkAmount = reworkAmount.add(log.getUnitPrice().multiply(qty));
        }
        QualityCostPolicy.Component rework = QualityCostPolicy.reworkCost(
                unpriced == reworkLogs.size() && !reworkLogs.isEmpty() ? null : reworkAmount, unpriced);
        components.add(com.migao.admin.dto.QualityCostView.Component.builder()
                .code(rework.code()).label(rework.label()).amount(rework.amount()).known(rework.known())
                .note(rework.note()).unknownItems(rework.unknownItems()).build());

        QualityCostPolicy.Component scrap = QualityCostPolicy.scrapCost();
        components.add(com.migao.admin.dto.QualityCostView.Component.builder()
                .code(scrap.code()).label(scrap.label()).amount(scrap.amount()).known(scrap.known())
                .note(scrap.note()).unknownItems(scrap.unknownItems()).build());

        // 赔付：按订单退款流水口径（`finance_transactions` 无售后单关联列 ⇒ 无法按售后单归集）
        List<com.migao.admin.entity.FinanceTransaction> refunds = new ArrayList<>();
        for (com.migao.admin.entity.FinanceTransaction refund : financeTransactionMapper.selectList(
                new LambdaQueryWrapper<com.migao.admin.entity.FinanceTransaction>()
                        .eq(com.migao.admin.entity.FinanceTransaction::getType, "refund")
                        .eq(com.migao.admin.entity.FinanceTransaction::getStatus, "success"))) {
            // 退款按「发生日」（没有则按创建日）卡窗口，与返工报工同一个窗口口径
            if (inWindow(txnDay(refund), from, to)) {
                refunds.add(refund);
            }
        }
        BigDecimal refundAmount = BigDecimal.ZERO;
        for (com.migao.admin.entity.FinanceTransaction refund : refunds) {
            refundAmount = refundAmount.add(refund.getAmount() == null ? BigDecimal.ZERO : refund.getAmount());
        }
        QualityCostPolicy.Component compensation =
                QualityCostPolicy.compensation(refundAmount, !refunds.isEmpty());
        components.add(com.migao.admin.dto.QualityCostView.Component.builder()
                .code(compensation.code()).label(compensation.label()).amount(compensation.amount())
                .known(compensation.known()).note(compensation.note())
                .unknownItems(compensation.unknownItems()).build());

        QualityCostPolicy.Total total = QualityCostPolicy.total(List.of(rework, scrap, compensation));
        return com.migao.admin.dto.QualityCostView.builder()
                .startDate(startDate)
                .endDate(endDate)
                .components(components)
                .total(total.amount())
                .complete(total.complete())
                .unknownComponents(total.unknownComponents())
                .build();
    }

    /**
     * **应收账龄报表**（issue #7376 段 5，P1-4）：五档 + 按客户分行的报表读面。
     *
     * <p>与客户档案里的账龄页**同一份底稿**（{@link CustomerService#receivableAging(Long, String)} →
     * {@code ReceivableAging.summarize}）—— 报表不重算分档，只补三条报表口径：</p>
     *
     * <ol>
     *   <li><b>空数据 ≠ 0</b>：没有欠款单 ⇒ {@code hasData=false} 且 {@code totals=null}
     *       （页面写「暂无数据」，不是「应收 0.00」）；</li>
     *   <li><b>合计 = 明细之和</b>：{@code totals.outstanding} 取纯函数的 {@code totalOutstanding}
     *       （恒等式 {@code == Σ五档 == Σ客户行} 由 {@code ReceivableAging} 承担）；</li>
     *   <li><b>单数单列</b>：{@code totals.orderCount} = Σ五档的单数 —— 金额里读不出「欠了多少张单」。</li>
     * </ol>
     *
     * @param scopeOwnerId P0-4 数据范围：非空 ⇒ 只算本人创建的单（{@code self}）
     */
    public com.migao.admin.dto.ReceivableAgingReportView receivableAging(Long tenantId, String scopeOwnerId) {
        var base = customerService.receivableAging(tenantId, scopeOwnerId);
        boolean hasData = !base.getCustomers().isEmpty();
        int orderCount = base.getBuckets().stream()
                .mapToInt(com.migao.admin.dto.ReceivableAgingResponse.BucketAmount::getOrderCount)
                .sum();
        return com.migao.admin.dto.ReceivableAgingReportView.builder()
                .asOf(base.getAsOf())
                .hasData(hasData)
                .customerCount(base.getCustomers().size())
                .buckets(base.getBuckets())
                .customers(base.getCustomers())
                .totals(hasData ? com.migao.admin.dto.ReceivableAgingReportView.Totals.builder()
                        .outstanding(base.getTotalOutstanding())
                        .overdue(base.getTotalOverdue())
                        .orderCount(orderCount)
                        .build() : null)   // 🔴 空数据 ⇒ null（不是 0）
                .build();
    }

    /**
     * **质量成本的维度汇总**（issue #7377 段 5）：把返工工时与赔付按「客户」或「工序」摊开。
     *
     * <p>🔴 恒等式 {@code 整表合计 == Σ行 + 未归属}：关联不上的金额**必须露出来**并写明原因 ——
     * 悄悄丢掉会让「各行之和」比整表小，而每行单看都正常。</p>
     *
     * <p>各维度可归因性：客户 = 返工走「报工 → 加工单 → 订单 → 客户」、赔付走「退款流水 → 订单 → 客户」；
     * 工序 = 返工直接取报工行的工序名，**赔付流水没有工序信息** ⇒ 工序维度下赔付整体进未归属。</p>
     *
     * @param dimension `customer` 或 `process`（其它值 ⇒ 400，不静默返回空）
     */
    public com.migao.admin.dto.QualityCostBreakdownView qualityCostBreakdown(
            String dimension, String startDate, String endDate) {
        String dim = dimension == null ? "" : dimension.trim();
        if (!"customer".equals(dim) && !"process".equals(dim)) {
            throw com.migao.admin.exception.BusinessException.validationError(
                    "不支持的质量成本维度（只支持 customer / process）：" + dim);
        }
        LocalDate from = parseDay(startDate);
        LocalDate to = parseDay(endDate);
        boolean byProcess = "process".equals(dim);

        java.util.Map<String, com.migao.admin.dto.QualityCostBreakdownView.Row> rows = new java.util.LinkedHashMap<>();
        int unpricedLines = 0;
        BigDecimal unattributedRework = BigDecimal.ZERO;
        int unattributedReworkLines = 0;

        for (com.migao.admin.entity.ProductionWorkLog log : productionWorkLogMapper.selectList(
                new LambdaQueryWrapper<com.migao.admin.entity.ProductionWorkLog>()
                        .eq(com.migao.admin.entity.ProductionWorkLog::getWorkType, "rework"))) {
            if (!inWindow(workDay(log), from, to)) {
                continue;
            }
            if ("unpriced".equals(log.getPriceState()) || log.getUnitPrice() == null) {
                unpricedLines++;   // 🔴 未定价不计金额（与整表同口径）
                continue;
            }
            BigDecimal amount = log.getUnitPrice().multiply(
                    log.getQty() == null ? BigDecimal.ZERO : log.getQty());
            com.migao.admin.dto.QualityCostBreakdownView.Row row =
                    byProcess ? rowForProcess(rows, log) : rowForCustomer(rows, log);
            if (row == null) {
                unattributedRework = unattributedRework.add(amount);
                unattributedReworkLines++;
            } else {
                row.setRework(row.getRework().add(amount));
                row.setReworkLines(row.getReworkLines() + 1);
            }
        }

        BigDecimal unattributedCompensation = BigDecimal.ZERO;
        int unattributedCompensationCount = 0;
        for (com.migao.admin.entity.FinanceTransaction refund : financeTransactionMapper.selectList(
                new LambdaQueryWrapper<com.migao.admin.entity.FinanceTransaction>()
                        .eq(com.migao.admin.entity.FinanceTransaction::getType, "refund")
                        .eq(com.migao.admin.entity.FinanceTransaction::getStatus, "success"))) {
            if (!inWindow(txnDay(refund), from, to)) {
                continue;
            }
            BigDecimal amount = refund.getAmount() == null ? BigDecimal.ZERO : refund.getAmount();
            // 🔴 退款流水没有工序信息 ⇒ 工序维度下赔付**整体**进未归属（不是「赔付为 0」）
            com.migao.admin.dto.QualityCostBreakdownView.Row row =
                    byProcess ? null : rowForCustomerOrder(rows, refund.getOrderId());
            if (row == null) {
                unattributedCompensation = unattributedCompensation.add(amount);
                unattributedCompensationCount++;
            } else {
                row.setCompensation(row.getCompensation().add(amount));
                row.setCompensationCount(row.getCompensationCount() + 1);
            }
        }

        List<com.migao.admin.dto.QualityCostBreakdownView.Row> list = new ArrayList<>(rows.values());
        for (com.migao.admin.dto.QualityCostBreakdownView.Row row : list) {
            row.setTotal(row.getRework().add(row.getCompensation()));
        }
        list.sort((a, b) -> b.getTotal().compareTo(a.getTotal()));

        BigDecimal rowRework = BigDecimal.ZERO;
        BigDecimal rowCompensation = BigDecimal.ZERO;
        int rowReworkLines = 0;
        int rowCompensationCount = 0;
        for (com.migao.admin.dto.QualityCostBreakdownView.Row row : list) {
            rowRework = rowRework.add(row.getRework());
            rowCompensation = rowCompensation.add(row.getCompensation());
            rowReworkLines += row.getReworkLines();
            rowCompensationCount += row.getCompensationCount();
        }
        BigDecimal unattributedTotal = unattributedRework.add(unattributedCompensation);
        boolean hasData = !list.isEmpty() || unattributedTotal.signum() != 0
                || unattributedReworkLines > 0 || unattributedCompensationCount > 0;

        List<String> notes = new ArrayList<>();
        notes.add("报废料不在本视图：本仓未采集（质检只到成品帘级），摊到任何维度都是编数");
        if (byProcess) {
            notes.add("赔付（退款口径）没有工序信息 ⇒ 全部计入「无法归属」（不是「赔付为 0」）");
        } else {
            notes.add("返工经「报工 → 加工单 → 订单 → 客户」归属；赔付经「退款流水 → 订单 → 客户」归属");
        }
        if (unpricedLines > 0) {
            notes.add("另有 " + unpricedLines + " 行未定价返工报工未计入金额（未定价 ≠ 0 元）");
        }

        return com.migao.admin.dto.QualityCostBreakdownView.builder()
                .dimension(dim)
                .scope(byProcess ? "rework_by_processing_operation" : "rework_and_compensation_by_customer")
                .startDate(startDate)
                .endDate(endDate)
                .hasData(hasData)
                .rows(list)
                .totals(!hasData ? null : com.migao.admin.dto.QualityCostBreakdownView.Totals.builder()
                        .rework(scale2(rowRework.add(unattributedRework)))
                        .reworkLines(rowReworkLines + unattributedReworkLines)
                        .compensation(scale2(rowCompensation.add(unattributedCompensation)))
                        .compensationCount(rowCompensationCount + unattributedCompensationCount)
                        .total(scale2(rowRework.add(rowCompensation).add(unattributedTotal)))
                        .build())
                .unattributed(com.migao.admin.dto.QualityCostBreakdownView.Unattributed.builder()
                        .rework(scale2(unattributedRework))
                        .reworkLines(unattributedReworkLines)
                        .compensation(scale2(unattributedCompensation))
                        .compensationCount(unattributedCompensationCount)
                        .total(scale2(unattributedTotal))
                        .reason(byProcess
                                ? "这些返工报工没记工序名；赔付流水本就没有工序字段"
                                : "这些返工报工关联不到加工单/订单，或退款流水关联不到订单")
                        .build())
                .notes(notes)
                .build();
    }

    /** 工序维度的一行：键 = 工序名（报工行直接带）。工序名缺失 ⇒ 返回 null（进未归属）。 */
    private com.migao.admin.dto.QualityCostBreakdownView.Row rowForProcess(
            java.util.Map<String, com.migao.admin.dto.QualityCostBreakdownView.Row> rows,
            com.migao.admin.entity.ProductionWorkLog log) {
        String name = log.getOperationName();
        if (!StringUtils.hasText(name)) {
            return null;
        }
        return rows.computeIfAbsent("op:" + name,
                k -> newRow(name, name));
    }

    /** 客户维度的一行：报工 → 加工单 → 订单 → 客户；任一环缺失 ⇒ null（进未归属）。 */
    private com.migao.admin.dto.QualityCostBreakdownView.Row rowForCustomer(
            java.util.Map<String, com.migao.admin.dto.QualityCostBreakdownView.Row> rows,
            com.migao.admin.entity.ProductionWorkLog log) {
        if (!StringUtils.hasText(log.getProcessingOrderId())) {
            return null;
        }
        com.migao.admin.entity.ProcessingOrder processingOrder =
                processingOrderMapper.selectById(log.getProcessingOrderId());
        if (processingOrder == null) {
            return null;
        }
        return rowForCustomerOrder(rows, processingOrder.getOrderId());
    }

    /** 客户维度的一行（订单 → 客户）。订单 id 缺失或查不到 ⇒ null。 */
    private com.migao.admin.dto.QualityCostBreakdownView.Row rowForCustomerOrder(
            java.util.Map<String, com.migao.admin.dto.QualityCostBreakdownView.Row> rows, String orderId) {
        if (!StringUtils.hasText(orderId)) {
            return null;
        }
        Order order = orderMapper.selectById(orderId);
        if (order == null) {
            return null;
        }
        String label = StringUtils.hasText(order.getCustomerName())
                ? order.getCustomerName() : order.getCustomerPhone();
        if (!StringUtils.hasText(label)) {
            return null;
        }
        String key = "cus:" + (StringUtils.hasText(order.getCustomerPhone())
                ? order.getCustomerPhone() : label);
        return rows.computeIfAbsent(key, k -> newRow(key, label));
    }

    private static com.migao.admin.dto.QualityCostBreakdownView.Row newRow(String key, String label) {
        return com.migao.admin.dto.QualityCostBreakdownView.Row.builder()
                .key(key).label(label)
                .rework(BigDecimal.ZERO).reworkLines(0)
                .compensation(BigDecimal.ZERO).compensationCount(0)
                .total(BigDecimal.ZERO)
                .build();
    }

    private static BigDecimal scale2(BigDecimal value) {
        return (value == null ? BigDecimal.ZERO : value)
                .setScale(2, java.math.RoundingMode.HALF_UP);
    }

    /** 报工行的业务日（`workDate` 缺失 ⇒ 用创建时刻按业务时区换算，与 #3802 同一口径）。 */
    private LocalDate workDay(com.migao.admin.entity.ProductionWorkLog log) {
        if (log.getWorkDate() != null) {
            return log.getWorkDate();
        }
        return log.getCreatedAt() == null ? null
                : LocalDate.ofInstant(log.getCreatedAt().toInstant(), businessClock.zone());
    }

    /** 退款流水的业务日（`occurredAt` 缺失 ⇒ 用创建时刻）。 */
    private LocalDate txnDay(com.migao.admin.entity.FinanceTransaction txn) {
        if (txn.getOccurredAt() != null) {
            return LocalDate.ofInstant(txn.getOccurredAt().toInstant(), businessClock.zone());
        }
        return txn.getCreatedAt() == null ? null
                : LocalDate.ofInstant(txn.getCreatedAt().toInstant(), businessClock.zone());
    }

    /**
     * 可选窗口：`from`/`to` 为 null 表示该侧不设界。
     *
     * <p>🔴 日期缺失（null）⇒ **计入**（「无法判窗」不等于「窗外」）：生产库上
     * `production_work_logs.work_date` 是 NOT NULL、`finance_transactions.created_at` 有默认值，
     * 真出现空日期只可能是异常存量 —— 此时漏算比多算更危险（前者让质量成本凭空变小）。</p>
     */
    private static boolean inWindow(LocalDate day, LocalDate from, LocalDate to) {
        if (day == null) {
            return true;
        }
        if (from != null && day.isBefore(from)) {
            return false;
        }
        return to == null || !day.isAfter(to);
    }

    private static LocalDate parseDay(String date) {
        return StringUtils.hasText(date) ? LocalDate.parse(date.trim()) : null;
    }

    private static OffsetDateTime startOfDay(String date, ZoneId zone) {
        return LocalDate.parse(date.trim()).atStartOfDay(zone).toOffsetDateTime();
    }
}
