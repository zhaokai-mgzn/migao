package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.StockBatchConsumption;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchConsumptionMapper;
import com.migao.admin.mapper.StockBatchMapper;
import com.migao.admin.mapper.StockLedgerMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 批次消耗台账服务（V116，issue #5145 阶段 1）—— 派工扣批次的**写面**与批次账的**读面**。
 *
 * <h2>两本账（用户裁定「路线 A」，本单不再讨论）</h2>
 * <ul>
 *   <li><b>SKU 账 = 销售账</b>：{@code product_skus.stock}，随支付扣（{@code OrderService.confirmPayment}）
 *       —— 本单<b>一字不动</b>（「不能损失客户」的命门）。</li>
 *   <li><b>批次账 = 实物账</b>：本服务，随**加工单生成**扣、随**加工单作废**回补。</li>
 * </ul>
 * 两账必然有差额（已售未派 / 公式口径 vs 实际 / 存量无批次来源）⇒ 路线 A 的**交换条件**是
 * {@link #reconcile} 这个读面：差额必须**读得出、可解释**，不得静默漂移。
 *
 * <h2>余量是派生值</h2>
 * {@code remaining = stock_batches.quantity + Σ(delta)} —— **不原地改** {@code stock_batches.quantity}
 * （V111 裁定「批次行不可改、冲销走新单据」）。{@code delta} 带符号：负 = 扣减、正 = 回补。
 *
 * <h2>写面分两段（plan → apply）—— 为什么必须分开</h2>
 * {@code ProcessingOrderService.generate} 逐单 {@code catch (BusinessException)} 记账后继续处理其余单，
 * 而**异常不逸出事务边界 ⇒ 不会回滚**。⇒ 若在写库之后再抛业务异常，就会留下「有加工单、扣了半截」
 * 的半成品（同 #4116 对工序实例 payload 的处置）。故本服务的纪律是：
 * <b>{@link #plan} 只读校验（任何业务异常都在这里抛完）；{@link #apply} 只落账、不再抛业务异常。</b>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class StockBatchConsumptionService {

    /** 变更来源：派加工单扣减 */
    public static final String REASON_PROCESSING_ORDER = StockBatchConsumption.REASON_PROCESSING_ORDER;
    /** 变更来源：加工单作废回补 */
    public static final String REASON_PROCESSING_ORDER_CANCELLED =
            StockBatchConsumption.REASON_PROCESSING_ORDER_CANCELLED;

    /** 批次不存在 / 不属于当前租户（错误码，可被前端与 agent 判读） */
    public static final String ERR_BATCH_NOT_FOUND = "BATCH_NOT_FOUND";
    /** 批次不属于该 SKU（指定错了货） */
    public static final String ERR_BATCH_SKU_MISMATCH = "BATCH_SKU_MISMATCH";
    /** 批次余量不足（fail-closed：**不得静默少扣**） */
    public static final String ERR_BATCH_STOCK_INSUFFICIENT = "BATCH_STOCK_INSUFFICIENT";

    /** 阶段 1 的建议值口径（**朴素**，显式回给读的人 —— 阶段 2 才换 best-fit，见 #5144） */
    public static final String SUGGESTION_RULE_FIFO = "FIFO_RECEIVED_DATE";

    private static final BigDecimal LE_0_2 = new BigDecimal("0.2");
    private static final BigDecimal LE_0_5 = new BigDecimal("0.5");
    private static final BigDecimal LE_1 = new BigDecimal("1");

    private final StockBatchMapper stockBatchMapper;
    private final StockBatchConsumptionMapper consumptionMapper;
    private final ProductSkuMapper productSkuMapper;
    private final StockLedgerMapper stockLedgerMapper;

    // ══════════════════════════════════════════════════════════════════════════════════
    // 写面 ① plan —— 只读校验（全部业务异常在此抛完）
    // ══════════════════════════════════════════════════════════════════════════════════

    /**
     * 派工指定批次的一行（由 {@code ProcessingOrderService} 从加工单快照行的**该行米数**算出）。
     *
     * <p>{@code skuId} **不在入参里**：**批次的 SKU 才是权威**（批次由入库产生、SKU 固定不变），
     * 而订单行侧只带得出 {@code skuCode}（{@code processing_info.sku}）。
     * 用「订单行 skuCode vs 批次 skuCode」做一致性判据，比从订单行反解 skuId 少一层猜测
     * （反解要靠 {@code OrderService.matchSkuId} 那套匹配，那是销售腿的口径）。</p>
     *
     * @param orderItemId 订单明细行 id（= 快照行的 itemId，唯一标识「哪一行」）
     * @param batchNo     文员指定的批次号（**人工最终选择**，不是建议值）
     * @param meters      该行要扣的米数（口径 = 订单行数量向上进位到 0.1，与销售账扣减**同一个函数**）
     */
    public record Designation(String orderItemId, String productId, String skuCode,
                              String batchNo, BigDecimal meters) {
    }

    /** 计划里的一行（已校验「批次存在 / 属于该 SKU / 余量足够」；apply 只负责落账） */
    public record Deduction(Long batchId, String batchNo, String productId, Long skuId, String skuCode,
                            String orderItemId, BigDecimal meters, BigDecimal remainingBefore) {
    }

    /**
     * 校验并规划派工扣减（**只读**，不写任何一行）。
     *
     * <p>三条 fail-closed 判据（缺料不静默的全部内容）：批次必须在（同租户）→ 必须属于该 SKU →
     * 余量必须够本行米数。<b>不足 ⇒ 抛 {@link #ERR_BATCH_STOCK_INSUFFICIENT} + 可行动建议</b>
     * （列出同 SKU 的有余量批次），绝不「有多少扣多少」。</p>
     *
     * <p>同一批次被多行指定时按**累积**判余量（不是逐行各自判）——否则两行各 3 米会把只剩 5 米的批次扣成 -1。</p>
     */
    public List<Deduction> plan(Long tenantId, List<Designation> designations) {
        if (designations == null || designations.isEmpty()) {
            return List.of();
        }
        Set<String> batchNos = new LinkedHashSet<>();
        for (Designation d : designations) {
            if (StringUtils.hasText(d.batchNo())) {
                batchNos.add(d.batchNo().trim());
            }
        }
        Map<String, StockBatch> byNo = new LinkedHashMap<>();
        if (!batchNos.isEmpty()) {
            for (StockBatch b : stockBatchMapper.selectList(new LambdaQueryWrapper<StockBatch>()
                    .eq(StockBatch::getTenantId, tenantId)
                    .eq(StockBatch::getDeleted, 0)
                    .in(StockBatch::getBatchNo, batchNos))) {
                byNo.put(b.getBatchNo(), b);
            }
        }
        List<Long> batchIds = new ArrayList<>();
        for (StockBatch b : byNo.values()) {
            batchIds.add(b.getId());
        }
        // 累积口径：running = 「该批次已消耗净额」（负数为扣减）—— 同一批次被多行指定时逐行递减
        Map<Long, BigDecimal> running = new HashMap<>(consumedByBatchId(tenantId, batchIds));

        List<Deduction> plan = new ArrayList<>();
        for (Designation d : designations) {
            StockBatch batch = StringUtils.hasText(d.batchNo()) ? byNo.get(d.batchNo().trim()) : null;
            if (batch == null) {
                throw new BusinessException(ERR_BATCH_NOT_FOUND,
                        String.format("批次 %s 不存在或不属于当前租户", d.batchNo()), 400,
                        "请刷新候选批次列表后重新选择；批次只能由入库单过账产生");
            }
            if (!batch.getProductId().equals(d.productId())) {
                throw new BusinessException(ERR_BATCH_SKU_MISMATCH,
                        String.format("批次 %s 属于商品 %s，与订单明细行的商品不一致",
                                batch.getBatchNo(), batch.getProductId()), 400,
                        "请选择与该行商品一致的批次");
            }
            if (StringUtils.hasText(d.skuCode()) && StringUtils.hasText(batch.getSkuCode())
                    && !batch.getSkuCode().equals(d.skuCode())) {
                throw new BusinessException(ERR_BATCH_SKU_MISMATCH,
                        String.format("批次 %s 属于 SKU %s，与订单明细行指定的 SKU %s 不一致",
                                batch.getBatchNo(), batch.getSkuCode(), d.skuCode()), 400,
                        "请选择与该行颜色/门幅一致的批次");
            }
            BigDecimal meters = StockQuantity.orZero(d.meters());
            BigDecimal before = StockQuantity.orZero(batch.getQuantity())
                    .add(running.getOrDefault(batch.getId(), BigDecimal.ZERO));
            if (before.compareTo(meters) < 0) {
                throw new BusinessException(ERR_BATCH_STOCK_INSUFFICIENT,
                        String.format("批次 %s 余量不足：可用 %s 米，本行需要 %s 米",
                                batch.getBatchNo(), plain(before), plain(meters)), 409,
                        availableHint(tenantId, d.productId(), batch.getSkuId(), batch.getId(), meters));
            }
            running.put(batch.getId(), before.subtract(meters).subtract(StockQuantity.orZero(batch.getQuantity())));
            plan.add(new Deduction(batch.getId(), batch.getBatchNo(), batch.getProductId(),
                    batch.getSkuId(),
                    StringUtils.hasText(batch.getSkuCode()) ? batch.getSkuCode() : d.skuCode(),
                    d.orderItemId(), meters, before));
        }
        return plan;
    }

    /**
     * 落账（**只插入**，不抛业务异常 —— 见类注释「写面分两段」）。
     *
     * @return 落账行数（0 = 本单没有指定任何批次 ⇒ 行为与今天逐字相同）
     */
    public int apply(Long tenantId, String processingOrderNo, String orderNo, List<Deduction> plan) {
        if (plan == null || plan.isEmpty()) {
            return 0;
        }
        for (Deduction d : plan) {
            BigDecimal delta = d.meters().negate();
            consumptionMapper.insert(StockBatchConsumption.builder()
                    .tenantId(tenantId)
                    .batchId(d.batchId())
                    .batchNo(d.batchNo())
                    .productId(d.productId())
                    .skuId(d.skuId())
                    .skuCode(d.skuCode())
                    .delta(delta)
                    .beforeQty(d.remainingBefore())
                    .afterQty(d.remainingBefore().add(delta))
                    .reason(REASON_PROCESSING_ORDER)
                    .processingOrderNo(processingOrderNo)
                    .orderNo(orderNo)
                    .orderItemId(d.orderItemId())
                    .operator(StockLedgerService.resolveOperator())
                    .note("生成加工单指定批次扣减")
                    .createdAt(OffsetDateTime.now())
                    .build());
        }
        log.info("派工扣批次库存: po={}, orderNo={}, tenant={}, lines={}, meters={}",
                processingOrderNo, orderNo, tenantId, plan.size(),
                plain(StockQuantity.sum(plan.stream().map(Deduction::meters).toList())));
        return plan.size();
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 写面 ② reverse —— 作废回补（同事务、幂等、可重跑）
    // ══════════════════════════════════════════════════════════════════════════════════

    /**
     * 加工单作废 ⇒ 回补该单扣过的每一个批次（**逐值对称**：回补量 = 原扣减量的相反数）。
     *
     * <p><b>幂等 / 可重跑</b>：已经回补过的行（按 {@code 批次 × 明细行} 配对）直接跳过 ——
     * 第二遍调用返回 0 而不是撞唯一键报错。DB 侧另有 {@code uk_batch_consumption_line} 兜底。</p>
     *
     * <p><b>fail-closed</b>：原扣减行引用的批次查不到 ⇒ 抛错（批次行不可删，出现即账坏了；
     * 静默跳过会让「回补了」与「没回补」长得一样）。</p>
     *
     * @return 本次真正回补的行数（0 = 该单没有批次扣减 / 已经全部回补过）
     */
    @Transactional(rollbackFor = Exception.class)
    public int reverse(Long tenantId, String processingOrderNo, String orderNo, String note) {
        List<StockBatchConsumption> consumed = consumptionMapper.selectList(
                new LambdaQueryWrapper<StockBatchConsumption>()
                        .eq(StockBatchConsumption::getTenantId, tenantId)
                        .eq(StockBatchConsumption::getProcessingOrderNo, processingOrderNo)
                        .eq(StockBatchConsumption::getReason, REASON_PROCESSING_ORDER)
                        .eq(StockBatchConsumption::getDeleted, 0));
        if (consumed.isEmpty()) {
            return 0;
        }
        List<StockBatchConsumption> already = consumptionMapper.selectList(
                new LambdaQueryWrapper<StockBatchConsumption>()
                        .eq(StockBatchConsumption::getTenantId, tenantId)
                        .eq(StockBatchConsumption::getProcessingOrderNo, processingOrderNo)
                        .eq(StockBatchConsumption::getReason, REASON_PROCESSING_ORDER_CANCELLED)
                        .eq(StockBatchConsumption::getDeleted, 0));
        Set<String> done = new LinkedHashSet<>();
        for (StockBatchConsumption r : already) {
            done.add(lineKey(r.getBatchId(), r.getOrderItemId()));
        }
        List<Long> batchIds = new ArrayList<>();
        for (StockBatchConsumption c : consumed) {
            batchIds.add(c.getBatchId());
        }
        Map<Long, StockBatch> batches = new LinkedHashMap<>();
        for (StockBatch b : stockBatchMapper.selectList(new LambdaQueryWrapper<StockBatch>()
                .eq(StockBatch::getTenantId, tenantId)
                .in(StockBatch::getId, batchIds))) {
            batches.put(b.getId(), b);
        }
        Map<Long, BigDecimal> running = new HashMap<>(consumedByBatchId(tenantId, batchIds));

        int rows = 0;
        for (StockBatchConsumption c : consumed) {
            if (done.contains(lineKey(c.getBatchId(), c.getOrderItemId()))) {
                continue; // 幂等：该行已回补过 ⇒ 跳过（可重跑）
            }
            StockBatch batch = batches.get(c.getBatchId());
            if (batch == null) {
                throw new BusinessException(ERR_BATCH_NOT_FOUND,
                        String.format("回补失败：批次 id=%s（%s）不存在 —— 批次行不可删，出现即账目异常",
                                c.getBatchId(), c.getBatchNo()), 409,
                        "请人工核对 stock_batch_consumptions 与该批次；不要手工删台账行");
            }
            BigDecimal before = StockQuantity.orZero(batch.getQuantity())
                    .add(running.getOrDefault(batch.getId(), BigDecimal.ZERO));
            BigDecimal delta = c.getDelta().negate();
            consumptionMapper.insert(StockBatchConsumption.builder()
                    .tenantId(tenantId)
                    .batchId(c.getBatchId())
                    .batchNo(c.getBatchNo())
                    .productId(c.getProductId())
                    .skuId(c.getSkuId())
                    .skuCode(c.getSkuCode())
                    .delta(delta)
                    .beforeQty(before)
                    .afterQty(before.add(delta))
                    .reason(REASON_PROCESSING_ORDER_CANCELLED)
                    .processingOrderNo(processingOrderNo)
                    .orderNo(orderNo != null ? orderNo : c.getOrderNo())
                    .orderItemId(c.getOrderItemId())
                    .operator(StockLedgerService.resolveOperator())
                    .note(note)
                    .createdAt(OffsetDateTime.now())
                    .build());
            // running 的口径 = 「Σdelta」（不是余量）⇒ 回补一行就是加一次 delta
            // （余量 = stock_batches.quantity + Σdelta，公式只有这一处）
            running.put(batch.getId(), running.getOrDefault(batch.getId(), BigDecimal.ZERO).add(delta));
            rows++;
        }
        if (rows > 0) {
            log.info("加工单作废回补批次库存: po={}, tenant={}, rows={}", processingOrderNo, tenantId, rows);
        }
        return rows;
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 读面
    // ══════════════════════════════════════════════════════════════════════════════════

    /**
     * 批次余量列表（派生 = 入库量 + Σ消耗）。
     *
     * @param onlyAvailable true ⇒ 只回余量 &gt; 0 的批次（派工候选/「还有哪些能用」）
     */
    public List<BatchStockViews.BatchRemaining> remaining(Long tenantId, String productId, Long skuId,
                                                          boolean onlyAvailable) {
        List<StockBatch> batches = listBatches(tenantId, productId, skuId);
        Map<Long, BigDecimal> consumed = consumedByBatchId(tenantId, ids(batches));
        List<BatchStockViews.BatchRemaining> rows = new ArrayList<>();
        for (StockBatch b : batches) {
            BigDecimal used = consumed.getOrDefault(b.getId(), BigDecimal.ZERO);
            BigDecimal inbound = StockQuantity.orZero(b.getQuantity());
            BigDecimal rest = inbound.add(used);
            if (onlyAvailable && rest.compareTo(BigDecimal.ZERO) <= 0) {
                continue;
            }
            rows.add(new BatchStockViews.BatchRemaining(b.getId(), b.getBatchNo(), b.getProductId(),
                    b.getSkuId(), b.getSkuCode(), b.getInboundNo(), b.getDyeLot(), b.getReceivedDate(),
                    b.getUnitCost(), plain(inbound), plain(used.negate()), plain(rest)));
        }
        return rows;
    }

    /**
     * 剩余量分布（四档 `≤0.2m / 0.2~0.5m / 0.5~1m / &gt;1m`，按批次数与占比）。
     *
     * <p>这就是母单 #5144 的效果判据「更多批次剩余量落到 ≤0.2m」的读数面 —— 阶段 1 先把
     * **同口径的基线**记下来（阶段 2 的 best-fit 才有前后可比的东西）。</p>
     */
    public BatchStockViews.Distribution distribution(Long tenantId, String productId) {
        List<BatchStockViews.BatchRemaining> rows = remaining(tenantId, productId, null, false);
        int[] counts = new int[4];
        for (BatchStockViews.BatchRemaining r : rows) {
            counts[bucketIndex(r.remainingMeters())]++;
        }
        int total = rows.size();
        List<BatchStockViews.Bucket> buckets = new ArrayList<>();
        buckets.add(bucket("le_0_2", "≤0.2 米", counts[0], total));
        buckets.add(bucket("b0_2_0_5", "0.2~0.5 米", counts[1], total));
        buckets.add(bucket("b0_5_1", "0.5~1 米", counts[2], total));
        buckets.add(bucket("gt_1", ">1 米", counts[3], total));
        return new BatchStockViews.Distribution(total, buckets);
    }

    /**
     * 对账读面（**路线 A 的交换条件**）：{@code Σ批次余量} 与 {@code product_skus.stock} 的差额。
     *
     * <p>恒等式与各腿的含义见 {@link BatchStockViews.ReconcileRow}。{@code reconciled=false}
     * 表示恒等式不成立（有批次/台账落到了读面覆盖不到的地方）——**读得出，不是静默**。</p>
     */
    public BatchStockViews.Reconcile reconcile(Long tenantId, String productId, Long skuId) {
        List<StockBatch> batches = listBatches(tenantId, productId, skuId);
        Map<Long, BigDecimal> consumed = consumedByBatchId(tenantId, ids(batches));
        // 逐 SKU 聚：入库总米数 / 批次余量
        Map<Long, BigDecimal> inboundBySku = new LinkedHashMap<>();
        Map<Long, BigDecimal> remainingBySku = new LinkedHashMap<>();
        Map<Long, String> skuCodes = new LinkedHashMap<>();
        for (StockBatch b : batches) {
            if (b.getSkuId() == null) {
                continue;
            }
            BigDecimal inbound = StockQuantity.orZero(b.getQuantity());
            inboundBySku.merge(b.getSkuId(), inbound, BigDecimal::add);
            remainingBySku.merge(b.getSkuId(), inbound.add(consumed.getOrDefault(b.getId(), BigDecimal.ZERO)),
                    BigDecimal::add);
            if (StringUtils.hasText(b.getSkuCode())) {
                skuCodes.putIfAbsent(b.getSkuId(), b.getSkuCode());
            }
        }
        // 派工扣减净额（逐 SKU）
        Map<Long, BigDecimal> dispatchedBySku = new LinkedHashMap<>();
        for (StockBatchConsumptionMapper.SkuDeltaSum sum : consumptionMapper.sumDeltaBySku(tenantId)) {
            dispatchedBySku.merge(sum.getSkuId(), StockQuantity.orZero(sum.getDeltaSum()).negate(),
                    BigDecimal::add);
        }
        // 销售账分腿（逐 SKU）
        Map<Long, StockLedgerMapper.SkuLedgerSum> ledger = new LinkedHashMap<>();
        for (StockLedgerMapper.SkuLedgerSum sum : stockLedgerMapper.sumBySku(tenantId)) {
            ledger.put(sum.getSkuId(), sum);
        }

        List<ProductSku> skus = productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getTenantId, tenantId)
                .eq(ProductSku::getProductId, productId)
                .eq(skuId != null, ProductSku::getId, skuId));
        List<BatchStockViews.ReconcileRow> rows = new ArrayList<>();
        BigDecimal totalDiff = BigDecimal.ZERO;
        int unreconciled = 0;
        for (ProductSku sku : skus) {
            BigDecimal inbound = inboundBySku.getOrDefault(sku.getId(), BigDecimal.ZERO);
            BigDecimal dispatched = dispatchedBySku.getOrDefault(sku.getId(), BigDecimal.ZERO);
            BigDecimal batchRemaining = remainingBySku.getOrDefault(sku.getId(), BigDecimal.ZERO);
            // 只列出「与批次账有关」的 SKU（从未入库过的 SKU 没有批次来源，差额恒为 −stock，读它无意义）
            if (inbound.compareTo(BigDecimal.ZERO) == 0 && dispatched.compareTo(BigDecimal.ZERO) == 0) {
                continue;
            }
            BigDecimal stock = StockQuantity.orZero(sku.getStock());
            StockLedgerMapper.SkuLedgerSum l = ledger.get(sku.getId());
            BigDecimal soldDeducted = l == null ? BigDecimal.ZERO : StockQuantity.orZero(l.getSoldDeducted());
            BigDecimal otherDelta = l == null ? BigDecimal.ZERO : StockQuantity.orZero(l.getOtherDelta());
            BigDecimal totalDelta = l == null ? BigDecimal.ZERO : StockQuantity.orZero(l.getTotalDelta());
            BigDecimal unbatched = stock.subtract(totalDelta);
            BigDecimal diff = batchRemaining.subtract(stock);
            BigDecimal explained = soldDeducted.subtract(dispatched).subtract(otherDelta);
            boolean ok = diff.compareTo(explained.subtract(unbatched)) == 0;
            if (!ok) {
                unreconciled++;
                log.warn("批次账对账不平: tenant={}, skuId={}, diff={}, explained={}, unbatched={}",
                        tenantId, sku.getId(), plain(diff), plain(explained), plain(unbatched));
            }
            totalDiff = totalDiff.add(diff);
            rows.add(new BatchStockViews.ReconcileRow(sku.getId(),
                    StringUtils.hasText(sku.getSkuCode()) ? sku.getSkuCode() : skuCodes.get(sku.getId()),
                    sku.getProductId(), plain(stock), plain(batchRemaining), plain(inbound),
                    plain(dispatched), plain(soldDeducted), plain(otherDelta), plain(unbatched),
                    plain(diff), plain(explained), ok));
        }
        return new BatchStockViews.Reconcile(rows, plain(totalDiff), unreconciled);
    }

    /**
     * 派工候选批次 + 建议值（生成加工单界面用）。
     *
     * <p><b>建议值口径 = 朴素 FIFO</b>（入库日期早者优先，同日按 id）：阶段 1 只记录、不改指派行为，
     * 故这里**刻意不做** best-fit（那是 #5144 阶段 2）。{@code suggestionRule} 显式回口径，
     * 免得读的人把朴素值当成智能指派。</p>
     */
    public BatchStockViews.Candidates candidates(Long tenantId, String productId, Long skuId,
                                                 BigDecimal requiredMeters) {
        List<BatchStockViews.BatchRemaining> rows = remaining(tenantId, productId, skuId, true);
        BigDecimal need = StockQuantity.orZero(requiredMeters);
        String suggested = null;
        List<BatchStockViews.Candidate> candidates = new ArrayList<>();
        for (BatchStockViews.BatchRemaining r : rows) {
            boolean enough = r.remainingMeters().compareTo(need) >= 0;
            boolean isSuggested = suggested == null && enough;
            if (isSuggested) {
                suggested = r.batchNo();
            }
            candidates.add(new BatchStockViews.Candidate(r.batchNo(), r.remainingMeters(),
                    r.receivedDate(), r.dyeLot(), r.inboundNo(), r.unitCost(), isSuggested, enough));
        }
        return new BatchStockViews.Candidates(SUGGESTION_RULE_FIFO, suggested, plain(need), candidates);
    }

    /** 消耗台账分页（判据：**按批次 / 加工单 / 订单**都能查回来）。 */
    public PageResponse<StockBatchConsumption> consumptionPage(Long tenantId, String batchNo,
                                                              String processingOrderNo, String orderNo,
                                                              long page, long size) {
        Page<StockBatchConsumption> result = consumptionMapper.selectPage(new Page<>(page, size),
                new LambdaQueryWrapper<StockBatchConsumption>()
                        .eq(StockBatchConsumption::getTenantId, tenantId)
                        .eq(StringUtils.hasText(batchNo), StockBatchConsumption::getBatchNo, batchNo)
                        .eq(StringUtils.hasText(processingOrderNo),
                                StockBatchConsumption::getProcessingOrderNo, processingOrderNo)
                        .eq(StringUtils.hasText(orderNo), StockBatchConsumption::getOrderNo, orderNo)
                        .orderByDesc(StockBatchConsumption::getId));
        return PageResponse.of(result);
    }

    /**
     * 某加工单逐明细行的批次指派（工人端读面用：`order_item_id → {batch_no, batch_meters}`）。
     *
     * <p>同一行同一批次可能既有扣减又有回补（作废后重新生成）⇒ 取**净额**；
     * 净额为 0（已完全回补）⇒ 该行**不出现在结果里**（工人不该被告知去裁一个已经不扣账的批次）。</p>
     */
    public Map<String, BatchAssignment> assignmentsOf(Long tenantId, String processingOrderNo) {
        if (!StringUtils.hasText(processingOrderNo)) {
            return Map.of();
        }
        List<StockBatchConsumption> rows = consumptionMapper.selectList(
                new LambdaQueryWrapper<StockBatchConsumption>()
                        .eq(StockBatchConsumption::getTenantId, tenantId)
                        .eq(StockBatchConsumption::getProcessingOrderNo, processingOrderNo)
                        .eq(StockBatchConsumption::getDeleted, 0)
                        .orderByAsc(StockBatchConsumption::getId));
        Map<String, BatchAssignment> out = new LinkedHashMap<>();
        for (StockBatchConsumption c : rows) {
            BatchAssignment current = out.get(c.getOrderItemId());
            BigDecimal meters = StockQuantity.orZero(c.getDelta()).negate();
            if (current == null) {
                out.put(c.getOrderItemId(), new BatchAssignment(c.getBatchNo(), meters));
            } else {
                out.put(c.getOrderItemId(), new BatchAssignment(current.batchNo(),
                        current.meters().add(meters)));
            }
        }
        out.entrySet().removeIf(e -> e.getValue().meters().compareTo(BigDecimal.ZERO) == 0);
        return out;
    }

    /** 工人端一行：批次号 + 该行的裁剪米数（净额） */
    public record BatchAssignment(String batchNo, BigDecimal meters) {
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 内部
    // ══════════════════════════════════════════════════════════════════════════════════

    private List<StockBatch> listBatches(Long tenantId, String productId, Long skuId) {
        return stockBatchMapper.selectList(new LambdaQueryWrapper<StockBatch>()
                .eq(StockBatch::getTenantId, tenantId)
                .eq(StockBatch::getDeleted, 0)
                .eq(StringUtils.hasText(productId), StockBatch::getProductId, productId)
                .eq(skuId != null, StockBatch::getSkuId, skuId)
                // 建议值口径 = 入库日期先进先出（同日按 id）；未记收货日期的排最后（不猜日期）
                .orderByAsc(StockBatch::getReceivedDate)
                .orderByAsc(StockBatch::getId));
    }

    private Map<Long, BigDecimal> consumedByBatchId(Long tenantId, Collection<Long> batchIds) {
        Map<Long, BigDecimal> out = new HashMap<>();
        if (batchIds == null || batchIds.isEmpty()) {
            return out;
        }
        for (StockBatchConsumptionMapper.BatchDeltaSum sum
                : consumptionMapper.sumDeltaByBatchIds(tenantId, batchIds)) {
            out.put(sum.getBatchId(), StockQuantity.orZero(sum.getDeltaSum()));
        }
        return out;
    }

    private static List<Long> ids(List<StockBatch> batches) {
        List<Long> ids = new ArrayList<>();
        for (StockBatch b : batches) {
            ids.add(b.getId());
        }
        return ids;
    }

    private static int bucketIndex(BigDecimal remaining) {
        BigDecimal r = StockQuantity.orZero(remaining);
        if (r.compareTo(LE_0_2) <= 0) {
            return 0;
        }
        if (r.compareTo(LE_0_5) <= 0) {
            return 1;
        }
        if (r.compareTo(LE_1) <= 0) {
            return 2;
        }
        return 3;
    }

    private static BatchStockViews.Bucket bucket(String key, String label, int count, int total) {
        BigDecimal share = total == 0
                ? BigDecimal.ZERO
                : BigDecimal.valueOf(count).divide(BigDecimal.valueOf(total), 4, RoundingMode.HALF_UP);
        return new BatchStockViews.Bucket(key, label, count, plain(share));
    }

    /** 缺料的可行动建议：同 SKU 还有哪些批次、各剩多少（fail-closed 不等于「只说不」） */
    private String availableHint(Long tenantId, String productId, Long skuId, Long excludeBatchId,
                                 BigDecimal needed) {
        List<BatchStockViews.BatchRemaining> rows = remaining(tenantId, productId, skuId, true);
        StringBuilder sb = new StringBuilder("该行需要 ")
                .append(plain(needed))
                .append(" 米。当前可用批次：");
        int shown = 0;
        for (BatchStockViews.BatchRemaining r : rows) {
            if (r.batchId().equals(excludeBatchId)) {
                continue;
            }
            if (shown++ == 3) {
                break;
            }
            sb.append(r.batchNo()).append("（剩 ").append(plain(r.remainingMeters())).append(" 米）");
            sb.append(shown == 1 ? "" : "、");
        }
        if (shown == 0) {
            sb.append("无（该 SKU 没有其它有余量的批次）");
        }
        return sb.append("。可选其它批次，或先入库补料后重新生成加工单（阶段 2 将支持拆多批次）。").toString();
    }

    private static String lineKey(Long batchId, String orderItemId) {
        return batchId + "#" + orderItemId;
    }

    /** 去掉无意义的尾零（`2.70` → `2.7`）：JSON 字面量与断言才好逐值比（同 StockQuantity 的口径）。 */
    private static BigDecimal plain(BigDecimal value) {
        return value == null ? null : StockQuantity.stripTrailingZerosPlain(value);
    }
}
