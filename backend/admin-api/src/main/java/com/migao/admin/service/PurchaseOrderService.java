package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.PurchaseOrderCreateRequest;
import com.migao.admin.dto.PurchaseOrderReceiveRequest;
import com.migao.admin.dto.PurchaseOrderView;
import com.migao.admin.entity.InboundOrder;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.PurchaseOrder;
import com.migao.admin.entity.PurchaseOrderItem;
import com.migao.admin.entity.PurchaseOrderReceipt;
import com.migao.admin.entity.Supplier;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.InboundOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.PurchaseOrderItemMapper;
import com.migao.admin.mapper.PurchaseOrderMapper;
import com.migao.admin.mapper.PurchaseOrderReceiptMapper;
import com.migao.admin.mapper.SupplierMapper;
import com.migao.admin.time.BusinessClock;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 采购单（issue #7369，P0-1 段 4）—— 按常见做法：**一单可分多次收货**，允许提前关闭（写原因）。
 *
 * <h3>为什么状态是派生值</h3>
 * <p>{@code status} 只由 {@link #receive} / {@link #close} 之后按 Σ收货数量重算，**请求体里没有这个字段**。
 * 若让客户端写状态，就会出现「单据说没收齐、实际收齐了」或反之 —— 而两种口径同时存在时，
 * 没有任何一处在说谎的瞬间会红。</p>
 *
 * <h3>五条硬约束</h3>
 * <ol>
 *   <li><b>收货不许超收</b>：本次数量 ≤ 该行「采购数量 − 已收」；</li>
 *   <li><b>只能在 ordered / partially_received 上收货</b>：closed / received 都不许再收
 *       （received 再收 = 单据数量是假的；closed 再收 = 关单决定被绕过）；</li>
 *   <li><b>关闭必须写原因</b>：断货 / 取消 / 到不齐都要留一句话，否则半年后没人知道为什么少了货；</li>
 *   <li><b>供应商必须在用</b>（建档 + 未停用）：停用的供应商可以继续付旧账，但不该再下新单；</li>
 *   <li><b>金额两位小数</b>（issue #6221）与<b>业务今天单点</b>（issue #3802）。</li>
 * </ol>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PurchaseOrderService {

    private static final DateTimeFormatter NO_DATE = DateTimeFormatter.ofPattern("yyyyMMdd");
    private static final BigDecimal ZERO = BigDecimal.ZERO.setScale(4);

    private final PurchaseOrderMapper orderMapper;
    private final PurchaseOrderItemMapper itemMapper;
    private final PurchaseOrderReceiptMapper receiptMapper;
    private final SupplierMapper supplierMapper;
    private final InboundOrderMapper inboundOrderMapper;
    /** 明细展示名（issue #7567）：按 skuId 反查商品 / 颜色 / 门幅 —— 收货面不许印雪花号。 */
    private final ProductSkuMapper skuMapper;
    private final ProductMapper productMapper;
    private final BusinessClock businessClock;

    /** 建单（状态一律 {@code ordered}；明细金额在这里算并冻结）。 */
    @Transactional(rollbackFor = Exception.class)
    public PurchaseOrderView create(PurchaseOrderCreateRequest req, Long tenantId, String operator) {
        String supplierId = trimToNull(req.supplierId());
        if (supplierId == null) {
            throw BusinessException.validationError("采购单必须指定供应商");
        }
        Supplier supplier = supplierMapper.selectById(supplierId);
        if (supplier == null) {
            throw BusinessException.notFound("供应商");
        }
        if (SupplierService.STATUS_INACTIVE.equals(supplier.getStatus())) {
            throw BusinessException.validationError(
                    "供应商已停用，不能下新采购单：若要继续采购，请先在「供应商」页启用它");
        }
        List<PurchaseOrderCreateRequest.Item> items = req.items();
        if (items == null || items.isEmpty()) {
            throw BusinessException.validationError("采购单至少要有一行明细");
        }

        LocalDate orderDate = req.orderDate() != null ? req.orderDate() : businessClock.today();

        // 先算清金额再落库：任何一行不合法都不许留下半张采购单
        BigDecimal total = ZERO;
        List<BigDecimal> amounts = new ArrayList<>();
        for (PurchaseOrderCreateRequest.Item item : items) {
            String skuId = trimToNull(item.skuId());
            if (skuId == null) {
                throw BusinessException.validationError("采购明细缺少 SKU");
            }
            // SKU 归属（issue #7568）：直连 API 曾能落「指向不存在 SKU」的明细 —— 收货面解析不到展示名、
            // 应付却照算。租户面由 MyBatis 租户拦截器兜（跨租户 selectById ⇒ null）⇒ 与「不存在」同一出口，
            // 不额外造一个能把「别家租户有这个 SKU」读出来的分支。
            ProductSku sku = skuMapper.selectById(skuId);
            if (sku == null) {
                throw BusinessException.validationError(
                        "采购明细的 SKU 不存在或不属于当前租户：请从选品器重新选择（skuId=" + skuId + "）");
            }
            String declaredProductId = trimToNull(item.productId());
            if (declaredProductId != null && !declaredProductId.equals(sku.getProductId())) {
                throw BusinessException.validationError(
                        "采购明细的商品与 SKU 不一致：SKU " + skuId + " 不属于商品 " + declaredProductId
                        + "，请重新选择");
            }
            BigDecimal qty = item.quantity();
            if (qty == null || qty.signum() <= 0) {
                throw BusinessException.validationError("采购数量必须大于 0（SKU " + item.skuId() + "）");
            }
            BigDecimal price = item.unitPrice() == null ? BigDecimal.ZERO : item.unitPrice();
            if (price.signum() < 0) {
                throw BusinessException.validationError("采购单价不能为负（SKU " + item.skuId() + "）");
            }
            // 金额准入（issue #6221）：钱只有两位小数的物理意义；超精度输入直接拒，不静默四舍五入
            price = MoneyScale.requireTwoDecimalsOrNull(price, "采购单价");
            BigDecimal amount = qty.multiply(price).setScale(2, RoundingMode.HALF_UP);
            amounts.add(amount);
            total = total.add(amount);
        }
        total = total.setScale(4, RoundingMode.HALF_UP);

        PurchaseOrder order = PurchaseOrder.builder()
                .tenantId(tenantId)
                .poNo(null)
                .supplierId(supplierId)
                .orderDate(orderDate)
                .expectedDate(req.expectedDate())
                .status(PurchaseOrder.STATUS_ORDERED)
                .totalAmount(total)
                .remark(req.remark())
                .createdBy(operator)
                .build();
        order.setPoNo(nextPoNo(tenantId, orderDate));
        insertOrderWithRetry(order);

        int line = 1;
        for (int i = 0; i < items.size(); i++) {
            PurchaseOrderCreateRequest.Item item = items.get(i);
            itemMapper.insert(PurchaseOrderItem.builder()
                    .tenantId(tenantId)
                    .purchaseOrderId(order.getId())
                    .lineNo(line++)
                    .skuId(item.skuId().trim())
                    .productId(trimToNull(item.productId()))
                    .quantity(item.quantity())
                    .unitPrice(item.unitPrice() == null ? BigDecimal.ZERO : item.unitPrice())
                    .amount(amounts.get(i))
                    .build());
        }
        return detail(order.getId(), tenantId);
    }

    /**
     * 登记收货（一次可多行）。
     *
     * <p>收完最后一行后按 Σ收货重算状态：全齐 ⇒ {@code received}，部分 ⇒ {@code partially_received}。
     * 收齐的这一刻**不自动关单**：收货与关单是两件事（还可能有一行永远到不了，那时走 close 写原因）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public PurchaseOrderView receive(String id, PurchaseOrderReceiveRequest req,
                                     Long tenantId, String operator) {
        PurchaseOrder order = requireOrder(id);
        if (PurchaseOrder.STATUS_CLOSED.equals(order.getStatus())) {
            throw BusinessException.validationError(
                    "采购单已关闭，不能再收货：" + order.getPoNo() + "（要续收请另开新单）");
        }
        if (PurchaseOrder.STATUS_RECEIVED.equals(order.getStatus())) {
            throw BusinessException.validationError(
                    "采购单已收齐，不能再收货：" + order.getPoNo());
        }
        List<PurchaseOrderReceiveRequest.Line> lines = req.lines();
        if (lines == null || lines.isEmpty()) {
            throw BusinessException.validationError("收货至少要有一行");
        }

        LocalDate receivedAt = req.receivedAt() != null ? req.receivedAt() : businessClock.today();
        Map<String, PurchaseOrderItem> itemsById = itemsOf(order.getId(), tenantId);

        // 第一遍：全部校验（任何一行不合法 ⇒ 一行都不落库，避免"收了一半"的半成品）
        for (PurchaseOrderReceiveRequest.Line line : lines) {
            String itemId = trimToNull(line.itemId());
            if (itemId == null) {
                throw BusinessException.validationError("收货行缺少采购明细 id");
            }
            PurchaseOrderItem item = itemsById.get(itemId);
            if (item == null) {
                throw BusinessException.notFound("采购明细");
            }
            BigDecimal qty = line.quantity();
            if (qty == null || qty.signum() <= 0) {
                throw BusinessException.validationError("收货数量必须大于 0（SKU " + item.getSkuId() + "）");
            }
            BigDecimal remaining = item.getQuantity().subtract(receivedOf(item.getId(), tenantId));
            if (qty.compareTo(remaining) > 0) {
                throw BusinessException.validationError(
                        "收货数量超出该行未收数量：SKU " + item.getSkuId()
                        + "（可收 " + remaining.stripTrailingZeros().toPlainString()
                        + "，本次 " + qty.stripTrailingZeros().toPlainString() + "）");
            }
            String inboundOrderId = trimToNull(line.inboundOrderId());
            if (inboundOrderId != null) {
                assertInboundOrderUsable(inboundOrderId, order, tenantId);
            }
        }

        for (PurchaseOrderReceiveRequest.Line line : lines) {
            receiptMapper.insert(PurchaseOrderReceipt.builder()
                    .tenantId(tenantId)
                    .purchaseOrderId(order.getId())
                    .purchaseOrderItemId(line.itemId())
                    .inboundOrderId(trimToNull(line.inboundOrderId()))
                    .quantity(line.quantity())
                    .receivedAt(receivedAt)
                    .remark(req.remark())
                    .createdBy(operator)
                    .build());
        }
        return recalcStatusAndView(order, itemsById.keySet(), tenantId);
    }

    /**
     * 关闭采购单（提前关闭 / 断货 / 取消 —— **必须写原因**）。
     *
     * <p>为什么不删单：删了就没有「当初为什么买、后来为什么没到」的痕迹，而补货决策恰恰要看这个。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public PurchaseOrderView close(String id, String reason, Long tenantId, String operator) {
        PurchaseOrder order = requireOrder(id);
        if (PurchaseOrder.STATUS_CLOSED.equals(order.getStatus())) {
            throw BusinessException.validationError("采购单已关闭：" + order.getPoNo());
        }
        if (PurchaseOrder.STATUS_RECEIVED.equals(order.getStatus())) {
            throw BusinessException.validationError(
                    "采购单已收齐，无需关闭：" + order.getPoNo() + "（收齐就是终态）");
        }
        String why = trimToNull(reason);
        if (why == null) {
            throw BusinessException.validationError("关闭采购单必须写原因（断货 / 取消 / 到不齐都要留一句）");
        }
        order.setStatus(PurchaseOrder.STATUS_CLOSED);
        order.setClosedAt(OffsetDateTime.now());
        order.setClosedBy(operator);
        order.setClosedReason(why);
        orderMapper.updateById(order);
        return detail(order.getId(), tenantId);
    }

    /** 列表（可按状态 / 供应商过滤；新的在前）。 */
    public List<PurchaseOrderView> list(Long tenantId, String status, String supplierId) {
        LambdaQueryWrapper<PurchaseOrder> wrapper = new LambdaQueryWrapper<PurchaseOrder>()
                .eq(PurchaseOrder::getTenantId, tenantId)
                .eq(StringUtils.hasText(status), PurchaseOrder::getStatus, status)
                .eq(StringUtils.hasText(supplierId), PurchaseOrder::getSupplierId, supplierId)
                .orderByDesc(PurchaseOrder::getOrderDate)
                .orderByDesc(PurchaseOrder::getCreatedAt)
                .last("LIMIT 200");
        List<PurchaseOrderView> out = new ArrayList<>();
        for (PurchaseOrder order : orderMapper.selectList(wrapper)) {
            out.add(detail(order.getId(), tenantId));
        }
        return out;
    }

    /** 单张采购单读面（含逐行已收/未收与收货记录）。 */
    public PurchaseOrderView detail(String id, Long tenantId) {
        PurchaseOrder order = requireOrder(id);
        Map<String, PurchaseOrderItem> items = itemsOf(order.getId(), tenantId);

        Map<String, BigDecimal> receivedByItem = new HashMap<>();
        List<PurchaseOrderView.ReceiptView> receipts = new ArrayList<>();
        List<PurchaseOrderReceipt> rows = receiptMapper.selectList(
                new LambdaQueryWrapper<PurchaseOrderReceipt>()
                        .eq(PurchaseOrderReceipt::getTenantId, tenantId)
                        .eq(PurchaseOrderReceipt::getPurchaseOrderId, order.getId())
                        .orderByDesc(PurchaseOrderReceipt::getReceivedAt)
                        .orderByDesc(PurchaseOrderReceipt::getCreatedAt));
        for (PurchaseOrderReceipt row : rows) {
            receivedByItem.merge(row.getPurchaseOrderItemId(), row.getQuantity(), BigDecimal::add);
            receipts.add(new PurchaseOrderView.ReceiptView(
                    row.getId(), row.getPurchaseOrderItemId(), row.getQuantity(),
                    row.getReceivedAt(), row.getInboundOrderId()));
        }

        // 明细展示名（issue #7567）：N 行只做 2 次批量查询（SKU → 商品），不逐行回查。
        // 查不到（SKU 已删 / test 用假 id）⇒ 四个展示字段留 null，**绝不拿 skuId 冒充商品名**。
        Map<Long, ProductSku> skuById = skusOf(items.values(), tenantId);
        Map<String, Product> productById = productsOf(skuById.values(), tenantId);
        List<PurchaseOrderView.ItemView> itemViews = new ArrayList<>();
        for (PurchaseOrderItem item : items.values()) {
            BigDecimal received = receivedByItem.getOrDefault(item.getId(), ZERO);
            Long skuKey = parseId(item.getSkuId());
            ProductSku sku = skuKey == null ? null : skuById.get(skuKey);
            Product product = sku == null ? null : productById.get(sku.getProductId());
            itemViews.add(new PurchaseOrderView.ItemView(
                    item.getId(), item.getSkuId(), item.getProductId(),
                    item.getQuantity(), item.getUnitPrice(), item.getAmount(),
                    received, item.getQuantity().subtract(received),
                    product == null ? null : product.getName(),
                    sku == null ? null : sku.getSkuCode(),
                    sku == null ? null : sku.getColorName(),
                    sku == null ? null : sku.getDoorWidth()));
        }

        Supplier supplier = supplierMapper.selectById(order.getSupplierId());
        return new PurchaseOrderView(
                order.getId(), order.getPoNo(), order.getSupplierId(),
                supplier == null ? null : supplier.getName(),
                order.getOrderDate(), order.getExpectedDate(), order.getStatus(),
                order.getTotalAmount(), order.getRemark(),
                order.getClosedAt(), order.getClosedReason(), itemViews, receipts);
    }

    // ─────────────────────────────── 内部 ───────────────────────────────

    /** 按 SKU id 批量取规格（租户内；`skuId` 非数字 / 不存在 ⇒ 不进 map）。 */
    private Map<Long, ProductSku> skusOf(Collection<PurchaseOrderItem> items, Long tenantId) {
        Set<Long> ids = new java.util.LinkedHashSet<>();
        for (PurchaseOrderItem item : items) {
            Long id = parseId(item.getSkuId());
            if (id != null) {
                ids.add(id);
            }
        }
        if (ids.isEmpty()) {
            // 🔴 空集必须返回**可变**表（不是 `Map.of()`）：不可变空表的 `get(null)` 直接抛 NPE
            //    （issue #6219 实测语义）—— 展示名解析发生在读面上，500 的代价远大于省一行分配。
            //    类级判据 = `WorkerCuttingHeightNullProductIdTest` 的「空不可变表产出方」普查。
            return new HashMap<>();
        }
        List<ProductSku> rows = skuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getTenantId, tenantId)
                .in(ProductSku::getId, ids));
        Map<Long, ProductSku> out = new HashMap<>();
        if (rows != null) {
            for (ProductSku row : rows) {
                out.put(row.getId(), row);
            }
        }
        return out;
    }

    /** 按商品 id 批量取商品名（租户内）。 */
    private Map<String, Product> productsOf(Collection<ProductSku> skus, Long tenantId) {
        Set<String> ids = new java.util.LinkedHashSet<>();
        for (ProductSku sku : skus) {
            if (sku.getProductId() != null) {
                ids.add(sku.getProductId());
            }
        }
        if (ids.isEmpty()) {
            // 同上：可变空表（issue #6219 口径）
            return new HashMap<>();
        }
        List<Product> rows = productMapper.selectList(new LambdaQueryWrapper<Product>()
                .eq(Product::getTenantId, tenantId)
                .in(Product::getId, ids));
        Map<String, Product> out = new HashMap<>();
        if (rows != null) {
            for (Product row : rows) {
                out.put(row.getId(), row);
            }
        }
        return out;
    }

    /** 雪花号 / 数字串 → Long（非法或溢出 ⇒ null，不抛异常：展示名取不到不该让读面 500）。 */
    private static Long parseId(String raw) {
        String text = trimToNull(raw);
        if (text == null) {
            return null;
        }
        for (int i = 0; i < text.length(); i++) {
            if (!Character.isDigit(text.charAt(i))) {
                return null;
            }
        }
        try {
            return Long.valueOf(text);
        } catch (NumberFormatException overflow) {
            return null;
        }
    }


    /**
     * 按 Σ收货重算状态并返回读面。
     *
     * <p>「全齐」的判据是**每一行**都收满，而不是「总额到了」—— 少一个 SKU 就不算到货完成。</p>
     */
    private PurchaseOrderView recalcStatusAndView(PurchaseOrder order, Set<String> itemIds, Long tenantId) {
        boolean anyReceived = false;
        boolean allReceived = true;
        for (String itemId : itemIds) {
            PurchaseOrderItem item = itemMapper.selectById(itemId);
            if (item == null) {
                continue;
            }
            BigDecimal received = receivedOf(itemId, tenantId);
            if (received.signum() > 0) {
                anyReceived = true;
            }
            if (received.compareTo(item.getQuantity()) < 0) {
                allReceived = false;
            }
        }
        String nextStatus = !anyReceived ? PurchaseOrder.STATUS_ORDERED
                : (allReceived ? PurchaseOrder.STATUS_RECEIVED : PurchaseOrder.STATUS_PARTIALLY_RECEIVED);
        if (!nextStatus.equals(order.getStatus())) {
            order.setStatus(nextStatus);
            orderMapper.updateById(order);
        }
        return detail(order.getId(), tenantId);
    }

    private BigDecimal receivedOf(String itemId, Long tenantId) {
        List<PurchaseOrderReceipt> rows = receiptMapper.selectList(
                new LambdaQueryWrapper<PurchaseOrderReceipt>()
                        .eq(PurchaseOrderReceipt::getTenantId, tenantId)
                        .eq(PurchaseOrderReceipt::getPurchaseOrderItemId, itemId));
        BigDecimal sum = ZERO;
        for (PurchaseOrderReceipt row : rows) {
            sum = sum.add(row.getQuantity());
        }
        return sum;
    }

    private Map<String, PurchaseOrderItem> itemsOf(String orderId, Long tenantId) {
        List<PurchaseOrderItem> rows = itemMapper.selectList(
                new LambdaQueryWrapper<PurchaseOrderItem>()
                        .eq(PurchaseOrderItem::getTenantId, tenantId)
                        .eq(PurchaseOrderItem::getPurchaseOrderId, orderId)
                        .orderByAsc(PurchaseOrderItem::getLineNo));
        Map<String, PurchaseOrderItem> byId = new LinkedHashMap<>();
        for (PurchaseOrderItem item : rows) {
            byId.put(item.getId(), item);
        }
        return byId;
    }

    /** 关联的入库单必须本租户、已过账、且属于本采购单的供应商（否则「收到的货」与「买的货」对不上）。 */
    private void assertInboundOrderUsable(String inboundOrderId, PurchaseOrder order, Long tenantId) {
        InboundOrder inbound = inboundOrderMapper.selectById(inboundOrderId);
        if (inbound == null) {
            throw BusinessException.notFound("入库单");
        }
        if (!InboundOrder.STATUS_POSTED.equals(inbound.getStatus())) {
            throw BusinessException.validationError(
                    "只能关联**已过账**的入库单：" + inbound.getInboundNo());
        }
        if (!order.getSupplierId().equals(inbound.getSupplierId())) {
            throw BusinessException.validationError(
                    "入库单 " + inbound.getInboundNo() + " 不属于本采购单的供应商，不能关联");
        }
    }

    private PurchaseOrder requireOrder(String id) {
        PurchaseOrder order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("采购单");
        }
        return order;
    }

    /**
     * 落库采购单（撞唯一号则换号重试，最多 3 次）—— 两个人同一秒下单会算出同一个号。
     */
    private void insertOrderWithRetry(PurchaseOrder order) {
        for (int attempt = 0; attempt < 3; attempt++) {
            try {
                orderMapper.insert(order);
                return;
            } catch (DuplicateKeyException e) {
                order.setId(null);
                order.setPoNo(nextPoNo(order.getTenantId(), order.getOrderDate()));
                log.warn("采购单号撞车（第 {} 次），换号重试: tenant={}, no={}",
                        attempt + 1, order.getTenantId(), order.getPoNo());
            }
        }
        throw BusinessException.conflict(
                "采购单号连续冲突，建单未完成：" + order.getPoNo(),
                "请稍后重试；重复提交不会产生两张采购单");
    }

    private String nextPoNo(Long tenantId, LocalDate orderDate) {
        String prefix = "CG-" + orderDate.format(NO_DATE) + "-";
        long count = orderMapper.selectCount(new LambdaQueryWrapper<PurchaseOrder>()
                .eq(PurchaseOrder::getTenantId, tenantId)
                .likeRight(PurchaseOrder::getPoNo, prefix));
        return prefix + String.format("%04d", count + 1);
    }

    private static String trimToNull(String raw) {
        if (raw == null) {
            return null;
        }
        String trimmed = raw.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }
}
