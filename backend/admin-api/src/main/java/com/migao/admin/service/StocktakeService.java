package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.migao.admin.dto.StocktakeView;
import com.migao.admin.entity.Approval;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.Stocktake;
import com.migao.admin.entity.StocktakeItem;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.StockBatchMapper;
import com.migao.admin.mapper.StocktakeItemMapper;
import com.migao.admin.mapper.StocktakeMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 盘点（issue #7373，P1-1 段 2）：出任务 → 录实盘 → 差异经审批后调整。
 *
 * <h3>四个动作，各自判在写之前</h3>
 * <ol>
 *   <li>{@link #open}：按仓库出任务 —— **账面数快照**（该仓全部有货批次的当前量）；</li>
 *   <li>{@link #record}：录实盘（逐批次，可分批录）；</li>
 *   <li>{@link #complete}：完成盘点 —— 有差异时**必须**有已通过的 `stocktake_diff` 审批，
 *       否则写面直接拒（不是前端提示）；无差异直接完成（不逼人审批「账实相符」）；</li>
 *   <li>{@link #cancel}：作废（只有进行中的能作废）。</li>
 * </ol>
 *
 * <h3>调整只改数量</h3>
 * <p>差异调整改的是 `stock_batches.quantity`，**不动成本快照**（`unit_cost`）：盘点是「账实对齐」，
 * 不是重估成本（那是 P0-3 的口径）。改成本会让毛利凭空变化而没人能解释。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class StocktakeService {

    private final StocktakeMapper stocktakeMapper;
    private final StocktakeItemMapper itemMapper;
    private final StockBatchMapper stockBatchMapper;
    private final WarehouseService warehouseService;
    private final ApprovalService approvalService;
    private final com.migao.admin.time.BusinessClock businessClock;

    /**
     * 出盘点任务：把该仓**当前有货**的批次快照成账面行。
     *
     * @param warehouseId 仓
     * @param note        备注（可选）
     * @param operator    盘点人（只从服务端上下文取）
     */
    @Transactional
    public StocktakeView open(Long warehouseId, String note, ApprovalService.Operator operator) {
        Warehouse warehouse = warehouseService.require(warehouseId);
        // 同一仓同时只能有一个进行中的盘点（部分唯一索引兜底；这里先给可读提示）
        List<Stocktake> existing = stocktakeMapper.selectList(new LambdaQueryWrapper<Stocktake>()
                .eq(Stocktake::getWarehouseId, warehouseId)
                .eq(Stocktake::getStatus, Stocktake.STATUS_COUNTING));
        if (!existing.isEmpty()) {
            throw BusinessException.validationError(String.format(
                    "仓「%s」已有一个进行中的盘点（%s），请先完成或作废它",
                    warehouse.getCode(), existing.get(0).getStocktakeNo()));
        }

        Stocktake stocktake = Stocktake.builder()
                .tenantId(warehouse.getTenantId())
                .stocktakeNo(nextStocktakeNo())
                .warehouseId(warehouseId)
                .status(Stocktake.STATUS_COUNTING)
                .note(note)
                .countedBy(operator == null ? null : operator.userId())
                .countedByName(operator == null ? null : operator.displayName())
                .build();
        try {
            stocktakeMapper.insert(stocktake);
        } catch (org.springframework.dao.DuplicateKeyException duplicate) {
            throw BusinessException.validationError("该仓刚有另一个盘点被发起，请刷新后处理那一个");
        }

        // 账面快照：只快照**有货**的批次（0 量的批次盘了也没有意义，且会让明细无限膨胀）
        //
        // 🔴 默认仓还收「未指定仓」与「写成仓名」的批次（issue #7592）：入库单的「仓库 / 仓位」是
        //    **自由文本**，商家留空或写「主仓」都不会等于编码 ⇒ 只按编码匹配的话，盘点单会是 0 行明细
        //    （「仓库下拉有数据了，出任务还是空的」是同一个缺陷的下半段）。
        //    非默认仓仍是严格按编码：写错仓必须拦，不许「尽力而为」。
        LambdaQueryWrapper<StockBatch> batchQuery = new LambdaQueryWrapper<StockBatch>()
                .eq(StockBatch::getTenantId, warehouse.getTenantId())
                .gt(StockBatch::getQuantity, BigDecimal.ZERO);
        if (Boolean.TRUE.equals(warehouse.getIsDefault())) {
            batchQuery.apply(
                    "(warehouse = {0} OR warehouse = {1} OR btrim(coalesce(warehouse, '')) = '')",
                    warehouse.getCode(), warehouse.getName());
        } else {
            batchQuery.eq(StockBatch::getWarehouse, warehouse.getCode());
        }
        List<StockBatch> batches = stockBatchMapper.selectList(batchQuery);
        List<StocktakeItem> items = new ArrayList<>();
        for (StockBatch batch : batches) {
            StocktakeItem item = StocktakeItem.builder()
                    .tenantId(warehouse.getTenantId())
                    .stocktakeId(stocktake.getId())
                    .batchId(batch.getId())
                    .batchNo(batch.getBatchNo())
                    .skuCode(batch.getSkuCode())
                    .bookQty(batch.getQuantity())
                    .unitCost(batch.getUnitCost())
                    .build();
            itemMapper.insert(item);
            items.add(item);
        }
        log.info("[stocktake] 出任务 | no={} warehouse={} lines={}", stocktake.getStocktakeNo(),
                warehouse.getCode(), items.size());
        return view(stocktake, warehouse.getCode(), items);
    }

    /**
     * 录实盘（逐批次；可分批录）。
     *
     * @param countedByBatchId 批次 id → 实盘量
     */
    @Transactional
    public StocktakeView record(String stocktakeId, Map<Long, BigDecimal> countedByBatchId) {
        Stocktake stocktake = require(stocktakeId);
        requireCounting(stocktake);
        if (countedByBatchId == null || countedByBatchId.isEmpty()) {
            throw BusinessException.validationError("至少要录一条实盘数量");
        }
        List<StocktakeItem> items = itemsOf(stocktakeId);
        Map<Long, StocktakeItem> byBatch = new LinkedHashMap<>();
        for (StocktakeItem item : items) {
            byBatch.put(item.getBatchId(), item);
        }
        for (Map.Entry<Long, BigDecimal> entry : countedByBatchId.entrySet()) {
            StocktakeItem item = byBatch.get(entry.getKey());
            if (item == null) {
                throw BusinessException.validationError(String.format(
                        "批次 %s 不在本次盘点范围内（盘点单只含出任务时有货的批次）", entry.getKey()));
            }
            BigDecimal counted = entry.getValue();
            if (counted == null || counted.signum() < 0) {
                throw BusinessException.validationError(String.format(
                        "批次 %s 的实盘量必须 ≥ 0（未数就不录，不要填 0）", item.getBatchNo()));
            }
            BigDecimal diff = counted.subtract(item.getBookQty());
            item.setCountedQty(counted);
            item.setDiffQty(diff);
            itemMapper.updateById(item);
        }
        return view(stocktake, null, itemsOf(stocktakeId));
    }

    /**
     * 完成盘点：**有差异必须有已通过的 `stocktake_diff` 审批**（未审批 ⇒ 写面直接拒）。
     *
     * <p>审批对象 = 盘点单号，金额 = |差异| 合计（审批人看得到「一共调多少」）。
     * 通过后本方法**当场消费**那条审批（一笔一批），再把差异写进批次数量。</p>
     */
    @Transactional
    public StocktakeView complete(String stocktakeId) {
        Stocktake stocktake = require(stocktakeId);
        requireCounting(stocktake);
        List<StocktakeItem> items = itemsOf(stocktakeId);
        List<StocktakePolicy.Line> lines = items.stream()
                .map(i -> new StocktakePolicy.Line(i.getBookQty(), i.getCountedQty())).toList();
        if (!StocktakePolicy.allCounted(lines)) {
            throw BusinessException.validationError("还有批次没录实盘 —— 没数不等于「数了正好一样」，请先录完");
        }

        // 落库三列自相一致（抓「改了实盘没同步差异」这类脏数据；不一致就不许据此调库存）
        List<StocktakePolicy.StoredRow> stored = items.stream()
                .map(i -> new StocktakePolicy.StoredRow(i.getBookQty(), i.getCountedQty(), i.getDiffQty()))
                .toList();
        if (!StocktakePolicy.storedDiffsAgreeWithQuantities(stored)) {
            throw BusinessException.validationError(
                    "这次盘点的明细自相矛盾（实盘与差异对不上），请重新录入后再完成");
        }

        boolean hasDiff = items.stream().anyMatch(i -> i.getDiffQty() != null && i.getDiffQty().signum() != 0);
        if (hasDiff) {
            BigDecimal totalAbsDiff = StocktakePolicy.totalAbsDiff(lines);
            String approvalId = approvalService.consume(Approval.TYPE_STOCKTAKE_DIFF,
                    stocktake.getStocktakeNo(), totalAbsDiff, stocktake.getId());
            if (approvalId == null) {
                throw BusinessException.validationError(String.format(
                        "盘点有差异（合计 %s），必须先有已通过的「盘点差异」审批："
                                + "objectType=stocktake_diff，objectRef=%s，金额 ≥ %s",
                        totalAbsDiff.toPlainString(), stocktake.getStocktakeNo(), totalAbsDiff.toPlainString()));
            }
            applyDiffs(items, lines);
            log.info("[stocktake] 差异经审批后调整 | no={} approval={} total_diff={}",
                    stocktake.getStocktakeNo(), approvalId, totalAbsDiff.toPlainString());
        }

        int updated = stocktakeMapper.update(null, new LambdaUpdateWrapper<Stocktake>()
                .eq(Stocktake::getId, stocktakeId)
                .eq(Stocktake::getStatus, Stocktake.STATUS_COUNTING)
                .set(Stocktake::getStatus, Stocktake.STATUS_COMPLETED)
                .set(Stocktake::getCompletedAt, OffsetDateTime.now())
                .set(Stocktake::getUpdatedAt, OffsetDateTime.now()));
        if (updated == 0) {
            throw BusinessException.validationError("这次盘点刚被别人完成了，请刷新后查看结果");
        }
        return view(require(stocktakeId), null, itemsOf(stocktakeId));
    }

    /** 作废（只有进行中的能作废；已完成的调整已经落到库存，不能撤）。 */
    @Transactional
    public StocktakeView cancel(String stocktakeId) {
        Stocktake stocktake = require(stocktakeId);
        requireCounting(stocktake);
        int updated = stocktakeMapper.update(null, new LambdaUpdateWrapper<Stocktake>()
                .eq(Stocktake::getId, stocktakeId)
                .eq(Stocktake::getStatus, Stocktake.STATUS_COUNTING)
                .set(Stocktake::getStatus, Stocktake.STATUS_CANCELLED)
                .set(Stocktake::getUpdatedAt, OffsetDateTime.now()));
        if (updated == 0) {
            throw BusinessException.validationError("这次盘点刚被完成，不能作废");
        }
        return view(require(stocktakeId), null, itemsOf(stocktakeId));
    }

    /** 详情（含逐批次账面 / 实盘 / 差异）。 */
    public StocktakeView detail(String stocktakeId) {
        Stocktake stocktake = require(stocktakeId);
        return view(stocktake, null, itemsOf(stocktakeId));
    }

    /** 列表（最新在前）。 */
    public List<StocktakeView> list() {
        return stocktakeMapper.selectList(new LambdaQueryWrapper<Stocktake>()
                        .orderByDesc(Stocktake::getCreatedAt)).stream()
                .map(s -> view(s, null, List.of()))
                .toList();
    }

    private void applyDiffs(List<StocktakeItem> items, List<StocktakePolicy.Line> lines) {
        for (int i = 0; i < items.size(); i++) {
            StocktakeItem item = items.get(i);
            BigDecimal diff = lines.get(i).diff();
            if (diff == null || diff.signum() == 0) {
                continue;
            }
            StockBatch batch = stockBatchMapper.selectById(item.getBatchId());
            if (batch == null) {
                throw BusinessException.notFound("批次");
            }
            if (!StocktakePolicy.adjustable(batch.getQuantity(), diff)) {
                throw BusinessException.validationError(String.format(
                        "批次 %s 调整后会变成负数（账面 %s + 差异 %s）—— 请先核对实盘数",
                        batch.getBatchNo(), batch.getQuantity().toPlainString(), diff.toPlainString()));
            }
            // 🔴 只改数量，不动 unit_cost（盘点不是成本重估，见类注释）
            batch.setQuantity(batch.getQuantity().add(diff));
            stockBatchMapper.updateById(batch);
        }
    }

    private Stocktake require(String stocktakeId) {
        Stocktake stocktake = stocktakeMapper.selectById(stocktakeId);
        if (stocktake == null) {
            throw BusinessException.notFound("盘点单");
        }
        return stocktake;
    }

    private static void requireCounting(Stocktake stocktake) {
        if (!Stocktake.STATUS_COUNTING.equals(stocktake.getStatus())) {
            throw BusinessException.validationError(String.format(
                    "这次盘点已经是「%s」，不能再改了", stocktake.getStatus()));
        }
    }

    private List<StocktakeItem> itemsOf(String stocktakeId) {
        return itemMapper.selectList(new LambdaQueryWrapper<StocktakeItem>()
                .eq(StocktakeItem::getStocktakeId, stocktakeId)
                .orderByAsc(StocktakeItem::getBatchNo));
    }

    private StocktakeView view(Stocktake stocktake, String warehouseCode, List<StocktakeItem> items) {
        return StocktakeView.builder()
                .id(stocktake.getId())
                .stocktakeNo(stocktake.getStocktakeNo())
                .warehouseId(stocktake.getWarehouseId())
                .warehouseCode(warehouseCode)
                .status(stocktake.getStatus())
                .note(stocktake.getNote())
                .completedAt(stocktake.getCompletedAt())
                .items(items.stream().map(i -> StocktakeView.Line.builder()
                        .batchId(i.getBatchId())
                        .batchNo(i.getBatchNo())
                        .skuCode(i.getSkuCode())
                        .bookQty(i.getBookQty())
                        .countedQty(i.getCountedQty())
                        .diffQty(i.getDiffQty())
                        .build()).toList())
                .build();
    }

    /** 单号：PD + 业务日期 + 4 位随机（同租户唯一索引兜底）。 */
    private String nextStocktakeNo() {
        String day = businessClock.today().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
        int suffix = (int) (Math.random() * 9000) + 1000;
        return "PD" + day + suffix;
    }
}
