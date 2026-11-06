package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.MaterialLabels;
import com.migao.admin.dto.ProductionPoolViews;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Duration;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static com.migao.admin.service.ProcessingOrderService.*;

/**
 * 加工单**派单池读面**单元（issue #8770「派单池」一档，从 {@link ProcessingOrderService} **纯搬运**）。
 *
 * <p><b>单一职责</b>：池的**只读视图** —— 取可派单（待付款 + 已确认、无活跃加工单）→ 逐单建快照 →
 * 按物料（{@code productId × skuCode}）分组 + 定序 + 等待 / 临期 / 加急 / 外发 / 库存可满足性回填；
 * 外加**成批闸**两条（加急单 / 外发单混进 {@code pooled=true} 批次 ⇒ 整批显式拒绝）。
 * <b>不写库</b>：本类没有任何写操作（只有 {@code selectList} / {@code selectActiveOrderIds} / 算料读面）。</p>
 *
 * <p><b>搬运口径</b>：方法体、注释、异常码与文案**一字未改**。改动只有三类，逐条可复算：
 * ① 可见性 7 处（{@code public pool} → 同包可见（公开入口仍在门面）；6 个 {@code private} → 同包可见）；
 * ② javadoc 里 3 处跨类 {@code @link} 限定到 {@link ProcessingOrderService}（那两个常量仍住门面）；
 * ③ 1 行 {@code businessClock.today()} → {@code today()}（时钟仍归门面，本类经 {@link Owner} 即时取值）。</p>
 *
 * <p><b>为什么快照 / 算料 / 时钟不搬过来</b>：{@code buildSnapshot} 与算料服务属**生成族**（上一档
 * #8725 的重启条件已明确留给后续档：事务与写库路径要真库判据），业务时钟是门面的注入点。复制一份
 * 就是第二份口径 ⇒ 本类只依赖窄接口 {@link Owner} **回调门面**，且**每次调用即时取值**
 * （不缓存 {@code BusinessClock} / {@code StockBatchConsumptionService}：既有判据用
 * {@code ReflectionTestUtils.setField} 在构造之后换时钟，缓存会读到旧值）。</p>
 */
class ProcessingOrderDispatchPool {

    /** 派单池对门面的**只读**外呼面（快照 / 时钟 / 算料 / 订单解析仍住门面：不复制第二份口径）。 */
    interface Owner {
        LocalDate today();

        List<OrderItem> loadOrderItems(String orderId, Long tenantId);

        List<Map<String, Object>> buildSnapshot(List<OrderItem> items, Long tenantId);

        StockBatchConsumptionService batchStock();

        Order resolveOrder(String rawId, Long tenantId);
    }

    private final OrderMapper orderMapper;
    private final ProcessingOrderMapper processingOrderMapper;
    private final Owner owner;

    ProcessingOrderDispatchPool(OrderMapper orderMapper, ProcessingOrderMapper processingOrderMapper,
                                Owner owner) {
        this.orderMapper = orderMapper;
        this.processingOrderMapper = processingOrderMapper;
        this.owner = owner;
    }

    private LocalDate today() {
        return owner.today();
    }

    private List<OrderItem> loadOrderItems(String orderId, Long tenantId) {
        return owner.loadOrderItems(orderId, tenantId);
    }

    private List<Map<String, Object>> buildSnapshot(List<OrderItem> items, Long tenantId) {
        return owner.buildSnapshot(items, tenantId);
    }

    private StockBatchConsumptionService batchStock() {
        return owner.batchStock();
    }

    private Order resolveOrder(String rawId, Long tenantId) {
        return owner.resolveOrder(rawId, tenantId);
    }

    /**
     * 待派池视图（issue #5169 判据 5 的可查面）。
     *
     * <h2>池的定义（唯一口径）</h2>
     * <b>待付款 + 已确认</b>（{@code orders.status ∈ }{@link ProcessingOrderService#GENERATABLE_ORDER_STATUSES}）且
     * **无活跃加工单**（排除口径与 {@code uk_processing_orders_active} 逐字相同）。
     * 🔴 issue #7634（用户 2026-10-24 裁定「只需要能让未付款的订单也能去生产即可，也要统一走智能派单」）：
     * 待付款单**入池** —— 订单详情页的直派入口已全部收走，派单页成为**唯一**派单面；
     * 作业单是生产计划（不扣库存、不记资金，扣减仍在 {@code confirmPayment}），故未收款也能进生产。
     * 无加工部位的单（配件/赠品行、无加工项）**不进池**：它们本来就不会生成加工单，
     * 进池只会让「池里有单却派不了」变成噪声。
     *
     * <h2>等待时长的口径（**不猜**，照实登记）</h2>
     * {@code waitHours = now − orders.created_at}。系统**没有**记录「支付时刻」（{@code orders}
     * 无 {@code paid_at}/{@code confirmed_at} 列）⇒ 用下单时刻作**上界**口径：它只会把等待算得**更久**、
     * 不会假装刚进池 —— 「不得静默压单」要的是**早**告警，故取保守方向。
     *
     * <h2>加急单**不进池**（issue #5177 判据 3）</h2>
     * {@code orders.is_urgent = true} 的单**不进** {@link ProductionPoolViews.Pool#groups()}
     * （= 不成批候选），而是进 {@link ProductionPoolViews.Pool#urgentLines()}（插队区）——
     * 用户裁定「允许加急的订单直接派，不加急的同批次候选池优先」。
     * ⇒ 看板对加急行的动作是**立刻单派**（{@code /dispatch} + {@code pooled=false}）；
     * 把它勾进 {@code pooled=true} 的批次会被 {@link #assertNoUrgentInPooledBatch} **整批拒绝**。
     *
     * @param maxWaitHoursRaw 滞留上限（小时）；{@code null} ⇒ {@link ProcessingOrderService#DEFAULT_POOL_MAX_WAIT_HOURS}，
     *                        非正数 ⇒ 显式拒绝（见 {@link #maxWaitHours}）
     */
    ProductionPoolViews.Pool pool(Long tenantId, BigDecimal maxWaitHoursRaw) {
        BigDecimal maxWaitHours = maxWaitHours(maxWaitHoursRaw);
        List<Order> poolable = orderMapper.selectList(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId)
                .eq(Order::getDeleted, 0)
                .in(Order::getStatus, GENERATABLE_ORDER_STATUSES)
                .orderByAsc(Order::getCreatedAt)
                .orderByAsc(Order::getId));
        if (poolable == null) {
            poolable = List.of();
        }
        List<String> ids = new ArrayList<>();
        for (Order order : poolable) {
            if (order.getId() != null) {
                ids.add(order.getId());
            }
        }
        Set<String> dispatched = ids.isEmpty() ? Set.of()
                : new LinkedHashSet<>(processingOrderMapper.selectActiveOrderIds(tenantId, ids));

        OffsetDateTime now = OffsetDateTime.now();
        LocalDate today = today();
        // 物料键 → 行；顺序 = 先出现的物料在前（确定性输出，便于看板与快照比对）
        Map<String, List<ProductionPoolViews.PoolLine>> linesByMaterial = new LinkedHashMap<>();
        Map<String, String[]> materialOf = new LinkedHashMap<>();
        List<ProductionPoolViews.PoolWarning> warnings = new ArrayList<>();
        // 池内（非加急）与**加急插队区**分开装：加急单**不进池**（issue #5177 判据 3）
        Set<String> ordersInPool = new LinkedHashSet<>();
        Set<String> urgentOrders = new LinkedHashSet<>();
        // 外发区（issue #7746 后续）：订单级 is_outsourced 标记的单同样**不进池** ⇒ 逐单立即派
        Set<String> outsourcedOrders = new LinkedHashSet<>();
        List<ProductionPoolViews.PoolLine> urgentLines = new ArrayList<>();
        List<ProductionPoolViews.PoolLine> outsourcedLines = new ArrayList<>();
        int lineCount = 0;
        for (Order order : poolable) {
            if (order.getId() == null || dispatched.contains(order.getId())) {
                continue;
            }
            List<OrderItem> items = loadOrderItems(order.getId(), tenantId);
            List<Map<String, Object>> snapshot = buildSnapshot(items, tenantId);
            if (snapshot.isEmpty()) {
                continue;
            }
            Map<String, String> productIdByItemId = new LinkedHashMap<>();
            for (OrderItem item : items) {
                if (item.getId() != null) {
                    productIdByItemId.put(item.getId(), item.getProductId());
                }
            }
            BigDecimal waitHours = hoursBetween(order.getCreatedAt(), now);
            boolean overdue = waitHours.compareTo(maxWaitHours) > 0;
            if (overdue) {
                // 「不得静默压单」= 超上限这件事**必须带着对象说出来**。🔴 issue #6524：对象由
                // `orderNo` **字段**承载（前端在明细表里单独成列），读数由 `waitHours` 字段承载
                // （同表另一列）⇒ 文案**不重复念同屏已有的列**，也不带口语责备尾巴；
                // 只留「阈值 + 该做什么」（阈值来自本次生效的 `maxWaitHours`，不写死）。
                // **加急单同样告警** —— 它更不该被压住。
                warnings.add(new ProductionPoolViews.PoolWarning(order.getId(), order.getOrderNo(),
                        waitHours, String.format("已超过最长等待 %s 小时，请合并派单或单独派单",
                        maxWaitHours.toPlainString())));
            }
            boolean urgent = Boolean.TRUE.equals(order.getIsUrgent());
            boolean outsourced = Boolean.TRUE.equals(order.getIsOutsourced());
            LocalDate requiredDeliveryDate = order.getRequiredDeliveryDate();
            Integer deliveryDaysLeft = deliveryDaysLeft(requiredDeliveryDate, today);
            for (Map<String, Object> row : snapshot) {
                String itemId = str(row.get("itemId"));
                BigDecimal required = StockQuantity.toStockScaleByCeiling(
                        row.get("quantity") instanceof BigDecimal q ? q : null);
                if (itemId == null || required.signum() <= 0) {
                    continue;
                }
                String productId = productIdByItemId.get(itemId);
                String skuCode = snapshotSkuCode(row);
                ProductionPoolViews.PoolLine line = new ProductionPoolViews.PoolLine(
                        order.getId(), order.getOrderNo(), itemId, productId, str(row.get("productName")),
                        skuCode, required, order.getCreatedAt(), waitHours, overdue,
                        urgent, outsourced, requiredDeliveryDate, deliveryDaysLeft, true);
                if (urgent) {
                    // 🔴 加急单**不进池**（用户裁定「允许加急的订单直接派，不加急的同批次候选池优先」）：
                    // 它的去处是插队区（看板上一个动作 = 立刻单派），**不是**成批候选。
                    urgentLines.add(line);
                } else if (outsourced) {
                    // 🔴 外发单同样**不进池**（issue #7746 后续裁定「外单应该和加急单一样」）：
                    // 去处 = 外发区（同样一个动作 = 立刻单派，但**必须**选承接方）。
                    outsourcedLines.add(line);
                } else {
                    String key = ProductionPoolViews.materialKey(productId, skuCode);
                    materialOf.putIfAbsent(key, new String[]{productId, skuCode});
                    linesByMaterial.computeIfAbsent(key, k -> new ArrayList<>()).add(line);
                    lineCount++;
                }
            }
            if (urgent) {
                urgentOrders.add(order.getId());
            } else if (outsourced) {
                outsourcedOrders.add(order.getId());
            } else {
                ordersInPool.add(order.getId());
            }
        }
        // issue #7091：行级库存可满足性（只读）—— 按物料**一次**批量判定后回填三条队列（唯一实现见 StockSatisfiability）。
        StockSatisfiability.fill(batchStock(), tenantId, urgentLines, outsourcedLines,
                linesByMaterial.values());
        // 智能派单排序（判据 5 的唯一落点）：插队区与每个物料组**各自**按同一把键排（见 POOL_LINE_ORDER）
        urgentLines.sort(POOL_LINE_ORDER);
        outsourcedLines.sort(POOL_LINE_ORDER);
        List<ProductionPoolViews.PoolGroup> groups = new ArrayList<>();
        for (Map.Entry<String, List<ProductionPoolViews.PoolLine>> entry : linesByMaterial.entrySet()) {
            String[] material = materialOf.get(entry.getKey());
            Set<String> groupOrders = new LinkedHashSet<>();
            BigDecimal required = BigDecimal.ZERO;
            for (ProductionPoolViews.PoolLine line : entry.getValue()) {
                groupOrders.add(line.orderId());
                required = required.add(line.requiredMeters());
            }
            List<ProductionPoolViews.PoolLine> lines = new ArrayList<>(entry.getValue());
            lines.sort(POOL_LINE_ORDER);
            groups.add(new ProductionPoolViews.PoolGroup(entry.getKey(),
                    materialLabel(lines.get(0)), material[0], material[1],
                    groupOrders.size(), required, List.copyOf(lines)));
        }
        return new ProductionPoolViews.Pool(maxWaitHours, POOLED_DEFAULT_ENABLED, ordersInPool.size(),
                lineCount, warnings.size(), urgentOrders.size(), List.copyOf(warnings),
                List.copyOf(urgentLines), List.copyOf(outsourcedLines), outsourcedOrders.size(),
                List.copyOf(groups));
    }

    /** 滞留上限归一：缺省用 {@link ProcessingOrderService#DEFAULT_POOL_MAX_WAIT_HOURS}；非正数 ⇒ **显式拒绝**（不静默回落）。 */
    static BigDecimal maxWaitHours(BigDecimal raw) {
        if (raw == null) {
            return DEFAULT_POOL_MAX_WAIT_HOURS;
        }
        if (raw.signum() <= 0) {
            throw BusinessException.validationError(
                    "maxWaitHours 必须为正数（实际 " + raw.toPlainString() + "）");
        }
        return raw;
    }

    /**
     * 等待时长（小时，1 位小数）= {@code now − orders.created_at}。
     *
     * <p>取 {@code created_at} 的理由与保守方向见 {@link #pool}；时间倒挂（时钟回拨 / 脏数据）
     * ⇒ 记 0 而不是负数（负的等待时长在读面上无法解释，且会让「超上限」恒为假 = 静默压单）。</p>
     */
    static BigDecimal hoursBetween(OffsetDateTime from, OffsetDateTime to) {
        if (from == null) {
            return BigDecimal.ZERO;
        }
        long minutes = Duration.between(from, to).toMinutes();
        if (minutes < 0) {
            minutes = 0;
        }
        return BigDecimal.valueOf(minutes).divide(BigDecimal.valueOf(60), 1, RoundingMode.HALF_UP);
    }

    /**
     * 物料组的**展示名**（issue #6523）：{@code 商品名 × 颜色/门幅}，**不是**机器键。
     *
     * <p>它是 {@link #materialKey} 的人话孪生兄弟 —— ⚠️ 已定的边界：**不得**退回机器键
     * （那正是本单修掉的缺陷：UUID 被当展示名摆给商家看）。商品名与 SKU 本来就都在
     * {@link ProductionPoolViews.PoolLine} 里（同组各行同料 ⇒ 取任一行的即可）。</p>
     *
     * <p>🔴 组装口径在 {@link com.migao.admin.dto.MaterialLabels}（**唯一一份**，issue #6535）：
     * 省料看板的 {@code SavingMetricViews.SavedGroup.materialLabel} 走的是同一个入口 ——
     * 两个 DTO 各写一份必然漂成两套语义（缺值回退 / 分隔符），而页面上看不出来。</p>
     */
    static String materialLabel(ProductionPoolViews.PoolLine line) {
        return MaterialLabels.materialLabel(line.productName(), line.skuCode());
    }

    /**
     * 到货日**临期度**（天）= 到货日 − 今天；负数 = **已逾期**；{@code null} = **未指定**。
     *
     * <p>服务端算、前端只渲染 —— 「临期」是看板的口径，在浏览器里再算一遍就是第二份口径
     * （一处改了另一处不跟 = 看板与排序对不上，且没有任何东西会变红）。</p>
     */
    static Integer deliveryDaysLeft(LocalDate required, LocalDate today) {
        return required == null ? null : (int) ChronoUnit.DAYS.between(today, required);
    }

    /**
     * 🔴 加急单**不进池**（issue #5177 判据 3）—— 成批（{@code pooled=true}）批次里出现加急单
     * ⇒ **整批显式拒绝**，且**一行都不写**（在任何只读准备与写库之前判完）。
     *
     * <h2>为什么是「拒绝」而不是「静默把加急单剔出去」</h2>
     * 静默剔除 = **静默少派**：商家勾了 3 张单、点了成批，回来 2 张加工单而没有任何提示
     * ⇒ 第 3 张单被压住且无人知道（同族纪律：「不得静默少扣 / 不得静默压单」）。
     * 拒绝带上**订单号**与**可行动处置**（单独派 = 插队；或先取消加急）。
     *
     * <p>查不到的单**不在这里报错**：{@code ORDER_NOT_FOUND} 由逐单路径按既有文案报
     * （本方法只补「加急」这一条新判据，不改既有失败面与失败顺序）。</p>
     */
    void assertNoOutsourcedInPooledBatch(List<String> orderIds, Long tenantId) {
        List<String> outsourced = new ArrayList<>();
        for (String rawId : orderIds) {
            Order order = resolveOrder(rawId, tenantId);
            if (order != null && Boolean.TRUE.equals(order.getIsOutsourced())) {
                outsourced.add(order.getOrderNo() == null ? rawId : order.getOrderNo());
            }
        }
        if (!outsourced.isEmpty()) {
            throw BusinessException.validationError(
                    "外发单不参与合并派单，请单独派：" + String.join("、", outsourced),
                    List.of(),
                    "请把这几个外发单在「外发区」单独派单（记得先选承接方/加工厂），"
                            + "或先取消它们的外发标记再合并派单");
        }
    }

    void assertNoUrgentInPooledBatch(List<String> orderIds, Long tenantId) {
        List<String> urgent = new ArrayList<>();
        for (String rawId : orderIds) {
            Order order = resolveOrder(rawId, tenantId);
            if (order != null && Boolean.TRUE.equals(order.getIsUrgent())) {
                urgent.add(order.getOrderNo() == null ? rawId : order.getOrderNo());
            }
        }
        if (!urgent.isEmpty()) {
            throw BusinessException.validationError(
                    "加急单不参与合并派单，请单独派：" + String.join("、", urgent),
                    List.of(),
                    "请把这几个加急单单独派单（立即派 = 单订单派单），"
                            + "或先取消它们的加急标记再合并派单");
        }
    }
}
