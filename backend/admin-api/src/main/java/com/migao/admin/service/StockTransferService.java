package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.StockTransferRequest;
import com.migao.admin.dto.StockTransferView;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.StockTransfer;
import com.migao.admin.entity.StockTransferItem;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.StockBatchMapper;
import com.migao.admin.mapper.StockTransferItemMapper;
import com.migao.admin.mapper.StockTransferMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;

/**
 * 调拨（issue #7373，P1-1 段 1）：调出仓 → 调入仓，**同事务两端一起变**。
 *
 * <h3>段 1 的形态：即时调拨</h3>
 * <p>确认即到位（`status = completed`），不设「在途」窗口 ⇒ 不存在「调拨中还能卖」的漏洞。
 * 两阶段在途是段 2（迁移已预留 `in_transit`）。</p>
 *
 * <h3>三条硬约束（都判在写之前）</h3>
 * <ol>
 *   <li><b>守恒</b>：同一批次行只改归属仓、不改数量 —— 调拨前后总量一字不变（{@link StockTransferPolicy}）；</li>
 *   <li><b>可调量</b>：不能超过该批次在**调出仓**的现有量（段 1 不做负库存）；</li>
 *   <li><b>缸号不丢</b>：明细引用 `batch_id`（同一行改仓）⇒ `dye_lot` 原样保留，可追溯。</li>
 * </ol>
 *
 * <h3>与「批次仓」的关系（照实登记）</h3>
 * <p>段 1 的仓库承载仍是 `stock_batches.warehouse`（文本）—— 本服务把它的值改成**调入仓的编码**，
 * 并把调出/调入两端记进调拨单（单据是真值，文本列是对齐后的快照）。把 `warehouse` 换成
 * `warehouse_id` 外键是段 2 的结构性改造（要迁存量文本值），不在本段偷偷做。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class StockTransferService {

    private final StockTransferMapper transferMapper;
    private final StockTransferItemMapper itemMapper;
    private final StockBatchMapper stockBatchMapper;
    private final WarehouseService warehouseService;
    private final com.migao.admin.time.BusinessClock businessClock;

    /**
     * 建单并**立即完成**（段 1 = 即时调拨）。
     *
     * @param request 调出仓 / 调入仓 / 逐批次明细
     * @param tenantId 租户
     */
    @Transactional
    public StockTransferView transfer(StockTransferRequest request, Long tenantId) {
        if (request.getFromWarehouseId() == null || request.getToWarehouseId() == null) {
            throw BusinessException.validationError("调出仓与调入仓都必须指定");
        }
        if (request.getFromWarehouseId().equals(request.getToWarehouseId())) {
            throw BusinessException.validationError("调出仓与调入仓不能是同一个仓");
        }
        if (request.getItems() == null || request.getItems().isEmpty()) {
            throw BusinessException.validationError("调拨至少要有一个批次明细");
        }
        Warehouse from = warehouseService.require(request.getFromWarehouseId());
        Warehouse to = warehouseService.require(request.getToWarehouseId());

        StockTransfer transfer = StockTransfer.builder()
                .tenantId(tenantId)
                .transferNo(nextTransferNo())
                .fromWarehouseId(from.getId())
                .toWarehouseId(to.getId())
                .status(StockTransfer.STATUS_COMPLETED)
                .note(request.getNote())
                .completedAt(OffsetDateTime.now())
                .build();

        List<StockTransferItem> items = new ArrayList<>();
        List<StockBatch> moved = new ArrayList<>();
        for (StockTransferRequest.Line line : request.getItems()) {
            if (line.getBatchId() == null) {
                throw BusinessException.validationError("调拨明细必须指明批次（batchId）");
            }
            StockBatch batch = stockBatchMapper.selectById(line.getBatchId());
            if (batch == null) {
                throw BusinessException.notFound("批次");
            }
            if (!from.getCode().equals(batch.getWarehouse())) {
                // 批次不在调出仓：要么写错仓，要么已经把货调走了 —— 两种都必须拒，不能「尽力而为」
                throw BusinessException.validationError(String.format(
                        "批次 %s 当前在仓「%s」，不在调出仓「%s」",
                        batch.getBatchNo(), batch.getWarehouse(), from.getCode()));
            }
            if (!StockTransferPolicy.canMove(batch.getQuantity(), line.getQty(), false)) {
                throw BusinessException.validationError(String.format(
                        "批次 %s 可调量不足：现有 %s，本次调拨 %s",
                        batch.getBatchNo(),
                        batch.getQuantity() == null ? "未知" : batch.getQuantity().toPlainString(),
                        line.getQty() == null ? "未知" : line.getQty().toPlainString()));
            }
            // 🔴 只改归属仓，不改数量（守恒）；缸号与其他批次属性一字不动
            batch.setWarehouse(to.getCode());
            moved.add(batch);

            // 成本是**库列回读值的搬运**（`stock_batches.unit_cost` 是 NUMERIC(12,4) = 元/米四位小数），
            // 🔴 不能套 2 位小数准入：那会把合法进价（12.3456）判成超精度 —— 精度按**列**判，不按「钱」一律 2 位。
            java.math.BigDecimal carriedCost = batch.getUnitCost();

            items.add(StockTransferItem.builder()
                    .tenantId(tenantId)
                    .batchId(batch.getId())
                    .batchNo(batch.getBatchNo())
                    .skuCode(batch.getSkuCode())
                    .qty(line.getQty())
                    .unitCost(carriedCost)
                    .build());
        }

        transferMapper.insert(transfer);
        for (StockTransferItem item : items) {
            item.setTransferId(transfer.getId());
            itemMapper.insert(item);
        }
        for (StockBatch batch : moved) {
            stockBatchMapper.updateById(batch);
        }
        log.info("[transfer] 调拨完成 | no={} from={} to={} lines={}", transfer.getTransferNo(),
                from.getCode(), to.getCode(), items.size());

        return StockTransferView.builder()
                .id(transfer.getId())
                .transferNo(transfer.getTransferNo())
                .fromWarehouseId(from.getId())
                .fromWarehouseCode(from.getCode())
                .toWarehouseId(to.getId())
                .toWarehouseCode(to.getCode())
                .status(transfer.getStatus())
                .items(items.stream().map(i -> StockTransferView.Line.builder()
                        .batchId(i.getBatchId()).batchNo(i.getBatchNo())
                        .skuCode(i.getSkuCode()).qty(i.getQty()).unitCost(i.getUnitCost())
                        .build()).toList())
                .build();
    }

    /** 调拨单详情（含明细）。 */
    public StockTransferView view(String transferId) {
        StockTransfer transfer = transferMapper.selectById(transferId);
        if (transfer == null) {
            throw BusinessException.notFound("调拨单");
        }
        List<StockTransferItem> items = itemMapper.selectList(new LambdaQueryWrapper<StockTransferItem>()
                .eq(StockTransferItem::getTransferId, transferId));
        return StockTransferView.builder()
                .id(transfer.getId())
                .transferNo(transfer.getTransferNo())
                .fromWarehouseId(transfer.getFromWarehouseId())
                .toWarehouseId(transfer.getToWarehouseId())
                .status(transfer.getStatus())
                .items(items.stream().map(i -> StockTransferView.Line.builder()
                        .batchId(i.getBatchId()).batchNo(i.getBatchNo())
                        .skuCode(i.getSkuCode()).qty(i.getQty()).unitCost(i.getUnitCost())
                        .build()).toList())
                .build();
    }

    /** 单号：TT + 业务日期 + 4 位随机（同租户唯一索引兜底）。 */
    private String nextTransferNo() {
        String day = businessClock.today().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
        int suffix = (int) (Math.random() * 9000) + 1000;
        return "TT" + day + suffix;
    }

    /** 段 1 不自动建仓：缺省仓由建仓接口显式设置。 */
    public Warehouse defaultWarehouse(Long tenantId) {
        return warehouseService.defaultWarehouse(tenantId);
    }

    /** 供未来段落使用：业务时区（与其余业务日期同源）。 */
    ZoneId businessZone() {
        return businessClock.zone();
    }
}
