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
import org.springframework.util.StringUtils;
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
    /** 部位码（V197 / issue #7762）：一张水洗唛 = 一个仓位 */
    private final com.migao.admin.mapper.ProcessingSetPartTokenMapper tokenMapper;
    /** 套（标签「第 N 套 / 共 M 套」） */
    private final com.migao.admin.mapper.ProcessingOrderSetMapper setMapper;
    /** 报工记录（授权：只有做过打包工序的工人能扫唛出库） */
    private final com.migao.admin.mapper.ProductionWorkLogMapper workLogMapper;
    /** 订单主表（标签抬头：订单号 / 客户 / 下单日期） */
    private final com.migao.admin.mapper.OrderMapper orderMapper;
    /** 业务时钟（issue #3802）：标签「下单日期」的 +08 口径唯一来源（不写时区字面量）。 */
    @org.springframework.beans.factory.annotation.Autowired(required = false)
    private com.migao.admin.time.BusinessClock businessClock = new com.migao.admin.time.BusinessClock();
    /** 本页「出库标签」的短链前缀（与 `/s/{短码}` 公开入口同一份口径） */
    private static final String SHORT_LINK_PREFIX = "/s/";
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
        // 🔴 V197（issue #7762）：有部位码 ⇒ 按「套 × 部位」逐行入库（5 套 × 布帘 = 5 行 = 5 个仓位）；
        // 没有码（布料单 / 未印码的历史单）⇒ 退回 V196 的订单行粒度（不造空行）。
        List<com.migao.admin.entity.ProcessingSetPartToken> tokens =
                tokenMapper.selectByOrderId(tenantId, order.getId());
        if (!tokens.isEmpty()) {
            return receiveOnPackByTokens(order, tenantId, operator, tokens);
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

    /**
     * 打包入库（套 × 部位粒度，V197 / issue #7762）。
     *
     * <p>每张水洗唛（部位码）一行：一个套的布帘 / 纱帘各有自己的仓位与标签 —— 工人扫哪张码就出哪一件。
     * 订单行仍是「成本/计价」载体，这里只把**可搬运的一件成品**当作仓位载体。</p>
     */
    private List<FinishedGoodsStock> receiveOnPackByTokens(Order order, Long tenantId, String operator,
                                                           List<com.migao.admin.entity.ProcessingSetPartToken> tokens) {
        Map<String, OrderItem> itemById = new LinkedHashMap<>();
        for (OrderItem item : orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getTenantId, tenantId)
                .eq(OrderItem::getOrderId, order.getId()))) {
            itemById.put(item.getId(), item);
        }
        Warehouse warehouse = warehouseService.ensureFinishedWarehouse(tenantId);
        List<com.migao.admin.entity.InboundOrderItem> lines = new ArrayList<>();
        int skipped = 0;
        for (com.migao.admin.entity.ProcessingSetPartToken token : tokens) {
            OrderItem item = itemById.get(token.getOrderItemId());
            if (item == null) {
                skipped++;
                continue;
            }
            com.migao.admin.entity.ProcessingOrderSet set = setMapper.selectById(token.getSetId());
            lines.add(com.migao.admin.entity.InboundOrderItem.builder()
                    .productId(item.getProductId())
                    .productName(item.getProductName())
                    .orderId(order.getId())
                    .orderNo(order.getOrderNo())
                    .orderItemId(item.getId())
                    .setId(token.getSetId())
                    .setNo(set == null ? null : set.getSetNo())
                    .shortCode(token.getShortCode())
                    .quantity(java.math.BigDecimal.ONE)
                    .unit(FinishedGoodsStock.UNIT_SET)
                    .remark("打包（套×部位）")
                    .build());
        }
        if (lines.isEmpty()) {
            // 码全是陈旧引用（订单行已删）⇒ 不造假单，退回订单行粒度
            log.warn("[成品入库] 部位码全部挂不到订单行，退回订单行粒度: tenant={}, orderNo={}, skipped={}",
                    tenantId, order.getOrderNo(), skipped);
            return receiveOnPackByItems(order, tenantId, operator);
        }
        inboundOrderService.receiveFinishedGoodsLines(tenantId, order, lines,
                warehouse.getId(), warehouse.getName(), operator);
        List<FinishedGoodsStock> rows = stockMapper.selectInStockByOrder(tenantId, order.getId());
        log.info("[成品入库] 打包入库（套×部位）完成: tenant={}, orderNo={}, tokens={}, skipped={}, bins={}",
                tenantId, order.getOrderNo(), lines.size(), skipped, binsOf(rows));
        return rows;
    }

    /** V196 的订单行粒度入库（无部位码的兜底形态）。 */
    private List<FinishedGoodsStock> receiveOnPackByItems(Order order, Long tenantId, String operator) {
        List<OrderItem> items = orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getTenantId, tenantId)
                .eq(OrderItem::getOrderId, order.getId())
                .orderByAsc(OrderItem::getId));
        if (items.isEmpty()) {
            return List.of();
        }
        Warehouse warehouse = warehouseService.ensureFinishedWarehouse(tenantId);
        inboundOrderService.receiveFinishedGoods(tenantId, order, items,
                warehouse.getId(), warehouse.getName(), operator);
        return stockMapper.selectInStockByOrder(tenantId, order.getId());
    }

    // ============================================================ 扫水洗唛（V197 / #7762）

    /**
     * 扫水洗唛的**只读**视图（移动端报工页的「成品出库」卡片）。
     *
     * <p>返回 {@code allowed / reason / bin_code / label}：{@code allowed} 三条同时成立才为 true ——
     * ① 这张码有在库行；② 当前工人**做过这张加工单的打包工序**；③ 未出库（在库行存在即未出库）。</p>
     *
     * @param key token 或短码（两者是同一行的两种表示）
     */
    public Map<String, Object> washLabelView(Long tenantId, String key, String workerId) {
        return washLabelView(tenantId, key, workerId, null);
    }

    public Map<String, Object> washLabelView(Long tenantId, String key, String workerId, String workerName) {
        Map<String, Object> out = new LinkedHashMap<>();
        com.migao.admin.entity.ProcessingSetPartToken token = StringUtils_resolveToken(tenantId, key);
        if (token == null) {
            out.put("allowed", false);
            out.put("reason", "这张码不是部位码（没有印套 × 部位的成品标签）");
            return out;
        }
        FinishedGoodsStock stock = stockMapper.selectInStockByWashLabel(tenantId, key);
        boolean inStock = stock != null;
        boolean packer = StringUtils.hasText(workerId)
                && workLogMapper.countPackerLogs(tenantId, token.getProcessingOrderId(), workerId) > 0;
        boolean allowed = inStock && packer;
        String reason;
        if (!inStock) {
            reason = "这张码对应的成品不在库（还没打包，或已经出库）";
        } else if (!packer) {
            reason = "只有做过打包工序的工人才能扫码出库";
        } else {
            reason = null;
        }
        out.put("allowed", allowed);
        if (reason != null) {
            out.put("reason", reason);
        }
        out.put("token", token.getToken());
        out.put("short_code", token.getShortCode());
        out.put("bin_code", stock == null ? null : stock.getBinCode());
        out.put("order_id", token.getOrderItemId() == null ? null : stock_orderId(stock, token));
        out.put("worker_name", workerName);
        out.put("label", labelOf(tenantId, token, stock));
        return out;
    }

    /**
     * 扫水洗唛出库（V197 / issue #7762）。
     *
     * <p>幂等由**条件更新**兜住：{@code status='in_stock'} 才改得动；0 行 ⇒ 409「已出库」。
     * 出库单 {@code source=scan}、单行（套 × 部位 + 仓位号），与发货出库同表同号段。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> issueByWashLabel(Long tenantId, String key, String workerId, String workerName) {
        Map<String, Object> view = washLabelView(tenantId, key, workerId, workerName);
        if (!Boolean.TRUE.equals(view.get("allowed"))) {
            throw BusinessException.conflict(String.valueOf(view.get("reason")),
                    "请确认这张水洗唛的成品已打包、并且你本人做过打包工序");
        }
        com.migao.admin.entity.ProcessingSetPartToken token = StringUtils_resolveToken(tenantId, key);
        FinishedGoodsStock stock = stockMapper.selectInStockByWashLabel(tenantId, key);
        if (token == null || stock == null) {
            throw BusinessException.conflict("这张水洗唛的在库行已不存在", "请刷新后重试");
        }
        Order order = orderMapper.selectById(stock.getOrderId());
        Warehouse warehouse = warehouseService.ensureFinishedWarehouse(tenantId);
        OutboundOrder doc = outboundOrderService.createScanOutbound(order == null ? stock.getOrderNo() : order.getOrderNo(),
                stock, warehouse, tenantId, StringUtils.hasText(workerName) ? workerName : workerId);
        int rows = stockMapper.markShippedById(tenantId, stock.getId(), doc.getId());
        if (rows == 0) {
            throw BusinessException.conflict("这张水洗唛已经出库了",
                    "同一个仓位不会被两件成品同时占用；重复提交不会重复扣减");
        }
        Map<String, Object> out = new LinkedHashMap<>(view);
        out.put("allowed", false);
        out.put("reason", "已出库");
        out.put("outbound_no", doc.getOutboundNo());
        log.info("[成品出库] 扫水洗唛出库完成: tenant={}, key={}, bin={}, outboundNo={}, worker={}",
                tenantId, key, stock.getBinCode(), doc.getOutboundNo(), workerId);
        return out;
    }

    private com.migao.admin.entity.ProcessingSetPartToken StringUtils_resolveToken(Long tenantId, String key) {
        if (!org.springframework.util.StringUtils.hasText(key)) {
            return null;
        }
        String k = key.trim();
        // 整条印刷 URL（`…/s/<短码>`）⇒ 取最后一段：与扫码归一化同口径（不在这里再写一套规则）
        int slash = k.lastIndexOf('/');
        if (slash >= 0 && slash < k.length() - 1 && !k.startsWith("http")) {
            k = k.substring(slash + 1);
        }
        return tokenMapper.selectByTokenOrShortCode(tenantId, k);
    }

    private static String stock_orderId(FinishedGoodsStock stock,
                                        com.migao.admin.entity.ProcessingSetPartToken token) {
        return stock == null ? null : stock.getOrderId();
    }

    /**
     * 标签内容（**服务端唯一源**，V197 / issue #7762）。
     *
     * <p>逐行 = 「标签字段名 → 值」；没有稳定来源的字段（项目名称 / 款式 / 安装工艺 / 扩展选项）
     * **不出现**（不印 `—`、不编造）—— 前端只负责按顺序排版与打印。</p>
     */
    public Map<String, Object> labelOf(Long tenantId,
                                       com.migao.admin.entity.ProcessingSetPartToken token,
                                       FinishedGoodsStock stock) {
        Map<String, Object> label = new LinkedHashMap<>();
        List<Map<String, String>> rows = new ArrayList<>();
        Order order = stock == null ? null : orderMapper.selectById(stock.getOrderId());
        OrderItem item = stock == null || stock.getOrderItemId() == null
                ? null : orderItemMapper.selectById(stock.getOrderItemId());
        com.migao.admin.entity.ProcessingOrderSet set = token.getSetId() == null
                ? null : setMapper.selectById(token.getSetId());
        int setTotal = set == null ? 0 : setMapper.selectCount(new LambdaQueryWrapper<com.migao.admin.entity.ProcessingOrderSet>()
                .eq(com.migao.admin.entity.ProcessingOrderSet::getProcessingOrderId, set.getProcessingOrderId())
                .eq(com.migao.admin.entity.ProcessingOrderSet::getDeleted, 0)).intValue();

        addRow(rows, "订单编号", order == null
                ? (stock == null ? null : stock.getOrderNo()) : order.getOrderNo());
        addRow(rows, "客户", order == null ? null : order.getCustomerName());
        addRow(rows, "下单日期", order == null || order.getCreatedAt() == null ? null
                : order.getCreatedAt().atZoneSameInstant(businessClock.zone()).toLocalDate().toString());
        // 收货人：数据模型只有「客户 + 收货地址」，没有独立收货人 ⇒ 收货人 = 客户（照实渲染，不猜人名）
        addRow(rows, "收货人", order == null ? null : order.getCustomerName());
        if (set != null) {
            addRow(rows, "套数", "第" + (set.getSetIndex() == null ? "?" : set.getSetIndex())
                    + "套/共" + (setTotal > 0 ? setTotal : "?") + "套");
        }
        addRow(rows, "尺寸", sizeOf(item));
        addRow(rows, "开数", item == null || item.getOpenCount() == null ? null
                : String.valueOf(item.getOpenCount()));
        addRow(rows, "部位", token.getPositionKind());
        addRow(rows, "主布货号", item == null ? null : item.getSkuCode());
        addRow(rows, "打包区域", stock == null ? null : stock.getBinCode());

        label.put("rows", rows);
        label.put("short_code", token.getShortCode());
        label.put("qr_value", token.getShortCode() == null
                ? token.getToken() : SHORT_LINK_PREFIX + token.getShortCode());
        label.put("bin_code", stock == null ? null : stock.getBinCode());
        return label;
    }

    private static void addRow(List<Map<String, String>> rows, String label, String value) {
        if (value == null || value.isBlank() || "?".equals(value)) {
            return;
        }
        rows.add(Map.of("label", label, "value", value.trim()));
    }

    /** 尺寸：`宽*高`（米，最多 2 位小数、去尾零）；缺任一边 ⇒ 不渲染（不猜）。 */
    private static String sizeOf(OrderItem item) {
        if (item == null || item.getWidth() == null || item.getHeight() == null) {
            return null;
        }
        return trimNumber(item.getWidth()) + "*" + trimNumber(item.getHeight());
    }

    private static String trimNumber(java.math.BigDecimal value) {
        return value.stripTrailingZeros().toPlainString();
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
