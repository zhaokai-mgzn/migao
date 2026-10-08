package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.BatchStocktakeRequest;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductSkuMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 按批次库存盘点（V143 / issue #5865，**最小录入式**）—— 实盘为准，差异落批次分录 + SKU 库存同事务对齐。
 *
 * <h2>它解决的问题（实证）</h2>
 * 盘点的写面此前只有 **Agent 面、SKU 粒度**的一条路（{@code ProductService.adjustStockForAgent}）：
 * 它改 {@code product_skus.stock} + 写销售台账，**完全不落批次** ⇒ 盘完之后
 * 「Σ批次余量 ≠ SKU 库存」恒成立，{@code /reconcile} 报得出差额却**没有配平路径**。
 * 本服务补的就是这条写面：**按批次**录实盘，差异同时落到两本账上。
 *
 * <h2>七条红线落在哪（逐条可核）</h2>
 * <ol>
 *   <li><b>不原地改 {@code stock_batches.quantity}</b>：本类**不注入** {@code StockBatchMapper} ——
 *       批次行根本不在它的可达面内；差异经
 *       {@link StockBatchConsumptionService#applyStocktake} 落成分录，派生余量自动跟上；</li>
 *   <li><b>批次分录与 SKU 库存同一事务</b>：{@link #stocktake} 是本类唯一的写入口，
 *       方法级 {@code @Transactional(rollbackFor = Exception.class)} ⇒ 任何一行失败整笔回滚
 *       （真库判据 {@code BatchStocktakeRealDbTest#secondBatchFailureLeavesNothingBehind} 用注入式失败证过）；</li>
 *   <li><b>来源可区分</b>：分录带 {@code reason='stocktake'} + {@code stocktake_run_id}，
 *       且三个扣料专属列留空（DB 约束 {@code ck_batch_consumption_source_shape} 两族形状互斥）；</li>
 *   <li><b>禁止负余量</b>：实盘 &lt; 0 ⇒ 400；盘后 SKU 库存 &lt; 0 ⇒ 422（都发生在**任何写入之前**）；</li>
 *   <li><b>幂等</b>：{@code delta = 0} ⇒ 零写入；同一 run id 的重放 / **并发**请求 ⇒ 该批次按
 *       「回放」出回执（读半边 {@link StockBatchConsumptionService#stocktakeRecordedBatchIds}
 *       + 写半边**原子闸** {@code StockBatchConsumptionMapper#insertStocktakeIfAbsent}
 *       = {@code ON CONFLICT DO NOTHING} 的部分唯一索引 {@code uk_batch_consumption_stocktake}）
 *       —— 并发时不抛唯一键异常、不冒泡成 500（issue #6301，判据
 *       {@code BatchStocktakeConcurrentRealDbTest#sameRunIdConcurrentRequestsAllGetIdempotentReceipt}）；</li>
 *   <li><b>不静默取整</b>：实盘米数一律过 {@link StockQuantity#requireOneDecimal}
 *       （超精度 / 负数显式 4xx，服务端绝不四舍五入、绝不截断）；</li>
 *   <li><b>对账差额不增大</b>：两本账按同一个 Σdelta 变化 ⇒
 *       {@code diff = Σ批次余量 − SKU 库存} 在盘点前后**恒等**（真库判据核过）。</li>
 * </ol>
 *
 * <h2>为什么是「盘前取派生余量」而不是先算一遍「应剩多少」</h2>
 * 「这批还剩多少」全仓只有一份口径（{@link StockBatchConsumptionService#remaining} =
 * 入库量 + Σdelta）。盘点差异 = 实盘 − 该口径的读数：任何第二份「应剩」算法都会与它漂移，
 * 而漂移的那一份不会变红 —— 所以这里直接调读面，不自己聚合 Σdelta。
 *
 * <h2>边界（如实登记，不粉饰）</h2>
 * <ul>
 *   <li>本类**不做**盘点单实体（无单号 / 状态 / 审批 / 打印）—— 用户 2026-10-01 选了 A 档；</li>
 *   <li>并发：两个**不同** run id 同时盘同一批次，理论上会各自基于同一盘前值记账（本仓既有派工
 *       路径同款：靠唯一索引防重复，不靠行锁）。**同一 run id** 的并发请求由原子闸
 *       {@code insertStocktakeIfAbsent} 判退 ⇒ 幂等回执（replayed）且**不再重复动 SKU 库存**
 *       （issue #6301）；</li>
 *   <li>跨货号一次提交不做（一次提交 = 一个货号；跨货号是两次提交，各自一个事务）。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class BatchStocktakeService {

    /** 实盘米数为负（红线 ④）；文案与库存链路的其它 4xx 同风格：说清原因 + 怎么改 */
    public static final String ERR_STOCKTAKE_NEGATIVE = "STOCKTAKE_ACTUAL_NEGATIVE";

    private final StockBatchConsumptionService batchStockService;
    private final ProductSkuMapper productSkuMapper;
    private final StockLedgerService stockLedgerService;

    /**
     * 提交一次盘点（最小录入式）：按货号，逐批次录实盘米数，差异落分录 + SKU 库存对齐。
     *
     * <p><b>校验全部先于写入</b>（fail-closed）：任何一行不合法 ⇒ 一个字节都不落
     * （真库判据核过；也让「第 2 个批次失败 ⇒ 第 1 个也不落」在**预校验**这一层就成立，
     * 事务边界再兜住「写入途中失败」的那一半）。</p>
     *
     * @param runId 幂等键（由调用方给；同一次提交的重复请求必须复用同一个值）
     * @return 逐行回执 + 汇总（{@code totalDelta} = 本次 SKU 库存的变化量）
     */
    @Transactional(rollbackFor = Exception.class)
    public BatchStockViews.StocktakeResult stocktake(Long tenantId, String productId, String runId,
                                                     List<BatchStocktakeRequest.Line> lines) {
        if (!StringUtils.hasText(productId)) {
            throw BusinessException.validationError("货号（productId）不能为空");
        }
        if (!StringUtils.hasText(runId)) {
            throw BusinessException.validationError(
                    "盘点运行标识 runId 不能为空（它是幂等键：同一次提交的重复请求必须用同一个值，"
                            + "否则网络重试会记第二笔）");
        }
        if (lines == null || lines.isEmpty()) {
            throw BusinessException.validationError("盘点明细不能为空：至少录一个批次的实盘米数");
        }

        // ① 逐行归一 + 准入 + 去重（**全部先于任何写入**）
        Map<Long, BigDecimal> wanted = new LinkedHashMap<>();
        for (BatchStocktakeRequest.Line line : lines) {
            if (line == null || line.getBatchId() == null) {
                throw BusinessException.validationError("盘点明细缺少批次 id（batchId）");
            }
            BigDecimal actual = StockQuantity.requireOneDecimal(line.getActualMeters(), "实盘米数 actualMeters");
            if (actual.signum() < 0) {
                throw new BusinessException(ERR_STOCKTAKE_NEGATIVE,
                        String.format("批次 %d 的实盘米数不能为负：%s", line.getBatchId(),
                                actual.toPlainString()), 400,
                        "实盘米数是「这一批现在实际还剩多少米」⇒ 最小是 0；报损请用库存调整并写清原因");
            }
            if (wanted.putIfAbsent(line.getBatchId(), actual) != null) {
                throw BusinessException.validationError(String.format(
                        "同一批次在本次盘点里出现了多次：批次 %d —— 请合并成一行后重试", line.getBatchId()));
            }
        }

        // ② 盘前余量 = **读面的派生余量**（全仓唯一口径；不自己聚合 Σdelta）
        Map<Long, BatchStockViews.BatchRemaining> byBatchId = new LinkedHashMap<>();
        for (BatchStockViews.BatchRemaining row
                : batchStockService.remaining(tenantId, productId, null, false)) {
            byBatchId.put(row.batchId(), row);
        }
        // ③ 幂等的读半边：本次运行已经记过账的批次 ⇒ 跳过（不双记）
        Set<Long> alreadyRecorded = batchStockService.stocktakeRecordedBatchIds(tenantId, runId);

        List<BatchStockViews.StocktakeLineResult> results = new ArrayList<>();
        List<StockBatchConsumptionService.StocktakeAdjustment> adjustments = new ArrayList<>();
        Map<Long, List<BatchStockViews.StocktakeLineResult>> perSku = new LinkedHashMap<>();
        BigDecimal totalDelta = BigDecimal.ZERO;
        int unchanged = 0;
        int replayed = 0;

        for (Map.Entry<Long, BigDecimal> entry : wanted.entrySet()) {
            BatchStockViews.BatchRemaining batch = byBatchId.get(entry.getKey());
            if (batch == null) {
                throw BusinessException.validationError(String.format(
                        "批次 %d 不属于货号 %s（或已被删除）—— 盘点只能盘该货号下的批次",
                        entry.getKey(), productId));
            }
            BigDecimal actual = entry.getValue();
            if (alreadyRecorded.contains(batch.batchId())) {
                replayed++;
                results.add(row(batch, actual, BigDecimal.ZERO, batch.remainingMeters(),
                        BatchStockViews.STOCKTAKE_REPLAYED));
                continue;
            }
            BigDecimal delta = actual.subtract(StockQuantity.orZero(batch.remainingMeters()));
            if (delta.signum() == 0) {
                // 红线 ⑤：实盘 == 余量 ⇒ **零写入**（不落分录、不落台账、不动 SKU 库存）
                unchanged++;
                results.add(row(batch, actual, BigDecimal.ZERO, batch.remainingMeters(),
                        BatchStockViews.STOCKTAKE_UNCHANGED));
                continue;
            }
            BatchStockViews.StocktakeLineResult lineResult = row(batch, actual, delta, actual,
                    BatchStockViews.STOCKTAKE_APPLIED);
            results.add(lineResult);
            adjustments.add(new StockBatchConsumptionService.StocktakeAdjustment(batch, delta));
            perSku.computeIfAbsent(batch.skuId(), k -> new ArrayList<>()).add(lineResult);
            totalDelta = totalDelta.add(delta);
        }

        if (adjustments.isEmpty()) {
            // 零差异 / 全部重放 ⇒ 一个字节都不写（硬要求，也是「点了提交但什么都没发生」的可解释回执）
            log.info("批次盘点无写入: tenant={}, product={}, runId={}, unchanged={}, replayed={}",
                    tenantId, productId, runId, unchanged, replayed);
            return new BatchStockViews.StocktakeResult(runId, productId, 0, unchanged, replayed,
                    BigDecimal.ZERO, results);
        }

        // ④ 盘后 SKU 库存 = 现库存 + 该 SKU 的 Σdelta；**先全算完再写**（负库存 ⇒ 整笔 4xx，不写半个字）
        Map<Long, BigDecimal> newStockBySku = new LinkedHashMap<>();
        Map<Long, ProductSku> skuById = new LinkedHashMap<>();
        for (ProductSku sku : productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getTenantId, tenantId)
                .in(ProductSku::getId, perSku.keySet()))) {
            skuById.put(sku.getId(), sku);
        }
        for (Map.Entry<Long, List<BatchStockViews.StocktakeLineResult>> entry : perSku.entrySet()) {
            ProductSku sku = skuById.get(entry.getKey());
            if (sku == null) {
                throw BusinessException.validationError(String.format(
                        "批次分录引用的 SKU %s 查不到 —— 无法同步 SKU 库存，本次盘点未写入", entry.getKey()));
            }
            BigDecimal before = StockQuantity.orZero(sku.getStock());
            BigDecimal delta = StockQuantity.sum(entry.getValue().stream()
                    .map(BatchStockViews.StocktakeLineResult::delta).toList());
            BigDecimal after = before.add(delta);
            if (after.signum() < 0) {
                throw new BusinessException("INSUFFICIENT_STOCK",
                        String.format("盘亏会让 SKU %s 的库存变负：现库存 %s 米，本次差异 %s 米",
                                sku.getSkuCode() == null ? entry.getKey() : sku.getSkuCode(),
                                before.toPlainString(), delta.toPlainString()), 422,
                        "盘点盘亏不能把库存扣成负数。请先核对是否漏记入库 / 先用「库存调整」补齐账面，再盘点");
            }
            newStockBySku.put(entry.getKey(), after);
        }

        // ⑤ 写：批次分录（唯一写入点 = StockBatchConsumptionService，**原子闸**：并发/重复的同一
        //    run id 请求在唯一索引处被判出来、返回已处理而不是抛异常 —— issue #6301）→
        //    SKU 库存 + 销售台账（唯一写入点 = StockLedgerService）。两段在**同一个事务**里：
        //    任一步失败整笔回滚。
        Set<Long> recorded = batchStockService.applyStocktake(tenantId, runId, adjustments);

        // ⑤b 原子闸判退的批次 = 并发中的**另一请求**已把这一行记过（它的 SKU 库存也已由那一笔对齐）
        //     ⇒ 本次必须是**幂等回放**：改回执状态，并把该批次从 SKU 库存 / 台账的写入面里摘掉。
        //    🔴 不摘就会双记：四个并发请求对同一个 sku 各写一次 `stock += delta`（探针 W5 的修前形态）。
        Set<Long> replayedNow = new LinkedHashSet<>();
        if (recorded.size() < adjustments.size()) {
            List<StockBatchConsumptionService.StocktakeAdjustment> persisted = new ArrayList<>();
            for (StockBatchConsumptionService.StocktakeAdjustment adjustment : adjustments) {
                if (recorded.contains(adjustment.batch().batchId())) {
                    persisted.add(adjustment);
                    continue;
                }
                long batchId = adjustment.batch().batchId();
                replayedNow.add(batchId);
                replayed++;
                for (int i = 0; i < results.size(); i++) {
                    BatchStockViews.StocktakeLineResult line = results.get(i);
                    if (line.batchId() == batchId && BatchStockViews.STOCKTAKE_APPLIED.equals(line.status())) {
                        results.set(i, row(adjustment.batch(), line.actualMeters(), BigDecimal.ZERO,
                                adjustment.batch().remainingMeters(), BatchStockViews.STOCKTAKE_REPLAYED));
                    }
                }
                List<BatchStockViews.StocktakeLineResult> skuLines = perSku.get(adjustment.batch().skuId());
                if (skuLines != null) {
                    skuLines.removeIf(line -> line.batchId() == batchId);
                }
                totalDelta = totalDelta.subtract(adjustment.delta());
            }
            if (!replayedNow.isEmpty()) {
                log.info("批次盘点并发回放: tenant={}, product={}, runId={}, replayedBatches={}",
                        tenantId, productId, runId, replayedNow);
                newStockBySku.clear();
                for (Map.Entry<Long, List<BatchStockViews.StocktakeLineResult>> entry : perSku.entrySet()) {
                    ProductSku sku = skuById.get(entry.getKey());
                    if (sku == null || entry.getValue().isEmpty()) {
                        continue;
                    }
                    BigDecimal delta = StockQuantity.sum(entry.getValue().stream()
                            .map(BatchStockViews.StocktakeLineResult::delta).toList());
                    newStockBySku.put(entry.getKey(), StockQuantity.orZero(sku.getStock()).add(delta));
                }
            }
        }
        for (Map.Entry<Long, BigDecimal> entry : newStockBySku.entrySet()) {
            ProductSku sku = skuById.get(entry.getKey());
            BigDecimal before = StockQuantity.orZero(sku.getStock());
            sku.setStock(entry.getValue());
            productSkuMapper.updateById(sku);
            // 台账逐批次一行：before/after 按**该 SKU 的库存链**首尾相接（销售账的不变式），
            // 批次自己的盘前/盘后写在 note 里 —— 两本账各记各自的量纲，不许混。
            BigDecimal running = before;
            for (BatchStockViews.StocktakeLineResult line : perSku.get(entry.getKey())) {
                BigDecimal next = running.add(line.delta());
                stockLedgerService.record(tenantId, productId, sku.getId(), sku.getSkuCode(),
                        running, next, StockLedger.REASON_MANUAL, line.batchNo(),
                        String.format("库存盘点：批次 %s 盘前 %s 米 → 盘后 %s 米（本次差异 %s 米）",
                                line.batchNo(), plain(line.beforeMeters()), plain(line.afterMeters()),
                                plain(line.delta())));
                running = next;
            }
        }
        log.info("批次盘点完成: tenant={}, product={}, runId={}, changed={}, unchanged={}, replayed={}, delta={}",
                tenantId, productId, runId, recorded.size(), unchanged, replayed, plain(totalDelta));
        return new BatchStockViews.StocktakeResult(runId, productId, recorded.size(), unchanged,
                replayed, StockQuantity.stripTrailingZerosPlain(totalDelta), results);
    }

    private static BatchStockViews.StocktakeLineResult row(BatchStockViews.BatchRemaining batch,
                                                           BigDecimal actual, BigDecimal delta,
                                                           BigDecimal after, String status) {
        return new BatchStockViews.StocktakeLineResult(batch.batchId(), batch.batchNo(), batch.skuId(),
                batch.skuCode(), StockQuantity.orZero(batch.remainingMeters()),
                StockQuantity.stripTrailingZerosPlain(actual),
                StockQuantity.stripTrailingZerosPlain(delta),
                StockQuantity.stripTrailingZerosPlain(after), status);
    }

    /** 去掉无意义的尾零（`2.70` → `2.7`）：JSON 字面量与断言才好逐值比（同 StockQuantity 的口径）。 */
    private static BigDecimal plain(BigDecimal value) {
        return StockQuantity.stripTrailingZerosPlain(value);
    }
}
