package com.migao.admin.service;

import com.migao.admin.dto.OrderCreateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 订单<b>库存与销量族</b>服务（issue #8191，P2-1c）。
 *
 * <p>从 {@link OrderService}（2,685 行）拆出的<b>库存面</b>：下单/确认支付前的库存前置校验、
 * 扣减与回补（商品级销量 + SKU 级库存）、以及它们共用的 SKU 定位判据
 * （{@code matchSkuId} 键族：ID 直查 / 组合回退 / 字符串族回退 + 失败即拒绝）。</p>
 *
 * <p>拆的是<b>位置</b>，<b>不是行为</b>：方法体逐字搬运（分支 / 异常类型与话术 / 日志 / 空值语义不变），
 * {@code @Transactional} 跟着方法走（本族只有 {@code restoreStockForReturn} 带事务注解）；
 * {@link OrderService} 保留同名门面委托，现有调用方（控制器 / 其它服务 / 既有单测）零改动。</p>
 *
 * <p><b>单向依赖</b>：本类只依赖 Mapper 与 {@link StockLedgerService}，<b>不</b>反向引用
 * {@link OrderService}（搬走的是整条闭包 ⇒ 不需要门面提供任何共享部件）。</p>
 *
 * <p><b>有意不搬</b>：批次消耗台账访问器 {@code batchStock()} 仍在 {@link OrderService}
 * （{@code cancelOrder} 的加工单作废路径在用，与库存族无关）；整卷分配 {@code applyRollAllocation}、
 * 状态流转与金额计算也不在本期（P2-1c/P2-1d 的后续边界）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrderStockService {

    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProductMapper productMapper;
    private final ProductSkuMapper productSkuMapper;
    private final StockLedgerService stockLedgerService;

    /**
     * 校验订单明细对应的 SKU 库存是否充足（按 processingInfo 匹配 SKU，判据见 {@link #matchSkuId}）。
     * 未声明 SKU 身份的明细不校验（对应无 SKU 扣减）；声明了身份却定位不到 ⇒ 显式拒绝。
     *
     * @param order       订单（已落库，明细从 order_item 表加载）
     * @throws BusinessException 库存不足、或规格无法定位到 SKU 时抛出业务异常
     */
    void validateStockSufficient(Order order) {
        if (order == null || order.getId() == null) {
            return;
        }
        List<OrderItem> items = orderItemMapper.selectList(
                new LambdaQueryWrapper<OrderItem>().eq(OrderItem::getOrderId, order.getId()));
        validateStockSufficientForItems(items, "确认支付");
    }

    /**
     * 创建订单前的库存校验入口（issue #2922：库存不足提示前移至下单时）。
     * 与确认支付共用 validateStockSufficientForItems 的同一套 SKU 匹配/库存口径。
     *
     * @param request     创建订单请求
     * @param actionLabel 动作文案（如「下单」），用于错误提示
     */
    void validateStockSufficientForRequest(OrderCreateRequest request, String actionLabel) {
        if (request.getItems() == null || request.getItems().isEmpty()) {
            return;
        }
        List<OrderItem> draftItems = new ArrayList<>(request.getItems().size());
        for (OrderCreateRequest.OrderItemRequest itemRequest : request.getItems()) {
            OrderItem draft = new OrderItem();
            draft.setProductId(itemRequest.getProductId());
            draft.setProductName(itemRequest.getProductName());
            draft.setQuantity(itemRequest.getQuantity());
            draft.setProcessingInfo(itemRequest.getProcessingInfo());
            draftItems.add(draft);
        }
        validateStockSufficientForItems(draftItems, actionLabel);
    }

    /**
     * 核心库存校验：遍历明细，按 processingInfo 匹配 SKU（单一判据 {@link #matchSkuId}）并校验库存充足。
     * 未声明 SKU 身份的明细不校验（对应无 SKU 扣减，与确认支付/扣减语义一致）；
     * 声明了身份却定位不到 ⇒ 显式拒绝（fail-closed，issue #4090）。
     *
     * @param items      订单明细（已落库的 OrderItem 或下单请求构造的草稿明细均可）
     * @param actionLabel 动作文案（如「下单」/「确认支付」），用于错误提示
     * @throws BusinessException 库存不足、或规格无法定位到 SKU 时抛出业务异常
     */
    void validateStockSufficientForItems(List<OrderItem> items, String actionLabel) {
        if (items == null) {
            return;
        }
        for (OrderItem item : items) {
            // 单一判据（issue #4090）：null 的唯一含义 = 该明细未声明 SKU 身份（合法，无 SKU 级库存）；
            // 声明了身份却定位不到 ⇒ matchSkuId 直接抛（可行动话术），不在这里静默 continue
            Long skuId = matchSkuId(item, actionLabel);
            if (skuId == null || item.getQuantity() == null) {
                continue;
            }
            ProductSku sku = productSkuMapper.selectById(skuId);
            BigDecimal stock = StockQuantity.orZero(sku != null ? sku.getStock() : null);
            // issue #5063（V115）：库存列已与订单数量同为小数（NUMERIC(12,1)）⇒ 按**真实数量**比较。
            // 改前是 `int needed = item.getQuantity().intValue()`：买 0.5 米 ⇒ needed = 0
            // ⇒ 校验**恒通过**（超卖防线被绕过）；买 2.7 米 ⇒ 只按 2 米校验（少校验 0.7 米）。
            // 校验值与实际扣减值必须**同源**（同一个 StockQuantity.toStockScaleByCeiling），
            // 否则会出现「校验通过却扣不动」/「校验拦住却本来够」。见该类里对该函数的理由说明。
            BigDecimal needed = StockQuantity.toStockScaleByCeiling(item.getQuantity());
            if (stock.compareTo(needed) < 0) {
                throw BusinessException.validationError(
                        String.format("商品「%s」库存不足：需要 %s 米，当前仅剩 %s 米，请先补货后再%s",
                                item.getProductName() != null ? item.getProductName() : skuId,
                                needed.toPlainString(), stock.toPlainString(), actionLabel));
            }
        }
    }

    /**
     * 确认支付后：扣减库存 + 增加销量（商品级 + SKU级）
     */
    void deductStockAndIncreaseSales(String orderId) {
        adjustStockAndSales(orderId, true, StockLedger.REASON_ORDER);
    }

    /**
     * 取消/退款后：恢复库存 + 减少销量（商品级 + SKU级）
     */
    void restoreStockAndDecreaseSales(String orderId) {
        adjustStockAndSales(orderId, false, StockLedger.REASON_ORDER);
    }

    /**
     * 售后退货回补库存（issue #2991）。
     *
     * 仅由 AfterSalesTicketService 在售后工单 refund/return 完结且订单全部商品
     * allow_return_restock=true（允许退货回补库存）时调用；复用取消订单的库存恢复路径
     * （恢复商品级+SKU级库存并减少销量）。窗帘行业定制退货不可再售，默认不走到本路径。
     *
     * <p>台账（issue #4137）：本路径的这次变更由**调用方** AfterSalesTicketService 落
     * {@code reason=aftersales} 行（它按「调用前快照 vs 调用后实际值」比对）——故这里传
     * {@code null} 不重复记账：同一次变更写两行会让 delta 翻倍，且两行的 before 互不相同
     * （相邻行首尾接不上，「库存为什么从 X 变成 Y」就答错了）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    void restoreStockForReturn(String orderId) {
        adjustStockAndSales(orderId, false, null);
        log.info("售后退货回补库存完成: orderId={}", orderId);
    }

    /**
     * 统一的库存和销量调整逻辑
     *
     * @param orderId      订单ID
     * @param isDeduct     true=扣库存+增销量（确认支付），false=恢复库存+减销量（取消/退款）
     * @param ledgerReason 台账变更来源（{@link StockLedger#REASON_ORDER}）；
     *                     {@code null} = 本次变更的落账由上游站点负责（售后回补 → aftersales）
     */
    @SuppressWarnings("unchecked")
    void adjustStockAndSales(String orderId, boolean isDeduct, String ledgerReason) {
        List<OrderItem> items = orderItemMapper.selectList(
                new LambdaQueryWrapper<OrderItem>().eq(OrderItem::getOrderId, orderId));
        if (items.isEmpty()) return;

        Order order = orderMapper.selectById(orderId);
        if (order == null) return;

        // 按 productId 聚合数量和金额
        // issue #3666：数量放宽为 BigDecimal，聚合也用 BigDecimal（不引入 double/float）；
        // issue #5063（V115）：销量列已同为 NUMERIC(12,1) ⇒ 不再取整数部分
        // （改前 `entry.getValue().intValue()` 会把「卖 2.7 米、销量 +2」的落差静默吃掉）。
        Map<String, BigDecimal> productQtyMap = new java.util.HashMap<>();
        Map<String, BigDecimal> productAmountMap = new java.util.HashMap<>();

        for (OrderItem item : items) {
            if (item.getProductId() == null) continue;
            BigDecimal qty = item.getQuantity() != null ? item.getQuantity() : BigDecimal.ZERO;
            BigDecimal amount = item.getSubtotal() != null ? item.getSubtotal() : BigDecimal.ZERO;
            productQtyMap.merge(item.getProductId(), qty, BigDecimal::add);
            productAmountMap.merge(item.getProductId(), amount, BigDecimal::add);

            // SKU级库存调整：从 processingInfo 中匹配 SKU
            if (isDeduct) {
                deductSkuStock(item, order, ledgerReason);
            } else {
                restoreSkuStock(item, order, ledgerReason);
            }
        }

        // 商品级调整
        for (Map.Entry<String, BigDecimal> entry : productQtyMap.entrySet()) {
            String productId = entry.getKey();
            BigDecimal totalQty = StockQuantity.toStockScaleByCeiling(entry.getValue());
            BigDecimal totalAmount = productAmountMap.getOrDefault(productId, BigDecimal.ZERO);
            if (isDeduct) {
                productMapper.increaseSales(productId, totalQty, totalAmount);
            } else {
                productMapper.decreaseSales(productId, totalQty, totalAmount);
            }
        }
    }

    /**
     * 从 OrderItem 的 processingInfo 中匹配 SKU 并扣减库存（issue #4137：并落订单腿台账行）。
     *
     * <p>判据见 {@link #matchSkuId}：{@code null} 只可能是「未声明 SKU 身份」；
     * 声明了却定位不到会直接抛，不会静默跳过（issue #4090）——即「库存/销量/台账三者同生共死」。</p>
     */
    @SuppressWarnings("unchecked")
    void deductSkuStock(OrderItem item, Order order, String ledgerReason) {
        Long skuId = matchSkuId(item, "确认支付");
        if (skuId != null && item.getQuantity() != null) {
            // issue #5063（V115）：库存/销量列已同为 NUMERIC(12,1) ⇒ 按**真实米数**扣减。
            // 改前 `item.getQuantity().intValue()` 把 2.7 米扣成 2 米（0.7 米凭空消失）、
            // 0.5 米扣成 0（成交但零变动）。口径与 §8「用料米数向上进位到 0.1」同源，
            // 且与库存前置校验、回补侧**同一个函数**（同笔单净变化恒为 0）。
            BigDecimal deductQty = StockQuantity.toStockScaleByCeiling(item.getQuantity());
            // 🔴 issue #6299：扣减是**一条带下限谓词的原子条件更新**，返回 null = 库存不够
            //（并发下另一个请求刚把库存扣走，或前置校验与扣减之间被别的事务改小）。
            // 改前的 `GREATEST(..., 0)` 会把这种情况**静默钳到 0**：两单都「成功」、
            // 库存 10 米只扣了 10（应扣 16）⇒ 超卖 6 米且无任何 4xx。
            StockChange change = StockChange.from(productSkuMapper.deductStock(skuId, deductQty, order.getTenantId()));
            if (change == null) {
                throw BusinessException.validationError(
                        String.format("商品「%s」库存不足：需要 %s 米，当前库存已被并发订单占用，请先补货后再确认支付",
                                item.getProductName() != null ? item.getProductName() : skuId,
                                deductQty.toPlainString()));
            }
            productSkuMapper.increaseSalesCount(skuId, deductQty);
            // 台账读数与扣减**同源**（同一条 SQL 的 RETURNING）：并发下 before/after 仍首尾相接
            recordAtomicStockChange(ledgerReason, order, item.getProductId(), skuId, change,
                    "订单确认支付扣减库存");
        }
    }

    /**
     * 从 OrderItem 的 processingInfo 中匹配 SKU 并恢复库存（issue #4137：并落订单腿台账行）。
     *
     * <p>与扣减侧同一判据 {@link #matchSkuId}（issue #4090）。</p>
     */
    void restoreSkuStock(OrderItem item, Order order, String ledgerReason) {
        Long skuId = matchSkuId(item, "取消回补");
        if (skuId != null && item.getQuantity() != null) {
            StockChange change = restoreStockForLedger(skuId, item);
            productSkuMapper.decreaseSalesCount(skuId, StockQuantity.toStockScaleByCeiling(item.getQuantity()));
            if (change != null) {
                recordAtomicStockChange(ledgerReason, order, item.getProductId(), skuId, change,
                        "订单取消/退款回补库存");
            }
        }
    }

    /**
     * 回补侧：与扣减侧**同一个函数、同一口径**（issue #5063）⇒ 扣 2.8 就回补 2.8。
     *
     * <p>台账读数与扣减同源（issue #6300）：回补的 before 也取<b>回补后</b>的库存减回补量，
     * 即扣减行的 after —— 两条腿的链在并发取消/确认交错时仍能首尾相接。</p>
     */
    StockChange restoreStockForLedger(Long skuId, OrderItem item) {
        BigDecimal restoreQty = StockQuantity.toStockScaleByCeiling(item.getQuantity());
        productSkuMapper.restoreStock(skuId, restoreQty);
        ProductSku after = productSkuMapper.selectById(skuId);
        if (after == null || after.getStock() == null) {
            // 读不到 = 回补未真正发生（或库存未知）⇒ 不落行，绝不用假读数污染台账链
            return null;
        }
        // before = 回补**之后**的库存减掉本次回补量 = 扣减行的 after（扣减/回补两腿共用同一张链）
        return new StockChange(after.getStock().subtract(restoreQty), after.getStock(), after.getSkuCode());
    }

    /**
     * 库存台账（issue #4137 / #6300）：按**原子语句给出的**变更前/变更后落一行。
     *
     * <p>改前走的是 {@code snapshotForLedger} → {@code recordChangesAgainstSnapshot}：
     * 先 {@code SELECT stock} 取快照、改库、再读一次比对。并发下两个请求会读到<b>同一个 before</b>
     * ⇒ 台账两行同基、链断裂（净增量仍对，所以只有查台账链才暴露）。现在读数直接来自
     * 扣减/回补那条 SQL 的 {@code RETURNING}（{@link StockChange}），<b>类型上没有「从快照构造」的入口</b>。</p>
     *
     * <p>{@code ledgerReason == null} = 本次变更的落账由上游站点负责（售后回补 → aftersales），
     * 这里不落行 —— 同一次变更写两行会让 delta 翻倍。</p>
     */
    void recordAtomicStockChange(String ledgerReason, Order order, String productId,
                                         Long skuId, StockChange change, String note) {
        // atomic-ledger: true —— before/after 来自原子语句的 RETURNING（见 StockChange 的类注释）
        if (ledgerReason == null || order == null || change == null) {
            return;
        }
        stockLedgerService.record(order.getTenantId(), productId, skuId, change.skuCode(),
                change.beforeQuantity(), change.afterQuantity(), ledgerReason, order.getOrderNo(), note);
    }

    /**
     * 库存路径的<b>单一判据</b>（issue #4090）：该明细是否声明了 SKU 身份、能否定位到 SKU。
     *
     * <p>processingInfo 键族：{@code { "skuId": N, "skuCode": "...", "colorId": N,
     * "colorName": "...", "doorWidth": "...", ... }}。
     * <b>三种结果，只有一种允许「不做 SKU 级库存调整」</b>：</p>
     * <ul>
     *   <li>{@code null} —— 明细<b>没有声明 SKU 身份键</b>（{@code skuId/skuCode/colorId/colorName}
     *       全空）：该明细没有「选了哪个 SKU」的语义（只带加工项 / 售卖方式 / 门幅也是本仓合法形态，
     *       见 {@code OrderQuantityDecimalTest} 的真实 fixture），故不做 SKU 级库存调整
     *       （商品级销量照记）。这是<b>唯一</b>合法的跳过 —— 库存校验 / 扣减 / 销量 / 回补四处
     *       都只按这一条判据分支，不再各写一套「有没有规格」的判断；</li>
     *   <li>{@code skuId} —— 唯一定位到 SKU（四处都按它走）；</li>
     *   <li>{@link BusinessException} —— 声明了 SKU 身份却<b>定位不到</b>：显式失败 + 可行动
     *       suggestion（声明了哪些键、该补什么），<b>不再静默跳过</b>。</li>
     * </ul>
     *
     * <p><b>为什么「定位不到」必须显式失败（issue #4090 实证）</b>：库存校验 / 扣减 / 销量三处
     * 都写成 {@code if (skuId != null)}，而匹配原先只认 <b>ID 族</b>（{@code skuId}，或
     * {@code colorId+sellingMethod+doorWidth}）；唯一生产者 ai-agent（{@code order_create}）
     * 只能产出<b>字符串族</b>（{@code skuCode/colorName/sellingMethod/doorWidth} ——
     * {@code product_detail._format_skus} 既不给 {@code color_id} 也不给 {@code skuId}）
     * ⇒ 键族不相交 ⇒ 三处同时静默跳过：顾客下单成功、SKU 库存不动、销量不涨、无任何失败
     * （可超卖、账实不符、线上不可归因）。修法两步：① 判定**能读字符串族**
     * （{@code product_skus.sku_code / color_name} 就是同一行上的原值）；② 仍然定位不到时
     * **显式拒绝**而不是放行。</p>
     *
     * <p>口径统一（issue #3621 沿用）：带单位门幅（{@code 2.8米}）用 {@link SkuNotation}
     * 双侧归一化比较，只归一化<b>匹配比较</b>、不回写库内值；陈旧 {@code skuId} 先校验存在性，
     * 不存在则回退键族匹配（防主键漂移后 update 命中 0 行的静默失败）。</p>
     *
     * <p><b>V111（用户裁定 2026-09-21）</b>：键族由 {@code colorId+sellingMethod+doorWidth}
     * 收窄为 {@code colorId+doorWidth} —— 售卖方式不再是 SKU 组合维度（它上移为商品级
     * {@code products.selling_methods} 与订单行偏好 {@code order_items.selling_method}）。</p>
     *
     * @param actionLabel 动作文案（「下单」/「确认支付」/「取消回补」），用于错误提示
     */
    @SuppressWarnings("unchecked")
    Long matchSkuId(OrderItem item, String actionLabel) {
        if (item.getProductId() == null) return null;

        Object processingInfo = item.getProcessingInfo();
        if (!(processingInfo instanceof Map)) return null;
        Map<String, Object> info = (Map<String, Object>) processingInfo;

        Long skuId = toSkuKey(info.get("skuId"), "skuId", item);
        String skuCode = toSkuText(info.get("skuCode"));
        Long colorId = toSkuKey(info.get("colorId"), "colorId", item);
        String colorName = toSkuText(info.get("colorName"));
        // V111：processingInfo 里历史残留的 `sellingMethod` 键**不再参与 SKU 定位** ——
        // 售卖方式是商品级基础属性（products.selling_methods）+ 订单行偏好，
        // SKU 组合只有 颜色 × 门幅（用户裁定 2026-09-21）。该键仍在 processingInfo 里原样保留
        // （历史快照不回改），只是不再是键族的一维。
        String doorWidth = toSkuText(info.get("doorWidth"));

        // 未声明任何 SKU 身份键 → 无 SKU 级库存调整（唯一合法的跳过）
        if (skuId == null && skuCode == null && colorId == null && colorName == null) {
            return null;
        }

        // ① skuId 直查（ID 族最精确）：存在性 + 归属同商品 —— 主键漂移（agent 重建路径可能
        //    「删旧行 + 插新行」）后拿着陈旧 id 直接返回，会让扣减/回补 update 命中 0 行且完全静默
        if (skuId != null) {
            ProductSku byId = productSkuMapper.selectById(skuId);
            if (byId != null && belongsToProduct(byId, item.getProductId())) {
                return byId.getId();
            }
            log.warn("matchSkuId: processingInfo.skuId 不可用（库中不存在或不属于该商品），改走键族回退, action={}, orderId={}, productId={}, skuId={}",
                    actionLabel, item.getOrderId(), item.getProductId(), skuId);
        }

        // ② ID 族组合回退（V111：键族为 colorId + 门幅 —— 售卖方式已不是 SKU 维度）
        if (colorId != null && doorWidth != null) {
            ProductSku byCombination = findSkuByCombination(item.getProductId(), colorId, doorWidth);
            if (byCombination != null) {
                return byCombination.getId();
            }
        }

        // ③ 字符串族（issue #4090 新增）：skuCode / colorName(+colorId) + 门幅 ——
        //    唯一生产者 ai-agent 只能产出这一族，此前它必然落进 ④（静默跳过）
        ProductSku byKeyFamily = findSkuByKeyFamily(item.getProductId(), skuCode, colorId, colorName,
                doorWidth);
        if (byKeyFamily != null) {
            return byKeyFamily.getId();
        }

        // ④ 声明了 SKU 身份却定位不到（含命中多行无法唯一确定）⇒ 显式失败，可行动 suggestion
        log.warn("matchSkuId: 声明了 SKU 身份但键族定位不到（未命中或多行歧义）→ 显式拒绝该动作（不静默跳过）, action={}, orderId={}, productId={}, {}",
                actionLabel, item.getOrderId(), item.getProductId(),
                describeDeclaredSpec(skuCode, colorId, colorName, doorWidth));
        throw BusinessException.validationError(String.format(
                "商品「%s」的本次规格无法定位到 SKU（%s）：已声明 %s。"
                        + "无法确定该行对应哪个 SKU，故**拒绝**而不是放行（放行会造成「订单成交但库存不动、销量不涨」）。"
                        + "请用 product_detail 返回的 skus[] 原值核对规格（sku_code / color_name / door_width），"
                        + "或直接传 skuId（skus[].id）后重试。",
                item.getProductName() != null ? item.getProductName() : item.getProductId(),
                actionLabel,
                describeDeclaredSpec(skuCode, colorId, colorName, doorWidth)));
    }

    /**
     * 字符串族定位（issue #4090）：{@code skuCode} 精确匹配；{@code colorName/colorId} +
     * 已声明的门幅（双侧归一化）组合匹配。
     *
     * <p>命中必须<b>唯一</b>：多行命中意味着「规格不足以唯一确定 SKU」（如只给了颜色、该颜色下
     * 有多个门幅），此时返回 null 交由调用方显式拒绝 —— 任取一条会扣错 SKU 的库存，比拒绝更糟。</p>
     *
     * @return 唯一命中的 SKU；0 行或多行命中返回 null（调用方负责告警与拒绝）
     */
    ProductSku findSkuByKeyFamily(String productId, String skuCode, Long colorId, String colorName,
                                          String doorWidth) {
        if (skuCode == null && colorId == null && colorName == null) {
            return null;
        }
        LambdaQueryWrapper<ProductSku> wrapper = new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getProductId, productId)
                .eq(skuCode != null, ProductSku::getSkuCode, skuCode)
                .eq(colorId != null, ProductSku::getColorId, colorId)
                .eq(colorName != null, ProductSku::getColorName, colorName)
                .orderByAsc(ProductSku::getId);
        List<ProductSku> rows = productSkuMapper.selectList(wrapper);

        ProductSku found = null;
        int hits = 0;
        for (ProductSku row : rows == null ? List.<ProductSku>of() : rows) {
            // 门幅双侧归一化比较（库内 2.8 与明细 2.8米 同一物理门幅；2.8 vs 3.2 不等）
            if (doorWidth != null && !SkuNotation.sameDoorWidth(row.getDoorWidth(), doorWidth)) {
                continue;
            }
            if (found == null) {
                found = row;
            }
            hits++;
        }
        if (hits > 1) {
            log.warn("matchSkuId: 规格不足以唯一定位 SKU（{} 行命中）→ 交由调用方显式拒绝, productId={}, skuCode={}, colorId={}, colorName={}, doorWidth={}",
                    hits, productId, skuCode, colorId, colorName, doorWidth);
            return null;
        }
        return found;
    }

    /** 该 SKU 是否属于本明细的商品（库内 product_id 为空的历史行不据此排除）。 */
    boolean belongsToProduct(ProductSku sku, String productId) {
        return sku.getProductId() == null || sku.getProductId().equals(productId);
    }

    /** 规格键取值：非空文本去首尾空白；空串/空白视为未声明。 */
    String toSkuText(Object raw) {
        if (raw == null) return null;
        String text = raw.toString().trim();
        return text.isEmpty() ? null : text;
    }

    /** 规格键取值：数字键（skuId/colorId）解析失败时留 WARN 并视为未声明（不静默）。 */
    Long toSkuKey(Object raw, String key, OrderItem item) {
        if (raw == null) return null;
        try {
            return Long.valueOf(raw.toString().trim());
        } catch (NumberFormatException e) {
            log.warn("matchSkuId: {} 格式错误（非数字，视为未声明）, orderId={}, productId={}, value={}",
                    key, item.getOrderId(), item.getProductId(), raw);
            return null;
        }
    }

    /** 已声明的规格键描述（错误话术/告警用：说清「缺哪个键、该补什么」的依据）。 */
    String describeDeclaredSpec(String skuCode, Long colorId, String colorName,
                                        String doorWidth) {
        List<String> parts = new ArrayList<>();
        if (skuCode != null) parts.add("skuCode=" + skuCode);
        if (colorId != null) parts.add("colorId=" + colorId);
        if (colorName != null) parts.add("colorName=" + colorName);
        if (doorWidth != null) parts.add("doorWidth=" + doorWidth);
        return String.join(", ", parts);
    }

    /**
     * 组合回退匹配：商品 + 颜色（+ 门幅，Java 侧按
     * {@link SkuNotation#sameDoorWidth} 双侧归一化比较，库内 {@code 2.8} 与明细
     * {@code 2.8米} / {@code 门幅2.8米} 视为同一物理门幅；{@code 2.8} vs {@code 3.2} 不等）。
     *
     * <p>V111（用户裁定 2026-09-21）：售卖方式那一维已从本匹配里删除 —— SKU 组合只有
     * 颜色 × 门幅，售卖方式是商品级基础属性。同一组合命中多行时取第一条并告警，
     * 便于发现历史重复行。</p>
     *
     * @return 命中的 SKU；未命中返回 null（调用方负责告警，不再静默跳过）
     */
    ProductSku findSkuByCombination(String productId, Long colorId, String doorWidth) {
        List<ProductSku> candidates = productSkuMapper.selectList(
                new LambdaQueryWrapper<ProductSku>()
                        .eq(ProductSku::getProductId, productId)
                        .eq(ProductSku::getColorId, colorId));
        ProductSku found = null;
        int hits = 0;
        for (ProductSku candidate : candidates) {
            if (SkuNotation.sameDoorWidth(candidate.getDoorWidth(), doorWidth)) {
                if (found == null) {
                    found = candidate;
                }
                hits++;
            }
        }
        if (hits > 1) {
            log.warn("matchSkuId: 归一化后同一组合命中多行 SKU（库内可能存在同门幅重复行），取第一条: productId={}, colorId={}, doorWidth={}, hits={}",
                    productId, colorId, doorWidth, hits);
        }
        return found;
    }
}
