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
 *   <li><b>扫码报「打包」工序</b>（issue #7845，2026-10-26 用户裁定）⇒ 成品入库：这张水洗唛
 *       （套 × 部位）建成品入库单（{@code source=packing}，立即过账、分配仓位）；
 *       报工页据此显示「质检结果 + 入库单号 + 仓位 + 打印入库标签」；</li>
 *   <li><b>打包</b>（{@code packed}）⇒ 成品入库：自动建成品入库单 + 分配仓位号
 *       （扫码已入过的部位跳过、只补剩余，见 {@link #receiveOnPackByTokens}）；</li>
 *   <li><b>发货</b>（{@code shipped}）⇒ 成品出库：自动建成品出库单（{@code source=ship}，立即过账）
 *       + 在库行置 shipped（释放仓位）；</li>
 *   <li><b>撤销打包</b>（{@code packed → producing}）⇒ 冲销：入库单作废 + 在库行置 unpacked（释放仓位）。</li>
 * </ul>
 *
 * <p>🔴 <b>入库时点为什么从「订单打包动作」扩到「扫码报打包工序」（沿革 + 取舍）</b>：
 * 改前（#7750）只挂在 {@code OrderShipmentService#pack}，理由是「扫码在本仓的语义是领活」
 * —— 但 #7845 用户改判「只有打包工序绑定了成品帘入库…扫码后除了自动报工，还需要生成成品入库单」
 * （车间里打包这道活干完，这一件就已经装袋、贴唛、可上架了）。两个时点现在**并存且幂等**：
 * 谁先到谁入库，后到的一侧跳过已在库的那一件（不会一件两仓）。一步发货
 * （{@code producing → shipped}，跳过打包）仍由 {@link #issueOnShip} 先补一次入库再出库。</p>
 *
 * <h3>幂等</h3>
 * <p>四个入口都以**订单状态迁移 / 在库行存在**为前置（pack / ship / unpack 的 CAS，以及
 * 「这张唛已在库 ⇒ 直接返回既有单据」）⇒ 同一件成品不会重复入库/重复出库。
 * {@link #receiveOnPack} 另外再按 token 判一次「哪些已在库」，让「扫码先入 + 订单后打包」的
 * 重入场景**补剩余**而非重复（不会建第二张同件入库单）。</p>
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

    /**
     * 质检结论（issue #7845）：打包工人扫码报工时要在屏上「确认质检结果」。
     *
     * <p>🔴 该读面对外只对开通了「质检」页的工人开放（{@code WorkerQualityController#requireInspector}），
     * 而打包工人通常没有这一页 ⇒ 结论**随入库块由服务端下发**，页面不再多发一次必然 403 的读请求。
     * 字段注入（{@code @RequiredArgsConstructor} 的构造签名被既有测试直接装配，不能加参数）。</p>
     */
    @org.springframework.beans.factory.annotation.Autowired(required = false)
    private QualityCheckService qualityCheckService;

    /** 读 `processing_info` 里安装信息用（issue #7856）；同样走字段注入，原因见 {@link #qualityCheckService}。 */
    @org.springframework.beans.factory.annotation.Autowired(required = false)
    private com.fasterxml.jackson.databind.ObjectMapper objectMapper;

    // ============================================================ 打包入库

    /**
     * 打包 ⇒ 成品入库（分配仓位号）。
     *
     * @return 本单当前在库的成品行（含 {@code binCode}）；订单没有明细行 ⇒ 空列表（不造假单）
     */
    @Transactional(rollbackFor = Exception.class)
    public List<FinishedGoodsStock> receiveOnPack(Order order, Long tenantId, String operator) {
        List<FinishedGoodsStock> existing = stockMapper.selectInStockByOrder(tenantId, order.getId());
        // 🔴 V197（issue #7762）：有部位码 ⇒ 按「套 × 部位」逐行入库（5 套 × 布帘 = 5 行；issue #8103 起
        // 同一订单固定同一个仓位，不再一行一个仓位）；
        // 没有码（布料单 / 未印码的历史单）⇒ 退回 V196 的订单行粒度（不造空行）。
        // 🔴 issue #7845：**先判有没有部位码，再判"是否已有在库行"** —— 打包工人扫码报工已经按件入过库的
        // 那些 token 必须跳过、**剩余部位照常补入**；改前「只要有一行在库就整单返回」会让其余部位永远不入库。
        List<com.migao.admin.entity.ProcessingSetPartToken> tokens =
                tokenMapper.selectByOrderId(tenantId, order.getId());
        if (!tokens.isEmpty()) {
            return receiveOnPackByTokens(order, tenantId, operator, tokens);
        }
        if (!existing.isEmpty()) {
            log.info("[成品入库] 本单已有在库成品行（无部位码），跳过重复入库: tenant={}, orderNo={}, bins={}",
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
        // 🔴 issue #7845：扫码报工**已按件入过库**的那些 token 跳过（只补剩余部位），否则订单打包动作
        // 会因为「已有在库行」而整单跳过 ⇒ 其余部位永远不入库（一单只进一件，库存与标签都对不上）。
        java.util.Set<String> inStock = new java.util.HashSet<>();
        for (FinishedGoodsStock row : stockMapper.selectInStockByOrder(tenantId, order.getId())) {
            if (row.getSetId() != null && row.getOrderItemId() != null) {
                inStock.add(row.getSetId() + "|" + row.getOrderItemId());
            }
        }
        List<com.migao.admin.entity.InboundOrderItem> lines = new ArrayList<>();
        int skipped = 0;
        int already = 0;
        for (com.migao.admin.entity.ProcessingSetPartToken token : tokens) {
            if (inStock.contains(token.getSetId() + "|" + token.getOrderItemId())) {
                already++;
                continue;
            }
            OrderItem item = itemById.get(token.getOrderItemId());
            if (item == null) {
                skipped++;
                continue;
            }
            lines.add(inboundLineOf(order, token, item));
        }
        if (lines.isEmpty()) {
            if (already > 0) {
                // 全部已在库（扫码先入）⇒ 不建第二张单，如实返回既有在库行
                List<FinishedGoodsStock> rows = stockMapper.selectInStockByOrder(tenantId, order.getId());
                log.info("[成品入库] 部位码全部已在库（扫码先入），跳过重复入库: tenant={}, orderNo={}, already={}, bins={}",
                        tenantId, order.getOrderNo(), already, binsOf(rows));
                return rows;
            }
            // 码全是陈旧引用（订单行已删）⇒ 不造假单，退回订单行粒度
            log.warn("[成品入库] 部位码全部挂不到订单行，退回订单行粒度: tenant={}, orderNo={}, skipped={}",
                    tenantId, order.getOrderNo(), skipped);
            return receiveOnPackByItems(order, tenantId, operator);
        }
        Warehouse warehouse = warehouseService.ensureFinishedWarehouse(tenantId);
        inboundOrderService.receiveFinishedGoodsLines(tenantId, order, lines,
                warehouse.getId(), warehouse.getName(), operator);
        List<FinishedGoodsStock> rows = stockMapper.selectInStockByOrder(tenantId, order.getId());
        log.info("[成品入库] 打包入库（套×部位）完成: tenant={}, orderNo={}, tokens={}, already={}, skipped={}, bins={}",
                tenantId, order.getOrderNo(), lines.size(), already, skipped, binsOf(rows));
        return rows;
    }

    /** 一条「套 × 部位」入库明细（**唯一**构造点：订单打包入库与扫码报工入库共用一份字段口径）。 */
    private com.migao.admin.entity.InboundOrderItem inboundLineOf(Order order,
                                                                  com.migao.admin.entity.ProcessingSetPartToken token,
                                                                  OrderItem item) {
        com.migao.admin.entity.ProcessingOrderSet set = token.getSetId() == null
                ? null : setMapper.selectById(token.getSetId());
        return com.migao.admin.entity.InboundOrderItem.builder()
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
                .build();
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

    // ============================================================ 扫码报工 ⇒ 成品入库（issue #7845）

    /**
     * 本次报工是不是**打包工序**（issue #7845）—— 成品入库只绑在打包这一道。
     *
     * <p>用户口径（2026-10-26 逐字）：「只有打包工序绑定了成品帘入库，如果是打包工人，那扫码后
     * 除了自动报工，还需要生成成品入库单」「打包通常是最后一个工序，打包扫码报工时就需要
     * 确认质检结果和成品入库&打入库标签」。</p>
     *
     * <p>关键词与授权判据**同一个常量**（{@link com.migao.admin.mapper.ProductionWorkLogMapper#PACK_OPERATION_KEYWORD}），
     * 不在这里另写一份「打包」字面量。</p>
     */
    public static boolean isPackOperation(String operationName) {
        return operationName != null
                && operationName.contains(com.migao.admin.mapper.ProductionWorkLogMapper.PACK_OPERATION_KEYWORD);
    }

    /**
     * 打包工序**报工即入库**（issue #7845）：这一件（套 × 部位）进成品仓、分配仓位、生成成品入库单。
     *
     * <p>幂等：这张唛已有在库行 ⇒ 直接返回它（{@code already=true}），**不建第二张单**、不重复占仓位。
     * 与订单打包动作（{@link #receiveOnPack}）共用同一条明细构造（{@link #inboundLineOf}）与同一张表/号段；
     * 订单打包时由 {@code receiveOnPackByTokens} 跳过已入的 token 只补剩余。</p>
     *
     * @param order 业务订单（报工侧已解析好，避免这里再查一次）
     * @param key   扫到的码（token / 短码 / 整条印刷 URL 均可）
     * @return 入库块（{@code inbound_no / bin_code / label / quality / already}）；
     *         <b>不是部位码</b> / 码挂不到订单行 ⇒ {@code null}（调用方据此不渲染卡片，不编造）
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> receiveByScanReport(Long tenantId, Order order, String key, String operator) {
        com.migao.admin.entity.ProcessingSetPartToken token = StringUtils_resolveToken(tenantId, key);
        if (token == null) {
            return null;
        }
        FinishedGoodsStock existing = stockMapper.selectInStockByWashLabel(tenantId, token.getToken());
        if (existing != null) {
            log.info("[成品入库] 扫码报工：这件已在库，返回既有入库单: tenant={}, bin={}, inboundNo={}",
                    tenantId, existing.getBinCode(), existing.getInboundNo());
            return inboundView(tenantId, token, existing, true);
        }
        OrderItem item = token.getOrderItemId() == null ? null : orderItemMapper.selectById(token.getOrderItemId());
        if (item == null) {
            log.warn("[成品入库] 扫码报工：码挂不到订单行，跳过入库: tenant={}, orderItemId={}",
                    tenantId, token.getOrderItemId());
            return null;
        }
        Warehouse warehouse = warehouseService.ensureFinishedWarehouse(tenantId);
        com.migao.admin.dto.InboundOrderResponse doc = inboundOrderService.receiveFinishedGoodsLines(tenantId, order,
                List.of(inboundLineOf(order, token, item)), warehouse.getId(), warehouse.getName(), operator);
        FinishedGoodsStock row = stockMapper.selectInStockByWashLabel(tenantId, token.getToken());
        if (row == null) {
            // 建单成功但没占到仓位 = 唯一索引竞争（同一件被并发入了）⇒ 以库里的事实为准
            log.warn("[成品入库] 扫码报工：入库单已建但没查到在库行（并发竞争？）: tenant={}, inboundNo={}",
                    tenantId, doc == null ? null : doc.getInboundNo());
            return null;
        }
        log.info("[成品入库] 扫码报工入库完成: tenant={}, orderNo={}, bin={}, inboundNo={}",
                tenantId, order.getOrderNo(), row.getBinCode(), row.getInboundNo());
        return inboundView(tenantId, token, row, false);
    }

    /**
     * 扫到一张**已入库**的唛 ⇒ 把入库块摆回屏上（issue #7845：刷新 / 回退后卡片不丢）。
     *
     * @return 同上入库块；未入库 / 不是部位码 ⇒ {@code null}
     */
    public Map<String, Object> completedInboundView(Long tenantId, String key) {
        com.migao.admin.entity.ProcessingSetPartToken token = StringUtils_resolveToken(tenantId, key);
        if (token == null) {
            return null;
        }
        FinishedGoodsStock stock = stockMapper.selectInStockByWashLabel(tenantId, token.getToken());
        return stock == null ? null : inboundView(tenantId, token, stock, true);
    }

    /**
     * 入库块（页面「成品入库」卡片的**唯一**数据源）。
     *
     * <p>质检结论随块下发：打包工人要在报工时「确认质检结果」，而质检读面对他们不一定开放
     * （{@code WorkerQualityController#requireInspector}）⇒ 由服务端带出来，页面不另发一次读请求。
     * 未接质检服务（切片测试装配 / 老上下文）⇒ {@code quality=null}（页面写「正常」，不编造判定）。</p>
     */
    private Map<String, Object> inboundView(Long tenantId,
                                            com.migao.admin.entity.ProcessingSetPartToken token,
                                            FinishedGoodsStock stock, boolean already) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("already", already);
        out.put("bin_code", stock.getBinCode());
        out.put("inbound_no", stock.getInboundNo());
        out.put("label", labelOf(tenantId, token, stock));
        // 质检读不到（未接线 / 码上缺订单行 / 读面异常）⇒ null（页面写「正常」），**绝不**让一张卡片
        // 把归一屏扫码打挂（质检结论是辅助信息，不是入库的前提）。
        Object quality = null;
        if (qualityCheckService != null && StringUtils.hasText(token.getOrderItemId())) {
            try {
                quality = qualityCheckService.latest(tenantId, token.getOrderItemId());
            } catch (RuntimeException e) {
                log.warn("[成品入库] 质检结论读不到（不影响入库与报工）: tenant={}, itemId={}, error={}",
                        tenantId, token.getOrderItemId(), e.getMessage());
            }
        }
        out.put("quality", quality);
        return out;
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
        // 🔴 纸面标签统一叫「帘种」（issue #7856；用户 2026-10-26「都要加上帘种」）：
        // 值仍取部位码的 `positionKind`（= 快照 `curtainType` 派生，同一条取值链）。
        addRow(rows, "帘种", token.getPositionKind() == null || token.getPositionKind().isBlank()
                ? (item == null ? null : item.getCurtainType()) : token.getPositionKind());
        // 安装去向（issue #7856）：订单级「安装小区」+ 件级「安装位置」，真值都在订单行
        // `processing_info` 顶层（零迁移）。空值不落键、不上纸（与纸面族同一口径）。
        addRow(rows, "安装小区", installInfoOf(item, OrderInstallInfo.KEY_INSTALL_COMMUNITY));
        addRow(rows, "安装位置", installInfoOf(item, OrderInstallInfo.KEY_INSTALL_ROOM));
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

    /**
     * 读订单行 {@code processing_info} 顶层的安装信息（issue #7856）。
     *
     * <p>真值 = `order_items.processing_info.installCommunity|installRoom`（零迁移）；
     * 缺键 / 空值 / 解析失败 ⇒ {@code null}（{@link #addRow} 据此**整行不印**，不编造）。</p>
     *
     * <p>🔴 {@code ObjectMapper} 用**字段注入 + required=false**：本类的构造签名被既有测试直接
     * {@code new} 装配（见 {@code qualityCheckService} 同一条注释），不能为它加构造参数；
     * 测试里没有 mapper ⇒ 该两行不出现（= 缺值口径），不会 NPE。</p>
     */
    private String installInfoOf(OrderItem item, String key) {
        if (item == null || item.getProcessingInfo() == null || objectMapper == null) {
            return null;
        }
        return OrderInstallInfo.valueOf(item.getProcessingInfo(), key, objectMapper);
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
        // issue #7792：单号来自 selectInStock 的 join 投影（inbound_orders.inbound_no）；
        // inboundOrderId 仍是内部 id，原样保留 = 契约冻结（其它调用方按 id 定位单据）。
        view.setInboundNo(row.getInboundNo());
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
