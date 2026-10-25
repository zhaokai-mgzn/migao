package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.FinishedGoodsView;
import com.migao.admin.entity.FinishedGoodsStock;
import com.migao.admin.entity.InboundOrder;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OutboundOrder;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinishedGoodsStockMapper;
import com.migao.admin.mapper.OrderItemMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 成品库存（V196，issue #7750）—— 打包入库 / 发货出库 / 撤销打包三个时点的唯一编排点。
 *
 * <h3>时点（与工人实际动作对齐）</h3>
 * <ul>
 *   <li><b>打包</b>（{@code packed}）⇒ 成品入库：自动建成品入库单（{@code source=packing}，立即过账）
 *       + 给每个成品订单行分配成品仓仓位号；</li>
 *   <li><b>发货</b>（{@code shipped}）⇒ 成品出库：自动建成品出库单（{@code source=ship}，立即过账）
 *       + 在库行置 shipped（释放仓位）；</li>
 *   <li><b>撤销打包</b>（{@code packed → producing}）⇒ 冲销：入库单作废 + 在库行置 unpacked（释放仓位）。</li>
 * </ul>
 *
 * <p>🔴 <b>为什么不挂在「扫码报打包工序」上</b>（如实登记）：扫码报工在本仓的语义是**领活**
 * （issue #4967 用户裁定「工人都是先扫码报工后再真实进行生产」）⇒ 那一刻货还没打包好。
 * 入库时点取**订单打包动作**（{@code OrderShipmentService#pack}，也是「打包发货」这条链的
 * 状态迁移点）；一步发货（{@code producing → shipped}，跳过打包）时由 {@link #issueOnShip}
 * 先补一次入库再出库，保证「发走的成品都能追到仓位」。</p>
 *
 * <h3>幂等</h3>
 * <p>三个入口都以**订单状态迁移**为前置（pack / ship / unpack 的 CAS 只放行一次）⇒
 * 同一订单不会重复入库/重复出库。{@link #receiveOnPack} 另外再判一次「是否已有在库行」，
 * 让「状态已 packed 但成品行缺失」的重入场景补齐而非重复（不会建第二张入库单）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class FinishedGoodsService {

    private final FinishedGoodsStockMapper stockMapper;
    private final OrderItemMapper orderItemMapper;
    private final WarehouseService warehouseService;
    private final InboundOrderService inboundOrderService;
    private final OutboundOrderService outboundOrderService;

    // ============================================================ 打包入库

    /**
     * 打包 ⇒ 成品入库（分配仓位号）。
     *
     * @return 本单当前在库的成品行（含 {@code binCode}）；订单没有明细行 ⇒ 空列表（不造假单）
     */
    @Transactional(rollbackFor = Exception.class)
    public List<FinishedGoodsStock> receiveOnPack(Order order, Long tenantId, String operator) {
        List<FinishedGoodsStock> existing = stockMapper.selectInStockByOrder(tenantId, order.getId());
        if (!existing.isEmpty()) {
            log.info("[成品入库] 本单已有在库成品行，跳过重复入库: tenant={}, orderNo={}, bins={}",
                    tenantId, order.getOrderNo(), binsOf(existing));
            return existing;
        }
        List<OrderItem> items = orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getTenantId, tenantId)
                .eq(OrderItem::getOrderId, order.getId())
                .orderByAsc(OrderItem::getId));
        if (items.isEmpty()) {
            log.warn("[成品入库] 订单没有成品行，跳过成品入库: tenant={}, orderNo={}", tenantId, order.getOrderNo());
            return List.of();
        }
        Warehouse warehouse = warehouseService.ensureFinishedWarehouse(tenantId);
        InboundOrder doc = toOrder(inboundOrderService.receiveFinishedGoods(tenantId, order, items,
                warehouse.getId(), warehouse.getName(), operator));
        List<FinishedGoodsStock> rows = stockMapper.selectInStockByOrder(tenantId, order.getId());
        log.info("[成品入库] 打包入库完成: tenant={}, orderNo={}, inboundNo={}, bins={}",
                tenantId, order.getOrderNo(), doc == null ? null : doc.getInboundNo(), binsOf(rows));
        return rows;
    }

    // ============================================================ 发货出库

    /**
     * 发货 ⇒ 成品出库（释放仓位）。
     *
     * <p>没有在库行（一步发货 / 历史订单）⇒ 不造空出库单，返回空列表并留痕：凭空写一张
     * 「0 行」的出库单只会让对账多一个无法解释的单据。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public List<FinishedGoodsStock> issueOnShip(Order order, Long tenantId, String operator) {
        List<FinishedGoodsStock> inStock = stockMapper.selectInStockByOrder(tenantId, order.getId());
        if (inStock.isEmpty()) {
            log.info("[成品出库] 本单没有在库成品行，跳过成品出库（不造空单）: tenant={}, orderNo={}",
                    tenantId, order.getOrderNo());
            return List.of();
        }
        Warehouse warehouse = warehouseService.ensureFinishedWarehouse(tenantId);
        OutboundOrder doc = outboundOrderService.createFinishedOutbound(order, inStock, warehouse, tenantId, operator);
        int rows = stockMapper.markShippedByOrder(tenantId, order.getId(), doc.getId());
        if (rows == 0) {
            // 走到这里说明在库行在本次事务内被并发改掉（撤销打包 / 另一次发货）⇒ 整笔回滚
            throw BusinessException.conflict("成品出库失败：在库状态已并发变更",
                    "请刷新订单后重试；库存与单据已整体回滚，不会出现「货发了、账没动」");
        }
        log.info("[成品出库] 发货出库完成: tenant={}, orderNo={}, outboundNo={}, bins={}, rows={}",
                tenantId, order.getOrderNo(), doc.getOutboundNo(), binsOf(inStock), rows);
        return inStock;
    }

    // ============================================================ 撤销打包（冲销）

    /**
     * 撤销打包 ⇒ 冲销成品入库（入库单作废 + 仓位释放）。
     *
     * @return 释放的在库行数（0 = 本单本就没有在库行，幂等）
     */
    @Transactional(rollbackFor = Exception.class)
    public int reverseOnUnpack(Order order, Long tenantId, String operator, String reason) {
        List<FinishedGoodsStock> inStock = stockMapper.selectInStockByOrder(tenantId, order.getId());
        if (inStock.isEmpty()) {
            return 0;
        }
        int released = stockMapper.markUnpackedByOrder(tenantId, order.getId());
        if (released == 0) {
            log.info("[成品入库] 撤销打包时没有可释放的在库行（并发已释放）: tenant={}, orderNo={}",
                    tenantId, order.getOrderNo());
            return 0;
        }
        List<String> inboundIds = new ArrayList<>();
        for (FinishedGoodsStock row : inStock) {
            if (row.getInboundOrderId() != null && !inboundIds.contains(row.getInboundOrderId())) {
                inboundIds.add(row.getInboundOrderId());
            }
        }
        String cancelReason = reason == null || reason.isBlank() ? "撤销打包" : "撤销打包：" + reason;
        for (String inboundId : inboundIds) {
            inboundOrderService.cancelFinishedPosting(inboundId, tenantId, operator, cancelReason);
        }
        log.info("[成品入库] 撤销打包已冲销: tenant={}, orderNo={}, released={}, bins={}, inboundOrders={}",
                tenantId, order.getOrderNo(), released, binsOf(inStock), inboundIds);
        return released;
    }

    // ============================================================ 读面

    /** 在库成品（成品库存页；按仓位号排序）。 */
    public List<FinishedGoodsView> listInStock(Long tenantId) {
        return stockMapper.selectInStock(tenantId).stream().map(FinishedGoodsService::toView).toList();
    }

    /** 本单在库成品的仓位号（读面/回执用；无在库行 ⇒ 空列表）。 */
    public List<String> binsOfOrder(Long tenantId, String orderId) {
        return binsOf(stockMapper.selectInStockByOrder(tenantId, orderId));
    }

    /** 本单在库成品的「订单行 → 仓位号」视图（打包/发货回执用，工人端据此打印/贴标）。 */
    public List<Map<String, Object>> binAssignments(Long tenantId, String orderId) {
        List<Map<String, Object>> assignments = new ArrayList<>();
        for (FinishedGoodsStock row : stockMapper.selectInStockByOrder(tenantId, orderId)) {
            Map<String, Object> one = new LinkedHashMap<>();
            one.put("order_item_id", row.getOrderItemId());
            one.put("product_name", row.getProductName());
            one.put("bin_code", row.getBinCode());
            one.put("quantity", row.getQuantity());
            one.put("unit", row.getUnit());
            assignments.add(one);
        }
        return assignments;
    }

    private static List<String> binsOf(List<FinishedGoodsStock> rows) {
        return rows.stream().map(FinishedGoodsStock::getBinCode).filter(Objects::nonNull).toList();
    }

    private static FinishedGoodsView toView(FinishedGoodsStock row) {
        FinishedGoodsView view = new FinishedGoodsView();
        view.setId(row.getId());
        view.setBinCode(row.getBinCode());
        view.setWarehouseId(row.getWarehouseId());
        view.setLocationId(row.getLocationId());
        view.setOrderId(row.getOrderId());
        view.setOrderNo(row.getOrderNo());
        view.setOrderItemId(row.getOrderItemId());
        view.setProductId(row.getProductId());
        view.setProductName(row.getProductName());
        view.setQuantity(row.getQuantity());
        view.setUnit(row.getUnit());
        view.setStatus(row.getStatus());
        view.setInboundOrderId(row.getInboundOrderId());
        view.setOutboundOrderId(row.getOutboundOrderId());
        view.setCreatedAt(row.getCreatedAt());
        return view;
    }

    /**
     * 入库单响应 → 实体（只为拿单号/仓位做日志；响应与实体同名字段，取需要的两项即可）。
     *
     * <p>这里不引入第二套 DTO 映射：调用方只需要 {@code inboundNo} 落日志。</p>
     */
    private static InboundOrder toOrder(com.migao.admin.dto.InboundOrderResponse response) {
        if (response == null) {
            return null;
        }
        return InboundOrder.builder()
                .id(response.getId())
                .inboundNo(response.getInboundNo())
                .status(response.getStatus())
                .build();
    }
}
