package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.OrderCreateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.Product;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.time.BusinessClock;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;

/**
 * 订单<b>共享部件族</b>（issue #8681，P2-1e 第九批）：<b>建单 / 改单 / Agent / 后续任何写单路径</b>
 * 共用的那一份「明细装配 · 取价 · 总额 · 库存前置 · 单号 · 定价留痕」的唯一实现点。
 *
 * <h2>为什么要有这个类（不是「又一个 service」）</h2>
 * <p>这批代码此前住在 {@link OrderService} 里，靠「把门面实例当第三参传进去」被
 * {@link OrderCreationService} 与 {@link OrderEntityWriteService} 复用。那条口径的<b>代价</b>不是行数，
 * 而是<b>依赖方向</b>：两个服务的入口签名里各挂着一个<b>门面</b>，于是门面永远删不掉
 * —— 谁想把它收成 &lt; 500 行，都得先回答「第三参换成谁」。本类的存在就是这个回答：
 * <b>第三参 = 共享部件实例</b>（不是门面 ⇒ 门面不再随调用链传播）。</p>
 *
 * <h2>边界（逐条判据见 issue #8681；这里记结论与理由）</h2>
 * <ul>
 *   <li><b>进来的</b>：被 <b>≥2 个服务</b>调用的那一族 —— 明细金额闸门 / 逐行取价 /
 *       总额 / 加工费组合同步 / 明细落库 / 安装位置归一 / 库存前置 / 两个库存校验入口；
 *       以及它们的<b>私有步骤</b>（{@code applyRollAllocation} 一族 / {@code applyPricingTrace} /
 *       {@code resolveItemSubtotal}）。私有步骤必须跟着走：把它们留在门面就得在两个类之间架一层回调，
 *       那是<b>新缝</b>，比搬家贵。</li>
 *   <li><b>只被建单族消费、但仍收在这里</b>：{@code generateOrderNo} / {@code recordPriceOverrideAudit}
 *       —— 按「≥2 个服务」判据它们<b>不算</b>共享部件。收在这里是**有意的取舍**：为它们给
 *       {@link OrderCreationService} 单加两个构造依赖（业务时钟 / 审计）的收益为负。
 *       ⇒ <b>具名登记</b>：它俩是「建单族专用、暂寄共享部件」；若建单族日后自持，应当迁走。</li>
 *   <li><b>不收</b>：{@code hasProcessingItems} / {@code needsWork}（订单域<b>公共 API</b>，
 *       生产待办与发货守卫逐字引用）、状态常量表 / 列表时间窗 / 状态筛选（静态契约面）、
 *       {@code OrderShipmentOutcome}（公开类型名）、{@code backfillSkuIdentity}（既有单测按
 *       {@code OrderService.xxx} 引用的静态入口）。</li>
 * </ul>
 *
 * <h2>唯一实现点纪律（元守卫）</h2>
 * <p>本类替代的是「同一段逻辑存在第二份」——那条路的症状是<b>静默分叉</b>
 * （改单漏挂加工费构成 / 建单与改单两个总额），没有任何既有断言会因此变红。
 * ⇒ 判据 = {@code OrderSharedPartsSingleImplementationTest}：任何服务<b>自己实现</b>
 * 本族的等价逻辑（明细装配 / 取价 / 总额 / 库存前置 / 整卷分配的落列与回落）⇒ 红并具名。</p>
 */
@Slf4j
@Service
public class OrderSharedParts {

    /**
     * 订单号序列号（线程安全）—— 随 {@code generateOrderNo} 从门面搬来（issue #8681，P2-1e 第九批），
     * 是「9 位后缀 = 5 位随机数 + 4 位原子序列」里的原子序列本体。
     */
    private static final AtomicInteger ORDER_SEQ = new AtomicInteger(0);

    /** 明细落库（{@code order_items}）的唯一写面。 */
    private final OrderItemMapper orderItemMapper;
    /** 行要素归一与加工费构成的 JSON 载体归一（{@code processing_info}）。 */
    private final ObjectMapper objectMapper;
    /** 整卷分配的商品查表（{@code products.roll_length_m} / {@code selling_methods}）。 */
    private final ProductMapper productMapper;
    /** 加工费**取价点**（issue #4406）：加工费只有这一个算法。 */
    private final ProcessingFeeCalculator processingFeeCalculator;
    /** 加工费组合定价**写面**（issue #4872）：建单/改单的「自建价目」唯一通路。 */
    private final ProcessingFeeCombinationCommandService processingFeeCombinationCommandService;
    /** 业务时钟：订单号日期段的唯一来源（不取系统时钟，单测可注入）。 */
    private final BusinessClock businessClock;
    /** 定价改写审计的操作人解析（issue #7375 段 2）。 */
    private final UserService userService;
    /** 定价改写审计的落账点（{@code audit_logs}）。 */
    private final AuditLogService auditLogService;
    /** 库存前置校验的唯一实现点（issue #8191，P2-1c）—— 本类只做参数搬运。 */
    private final OrderStockService orderStockService;
    /**
     * 批次消耗台账（V116 / issue #5145）：{@code cancelOrder}「加工单自动作废」那一路的批次回补。
     *
     * <p>它随第三参一起落到本类：{@link OrderLifecycleService} 的第三参换成共享部件之后，
     * 它对该参数的<b>唯一</b>用法就是本访问器（原话：{@code orderService.batchStock()}）。</p>
     */
    private final StockBatchConsumptionService stockBatchConsumptionService;

    public OrderSharedParts(OrderItemMapper orderItemMapper,
                            ObjectMapper objectMapper,
                            ProductMapper productMapper,
                            ProcessingFeeCalculator processingFeeCalculator,
                            ProcessingFeeCombinationCommandService processingFeeCombinationCommandService,
                            BusinessClock businessClock,
                            UserService userService,
                            AuditLogService auditLogService,
                            OrderStockService orderStockService,
                            StockBatchConsumptionService stockBatchConsumptionService) {
        this.orderItemMapper = orderItemMapper;
        this.objectMapper = objectMapper;
        this.productMapper = productMapper;
        this.processingFeeCalculator = processingFeeCalculator;
        this.processingFeeCombinationCommandService = processingFeeCombinationCommandService;
        this.businessClock = businessClock;
        this.userService = userService;
        this.auditLogService = auditLogService;
        this.orderStockService = orderStockService;
        this.stockBatchConsumptionService = stockBatchConsumptionService;
    }

    // ══════════════════ 待付款订单内容编辑（issue #5842）与共用写面部件 ══════════════════

    /**
     * 明细金额闸门（数量 ≥ 1、单价 > 0）—— 建单与改单**同一份**（issue #5842 抽出）。
     *
     * <p>为什么必须在 Service 层显式判定（而不是只靠 DTO 注解）：① Agent 路径是**手工 new** DTO
     * 再调用（程序化构造的 Bean 不经过 Bean Validation）；② 数量直接驱动库存/销量与金额
     * ⇒ 判在唯一共享入口才无死角。</p>
     */
    void assertItemAmountsValid(List<OrderCreateRequest.OrderItemRequest> items) {
        for (int i = 0; i < items.size(); i++) {
            OrderCreateRequest.OrderItemRequest itemRequest = items.get(i);
            if (itemRequest.getQuantity() == null
                    || itemRequest.getQuantity().compareTo(BigDecimal.ONE) < 0) {
                throw BusinessException.validationError(
                        String.format("商品明细第 %d 项的数量不能小于 1", i + 1));
            }
            if (itemRequest.getUnitPrice() == null
                    || itemRequest.getUnitPrice().compareTo(BigDecimal.ZERO) <= 0) {
                throw BusinessException.validationError(
                        String.format("商品明细第 %d 项的单价必须大于 0", i + 1));
            }
            // 金额精度准入（issue #6228）：`order_items.unit_price` 是 NUMERIC(·,2)，
            // 超 2 位有效小数会被 PG **静默四舍五入**（接口 200、库内值与请求值不等）。
            // 判在本方法 = 建单/改单**唯一共享入口**，且在 `persistOrderItems` 任何写之前。
            itemRequest.setUnitPrice(MoneyScale.requireTwoDecimalsOrNull(
                    itemRequest.getUnitPrice(), String.format("商品明细第 %d 项的单价", i + 1)));
        }
    }

    /**
     * 逐行加工费取价（**唯一取价点**，建单与改单共用；issue #4406 / #5842）。
     *
     * <p>未定价 / 缺米数 ⇒ **不静默**：金额照样成立（该半按 0 计），但日志留下可排查证据。</p>
     */
    List<ProcessingFeeCalculator.Fee> priceItems(List<OrderCreateRequest.OrderItemRequest> items,
                                                         Long tenantId) {
        List<ProcessingFeeCalculator.Fee> itemFees = processingFeeCalculator.feesFor(
                items.stream()
                        .map(OrderCreateRequest.OrderItemRequest::getProcessingInfo)
                        .collect(Collectors.toList()),
                tenantId);
        for (int i = 0; i < items.size(); i++) {
            if (ProcessingFeeCalculator.FEE_SOURCE_UNPRICED.equals(itemFees.get(i).feeSource())) {
                log.warn("加工费未定价（本行按 0 计）: tenantId={}, itemIndex={}, composition={}, hint={}",
                        tenantId, i, itemFees.get(i).compositionKey(), itemFees.get(i).hint());
            }
        }
        return itemFees;
    }

    /**
     * 订单总额 = Σ(单价 × 数量) + Σ 行加工费（**服务端独立计算**，不信客户端任何金额字段）。
     *
     * <p>与 issue #4406 的口径一致：行加工费 = {@code Fee#lineAmount()}
     * （组合那半 + Σ 特殊选项 + 拼色加价）—— 不另拼第二份算式。</p>
     */
    BigDecimal computeItemsTotal(List<OrderCreateRequest.OrderItemRequest> items,
                                         List<ProcessingFeeCalculator.Fee> itemFees) {
        BigDecimal total = BigDecimal.ZERO;
        for (int i = 0; i < items.size(); i++) {
            OrderCreateRequest.OrderItemRequest itemRequest = items.get(i);
            BigDecimal itemAmount = BigDecimal.ZERO;
            if (itemRequest.getUnitPrice() != null && itemRequest.getQuantity() != null) {
                itemAmount = itemRequest.getUnitPrice().multiply(itemRequest.getQuantity());
            }
            total = total.add(itemAmount).add(itemFees.get(i).lineAmount());
        }
        return total;
    }

    /**
     * 建单同步回加工费组合配置（issue #4872）：只对 {@code fee_source=manual} 的行按
     * {@code compositionKey} **同源口径** upsert 组合价 + 追加版本台账。无 manual 行 ⇒ **零调用**。
     *
     * <p>改单（#5842）同样走它：商家在未定价行上就地改价这件事，与「这次是新单还是改单」无关；
     * 两条路各接一次就会分叉成「改单改的价不进组合台账」。</p>
     *
     * <p>🔴 #7642（用户 2026-10-24 裁定「新增订单中的加工费组合需要允许修改」= **只改本单单价**）：
     * 组合**已配置**（{@link ProcessingFeeCalculator.Fee#configuredUnitPrice()} 非 null）⇒ 价目里
     * 已经有这一条，本单改价**不**回写（回写会把这一单的谈定价变成租户共享价，之后所有同组合的新单
     * 都按它算钱）。未配置 ⇒ 仍走既有 upsert —— 那是「自建价目」的唯一通路。</p>
     */
    void syncProcessingFeeCombinations(List<ProcessingFeeCalculator.Fee> itemFees, Long tenantId) {
        for (ProcessingFeeCalculator.Fee fee : itemFees) {
            if (!ProcessingFeeCalculator.FEE_SOURCE_MANUAL.equals(fee.feeSource())) {
                continue;
            }
            // #7642：本单改价覆盖的是**已配置**的组合 ⇒ 价目不动（见方法注释）
            if (fee.configuredUnitPrice() != null) {
                continue;
            }
            // #7658：**0 元是本单语义**（免加工费）⇒ 绝不写进租户共享价目
            // （写进去 = 之后所有同组合的新单都按 0 元收钱；一个免费单把整条组合价清零）。
            if (fee.unitPrice() == null || fee.unitPrice().signum() <= 0) {
                continue;
            }
            processingFeeCombinationCommandService.upsertFromOrderOverride(
                    fee.compositionKey(), fee.items(), fee.unitPrice(), tenantId);
        }
    }

    /**
     * 明细落库（商品金额 + 加工项 + 工艺规格列 + 整卷分配）—— 建单与改单**同一份**（issue #5842 抽出）。
     *
     * <p>抽出的理由不是"好看"：改单若自己再写一遍这个循环，加工费 detail 的挂载 / V63 行要素物化 /
     * V111 整卷分配这三件事都会出现**第二份**，而它们分叉的方向是「改单后加工费构成丢失」
     * 「改单后整卷分配不再重算」——都是静默的（没有任何东西会变红）。</p>
     */
    /**
     * 订单明细落库（建单 / 内容更新 / Agent 三条路径的**唯一共享入口**）。
     *
     * <h3>安装信息（issue #7856）：写侧**单点扇出**</h3>
     * <p>订单级语义的「安装小区」（{@code processingInfo.installCommunity}）在这里写进**每一行**：
     * 加工单快照与订单明细都是行数组、没有订单级顶层对象，而纸面（水洗唛 / 发货标签 / 入库标签）
     * 逐行打印 ⇒ 订单级事实只能逐行落（同 {@code isUrgent} 的既有范式）。调用方只交一个订单级字符串，
     * **不前端逐行写**（那是第二份口径）；件级「安装位置」则直接放在该行的
     * {@code processingInfo.installRoom}（与 {@code curtainType} / {@code remark} 同一载体）。</p>
     * <p>为什么落 JSONB 而不是给 {@code orders} / {@code order_items} 加列（用户 2026-10-26 当场裁定
     * 「不能作为订单基础字段吧？」）：它只上纸、不参与算料 / 计价 / 派工 / 库存 / 检索；
     * {@code order_items.processing_info} 是**已登记**的 JSONB 扩展点 ⇒ **数据库零迁移**
     * （{@code orders} 仍 24 列、{@code order_items} 仍 32 列）。
     * 缺值不落键（与 {@code CRAFT_SPEC_SNAPSHOT_KEYS} 的白名单键族一致）。</p>
     *
     * @param installCommunity 已归一 + 准入的安装小区（{@code null} = 未填 ⇒ 不落键）
     */
    void persistOrderItems(Order order, List<OrderCreateRequest.OrderItemRequest> items,
                                   List<ProcessingFeeCalculator.Fee> itemFees, Long tenantId,
                                   List<OrderPricingService.LinePricing> linePricings,
                                   String installCommunity) {
        for (int i = 0; i < items.size(); i++) {
            OrderCreateRequest.OrderItemRequest itemRequest = items.get(i);
            // ── 加工费可审计构成落库（issue #4406）──
            // 为什么落 `processing_info.processingFeeDetail` 而不是新列：加工费是**行级一个数 +
            // 构成**，构成（组合/命中规则/单价/来源/米数/来源/三态）与 processing_info 同生命周期
            // （R13 快照优先：改组合价后**已生成订单一字不变** ⇒ 读面读存量、不重算）。
            // JSON **字符串**形态先归一化成 Map 再挂（否则 `put` 无处可落、detail 静默丢失）；
            // 且**另起一份可变副本**（`Map.of` / `List.of` 一类不可变容器 `put` 会抛
            // UnsupportedOperationException ⇒ 下单直接 500；同时也不该就地改调用方传进来的对象）。
            Map<String, Object> normalizedInfo = OrderLineCraftFields.normalize(
                    itemRequest.getProcessingInfo(), objectMapper);
            // 安装信息（issue #7856）两键在**同一处**落：订单级 `installCommunity` 扇到每行，
            // 件级 `installRoom` 落本行（显式 API 字段 > 调用方自己塞进 processingInfo 的同名键）。
            String installRoom = itemRequest.getInstallRoom();
            if (normalizedInfo != null || installCommunity != null || installRoom != null) {
                Map<String, Object> annotated = normalizedInfo == null
                        ? new LinkedHashMap<>()
                        : new LinkedHashMap<>(normalizedInfo);
                if (normalizedInfo != null) {
                    // 加工费可审计构成只在原本就有 processing_info 的行上挂（与改前逐字同语义）
                    ProcessingFeeCalculator.attach(annotated, itemFees.get(i));
                }
                if (installCommunity != null) {
                    annotated.put(OrderInstallInfo.KEY_INSTALL_COMMUNITY, installCommunity);
                }
                if (installRoom != null) {
                    annotated.put(OrderInstallInfo.KEY_INSTALL_ROOM, installRoom);
                }
                itemRequest.setProcessingInfo(annotated);
                normalizedInfo = annotated;
            }
            OrderItem item = new OrderItem();
            item.setTenantId(tenantId);
            item.setOrderId(order.getId());
            item.setProductId(itemRequest.getProductId());
            // 定价依据落列（V180，issue #7375 段 2）：SKU + 命中层级 + 被改写前的客户端价
            applyPricingTrace(item, linePricings, i);
            item.setProductName(itemRequest.getProductName());
            item.setQuantity(itemRequest.getQuantity());
            item.setUnitPrice(itemRequest.getUnitPrice());
            item.setWidth(itemRequest.getWidth());
            item.setHeight(itemRequest.getHeight());
            item.setProcessingInfo(itemRequest.getProcessingInfo());
            // 下单行要素落列（V63，issue #4362，S1）：两个采集端（C 端元元澄清清单 / B 端黄金策
            // order_create）写入的 processing_info 顶层工艺规格键在此**物化**到 order_items 的列上。
            // 判在本方法（表单 / Agent / 程序化三条路径的**唯一共享入口**）才无死角；
            // 全部可空、不设必填校验（用户裁定「部位不是必填的」）⇒ 缺键就是缺。
            OrderLineCraftFields.materialize(normalizedInfo, item);
            // ── 售卖方式偏好 + 「优先整卷发货」分配落列（V111，用户裁定 2026-09-21）──
            // 三列语义见 OrderItem 的字段 javadoc；判在**本方法**（表单 / Agent / 程序化三条路径
            // 的唯一共享入口）才无死角 —— 与上面 V63 的行要素物化同一理由。
            applyRollAllocation(itemRequest, item);
            item.setSubtotal(resolveItemSubtotal(itemRequest));
            orderItemMapper.insert(item);
        }
    }

    /**
     * 定价改写审计（issue #7375 段 2）：`action = price_server_override`，details 带逐行
     * 「客户端价 → 服务端价 / 命中层级」。
     *
     * <p>只记被改写的行：审计是**证据**，不是流水账 —— 把没改的行也写进去会让真差异淹在噪音里。</p>
     */
    void recordPriceOverrideAudit(Order order, List<OrderPricingService.LinePricing> linePricings) {
        if (linePricings == null || linePricings.isEmpty()) {
            return;
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        for (int i = 0; i < linePricings.size(); i++) {
            OrderPricingService.LinePricing pricing = linePricings.get(i);
            if (pricing == null || pricing.clientPrice() == null) {
                continue;   // 未被改写
            }
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("line", i + 1);
            row.put("sku_id", pricing.skuId());
            row.put("sku_code", pricing.skuCode());
            row.put("client_price", pricing.clientPrice().toPlainString());
            row.put("price_source", pricing.priceSource());
            rows.add(row);
        }
        if (rows.isEmpty()) {
            return;
        }
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("order_no", order.getOrderNo());
        details.put("overridden_lines", rows);
        UserService.CurrentOperator operator = userService.resolveCurrentOperator();
        auditLogService.recordLog(order.getTenantId(),
                operator != null ? operator.userId() : null,
                operator != null ? operator.displayName() : null,
                "price_server_override", "order", null,
                order.getId(), order.getOrderNo(), details, null, null);
    }

    /**
     * 定价依据落列（issue #7375 段 2）：SKU + 命中层级 + **被改写前的客户端价**。
     *
     * <p>只写有依据的那几列：没有 SKU/没参与定价的行保持 null（缺就是缺，不猜、不填 0）。
     * `priceClientUnitPrice` 只在**真被改写**时写 —— 否则「一样的价」会被记成「改过」。</p>
     */
    private void applyPricingTrace(OrderItem item, List<OrderPricingService.LinePricing> linePricings, int index) {
        if (linePricings == null || index >= linePricings.size()) {
            return;
        }
        OrderPricingService.LinePricing pricing = linePricings.get(index);
        if (pricing == null) {
            return;
        }
        item.setSkuId(pricing.skuId());
        item.setSkuCode(pricing.skuCode());
        item.setPriceSource(pricing.priceSource());
        item.setPriceClientUnitPrice(pricing.clientPrice());
    }





    /**
     * 逐行归一 + 准入件级「安装位置」（issue #7856）：去空白 / 折叠内部换行 / ≤12 字，超长 422。
     *
     * <p>归一结果**写回请求明细**（{@code itemRequest.setInstallRoom}）⇒ {@code persistOrderItems}
     * 只搬已归一的值，不必再判一次；判在写库之前，超长不会留下半张单。</p>
     */
    void normalizeInstallRooms(List<OrderCreateRequest.OrderItemRequest> items) {
        if (items == null) {
            return;
        }
        for (OrderCreateRequest.OrderItemRequest item : items) {
            if (item != null) {
                item.setInstallRoom(OrderInstallInfo.normalizeRoom(item.getInstallRoom()));
            }
        }
    }




    /**
     * 生成订单号
     * 格式: 17位纯数字 = yyyyMMdd(8) + 9位随机数，简洁唯一
     */
    String generateOrderNo() {
        String datePart = businessClock.today().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
        // 9 位后缀 = 5 位随机数 + 4 位原子序列。
        // 原实现取 nanoTime 尾 9 位：每秒回绕一次、跨实例易碰撞。
        // 改用随机 + 原子计数器，降低碰撞概率并启用原先闲置的 ORDER_SEQ。
        int randomPart = ThreadLocalRandom.current().nextInt(100_000);   // 0..99999
        int seqPart = ORDER_SEQ.incrementAndGet() % 10_000;             // 0..9999，防随机碰撞
        return String.format("%s%05d%04d", datePart, randomPart, seqPart);
    }

    /**
     * 售卖方式偏好校验 + 「优先整卷发货」分配落列（V111，用户裁定 2026-09-21）。
     *
     * <p><b>为什么分配在服务端算</b>：整卷数是 {@code quantity} 与货号卷长的函数，只能有一个
     * 权威实现 —— 若允许调用方各算一套，「同一张单两个整卷数」无法对账。</p>
     *
     * <p>🔄 <b>2026-10-01（issue #5846）有意改判：<u>显式 &gt; 派生 + 缺的那半回落</u></b>。
     * 用户裁定 A（原话：「订单中售卖整卷布料时，应该有卷数和实际米数两字段」）：
     * 订单行可显式给出 {@code rollCount} / {@code rollLengthM}，<b>缺的那一半回落</b> ——
     * {@code effectiveLength = 显式 rollLengthM ?? 商品 roll_length_m}；
     * {@code rollCount = 显式 rollCount ?? floor(quantity / effectiveLength)}。
     * 用户同日<b>二次裁定：取消「成对」契约</b>（只给一个也是合法输入，缺的那半走回落）。</p>
     *
     * <p>🔴 <b>不变式（改判后仍一字不动）</b>：一次分配里<b>同一个字段只有一个权威来源</b>
     * （显式 XOR 派生）—— 不允许「同一单两个整卷数」。回落点<b>只有</b>
     * {@link ProductRollAllocation#resolve} 一处（本方法是它唯一的调用点，见类级元守卫
     * {@code OrderRollAllocationAuthorityTest}）。</p>
     *
     * <p><b>分配闸门 = 货号有没有配卷长，与售卖方式无关</b>（用户原话的例子就是按米买布）：
     * 「客户买 100 米布，一卷=60 米 ⇒ 发 1 整卷 60 + 散剪 40 米」里顾客**没有**说「我要整卷」。
     * ⇒ 把闸门写成「只有明说整卷才算」会让用户裁定举的例子在新单路径上**根本不生效**
     * （独立对抗式复核实测抓到）。「优先整卷发货」是**发货方式**偏好，不是「整卷售卖单」专属。
     * 显式分支同理：它**不改变**闸门（用户显式给了就是要，也不需要先声明售卖方式）。</p>
     *
     * <p><b>三条不猜的红线</b>：</p>
     * <ol>
     *   <li>未指定售卖方式 ⇒ 该列保持 NULL（不默认整卷、也不默认散剪）
     *       —— 但它**不阻止**分配（见上）；</li>
     *   <li>货号未配卷长（{@code products.roll_length_m} 为空/非正）<b>且用户没给卷长</b>、<b>也没给卷数</b> ⇒
     *       {@code rollCount} / {@code rollLengthM} 保持 NULL，<b>不落 0</b>
     *       —— 「不知道」不许伪装成「0 整卷」（见 {@link ProductRollAllocation}）；
     *       🔻 <b>例外（新合法态）</b>：显式给了卷数而卷长两边都没有 ⇒ {@code rollCount = 显式值}、
     *       {@code rollLengthM = NULL}（「客户要 N 卷」是真实意图，不是未分配）；</li>
     *   <li>货号不存在（历史/外部商品）⇒ 同上（不因此拒绝整单），但**显式给的值照落**
     *       —— 显式值不依赖商品查表（见 {@link #parseExplicitRollCount}）。</li>
     * </ol>
     *
     * <p><b>越界售卖方式必须显式拒绝</b>：该货号 {@code products.selling_methods} 不支持顾客
     * 要的那一档时抛 422（可行动文案）—— 静默落库会让仓库照一个本店不提供的售卖方式发货。</p>
     *
     * <p><b>取值来源有两处，列优先</b>：① 请求体行字段 {@code sellingMethod}；
     * ② 回落 {@code processingInfo.sellingMethod} —— 那是 ai-agent（{@code order_create}）
     * 一直以来的真实写入位置（该键同时被加工单快照消费，不能挪），所以**必须**认它，
     * 否则「agent 明确说了要整卷」这条链路上分配恒为空。</p>
     */
    private void applyRollAllocation(OrderCreateRequest.OrderItemRequest itemRequest, OrderItem item) {
        // ⓪ 显式值只做**边界**校验（不再要求「成对」—— 用户 2026-10-01 裁定取消成对契约）
        Integer explicitRollCount = parseExplicitRollCount(itemRequest);
        assertExplicitRollLengthUsable(itemRequest.getRollLengthM());

        // 商品查表：`productId` 缺 ⇒ 不查（也无售卖方式口径）；查不到 ⇒ 视为「没有货号卷长可回落」
        Product product = itemRequest.getProductId() == null
                ? null
                : productMapper.selectById(itemRequest.getProductId());

        // ① 售卖方式偏好：未指定 ⇒ 该列保持 NULL（不默认整卷、也不默认散剪）
        //    ⚠️ 只在**有 productId** 时处理（「没有商品 ⇒ 既无售卖方式口径也无卷长口径」的旧口径不变）；
        //    商品存在与否都照落列，只是「支持性校验」需要商品（见 `assertSellingMethodSupported` 的调用条件）。
        if (itemRequest.getProductId() != null) {
            String sellingMethod = SkuNotation.normalizeSellingMethod(itemRequest.getSellingMethod());
            if (sellingMethod == null) {
                sellingMethod = SkuNotation.normalizeSellingMethod(
                        readProcessingInfoSellingMethod(itemRequest.getProcessingInfo()));
            }
            if (sellingMethod != null) {
                item.setSellingMethod(sellingMethod);
                if (product != null) {
                    assertSellingMethodSupported(itemRequest, product, sellingMethod);
                }
            }
        }

        // ② 一次分配的**唯一权威来源**：显式优先 + 缺的那半**回落**；回落点唯一 =
        //    `ProductRollAllocation.resolve`（本方法是它唯一的调用点，见类级元守卫）。
        //    ⚠️ 回落**不到**（卷长两边都没有 且 没有显式卷数）⇒ 不写分配（两列保持 NULL，不落 0、不猜）。
        //    分配闸门仍**只看卷长**（不看售卖方式）：用户裁定原话「客户买 100 米布，一卷=60 米 ⇒
        //    发 1 整卷 60 + 散剪 40 米」里顾客**没有**说「我要整卷」—— 把闸门写成「只有明说整卷才算」
        //    会让该例子在新单路径上**根本不生效**（独立对抗式复核实测抓到）。
        ProductRollAllocation.Allocation allocation = ProductRollAllocation.resolve(
                explicitRollCount,
                itemRequest.getRollLengthM(),
                itemRequest.getQuantity(),
                product == null ? null : product.getRollLengthM());
        if (!allocation.allocated()) {
            if (itemRequest.getProductId() != null && product == null) {
                log.warn("applyRollAllocation: 商品不存在，无货号卷长可回落（不猜卷长）, productId={}, orderId={}",
                        itemRequest.getProductId(), item.getOrderId());
            } else {
                log.info("applyRollAllocation: 卷长未知（货号未配且未显式给）且未显式给卷数 ⇒ 不写分配, productId={}, orderId={}",
                        itemRequest.getProductId(), item.getOrderId());
            }
            return;
        }
        item.setRollCount(allocation.rollCount());
        item.setRollLengthM(allocation.rollLengthM());
    }

    /**
     * 解析<b>显式</b>卷数（issue #5846）—— 返回卷数；{@code null} = 客户端<b>没给</b>。
     *
     * <p><b>用户 2026-10-01 裁定：取消「成对」契约</b> —— 只给卷数、只给每卷米数、两个都给，
     * 三种都是合法输入；缺的那一半由
     * {@link ProductRollAllocation#resolve(Integer, BigDecimal, BigDecimal, BigDecimal)} <b>回落</b>
     * （显式 &gt; 商品；回落不到 ⇒ 保持 NULL，不猜）。所以本方法**不再**对「成对」做任何校验。</p>
     *
     * <p><b>保留下来的只有边界（一条都不许放宽，每条都有断言）</b>：</p>
     * <ul>
     *   <li>卷数 &lt; 0 ⇒ 422（不落负值、不静默取整）；</li>
     *   <li>卷数非整数 ⇒ 422 —— 🔴 Jackson 默认 {@code ACCEPT_FLOAT_AS_INT=true}，请求 DTO 若把
     *       该字段声明成 {@code Integer}，{@code 2.5} 会被<b>静默截断成 2 卷</b>；
     *       现在原样落到这里由 {@code intValueExact()} 拒绝。</li>
     * </ul>
     *
     * @return 卷数（含合法的 {@code 0}——「全散剪」是真实结论）；未显式给 ⇒ {@code null}
     */
    private Integer parseExplicitRollCount(OrderCreateRequest.OrderItemRequest itemRequest) {
        BigDecimal rolls = itemRequest.getRollCount();
        if (rolls == null) {
            return null; // 没给卷数 ⇒ 由 resolve 派生（与改判前逐字节相同）
        }
        if (rolls.signum() < 0) {
            throw BusinessException.validationError(
                    "卷数不能为负数（收到 " + rolls.toPlainString() + "）");
        }
        try {
            return rolls.intValueExact();
        } catch (ArithmeticException notAnInt) {
            // 区分「非整数」与「超出 int 范围」——两者都是显式拒绝，但文案要能行动
            boolean integral = rolls.stripTrailingZeros().scale() <= 0;
            throw BusinessException.validationError(integral
                    ? "卷数超出可取值范围（收到 " + rolls.toPlainString() + "）"
                    : "卷数必须是整数（收到 " + rolls.toPlainString() + "）—— 系统不会替你取整，请确认后重填。");
        }
    }

    /**
     * 显式「每卷米数」的边界（issue #5846）：给了就必须 &gt; 0。
     *
     * <p>{@code null} = 没给（合法 —— 走回落）；{@code 0} / 负值不是「没配」而是错的输入 ⇒ 422。
     * DTO 上也有 {@code @DecimalMin(inclusive = false)}（控制器 {@code @Valid} ⇒ 400），
     * 这里再兜一道：**服务层被直接调用时也不许落一个荒谬的卷长**。</p>
     */
    private void assertExplicitRollLengthUsable(BigDecimal explicitRollLengthM) {
        if (explicitRollLengthM != null && explicitRollLengthM.signum() <= 0) {
            throw BusinessException.validationError(
                    "每卷米数必须大于 0（收到 " + explicitRollLengthM.toPlainString() + "）");
        }
    }

    /**
     * 从 {@code processingInfo} 里读售卖方式偏好（ai-agent 的真实写入位置）。
     *
     * <p>{@code processingInfo} 既可能是 Map（服务端已归一化），也可能是 JSON 字符串
     * （历史/程序化调用方直传）—— 两种形态都要认，否则 agent 路径静默读不到。</p>
     *
     * @return 原始字符串（未归一化）；无该键或形态不可解析 ⇒ {@code null}
     */
    @SuppressWarnings("unchecked")
    private String readProcessingInfoSellingMethod(Object processingInfo) {
        Object raw = processingInfo;
        if (raw instanceof String text && !text.isBlank()) {
            try {
                raw = objectMapper.readValue(text, Map.class);
            } catch (Exception e) {
                log.warn("applyRollAllocation: processingInfo 是字符串但不是合法 JSON，读不到售卖方式偏好: {}",
                        e.getMessage());
                return null;
            }
        }
        if (!(raw instanceof Map)) {
            return null;
        }
        Object value = ((Map<String, Object>) raw).get("sellingMethod");
        return value == null ? null : value.toString();
    }

    /** 该货号是否支持这个售卖方式（{@code products.selling_methods} 是权威口径）。 */
    private void assertSellingMethodSupported(OrderCreateRequest.OrderItemRequest itemRequest,                                              Product product, String sellingMethod) {
        List<String> supported = product.getSellingMethods();
        if (supported == null || supported.isEmpty()) {
            return; // 未配置 ⇒ 不误禁（存量商品可能没有该列的值）
        }
        boolean ok = supported.stream()
                .anyMatch(m -> sellingMethod.equals(SkuNotation.normalizeSellingMethod(m)));
        if (!ok) {
            throw BusinessException.validationError(String.format(
                    "商品「%s」不支持售卖方式「%s」（该货号支持：%s）。"
                            + "请改用受支持的售卖方式，或先让商家在商品上配置该售卖方式。",
                    itemRequest.getProductName() != null ? itemRequest.getProductName()
                            : itemRequest.getProductId(),
                    sellingMethod,
                    String.join(" / ", supported)));
        }
    }

    /**
     * 计算/解析订单明细小计：优先使用请求中的 subtotal，若为 null 则回退 unitPrice * quantity。
     * 避免前端未传 subtotal 时 totalAmount 被记录为 0 的问题。
     */
    private BigDecimal resolveItemSubtotal(OrderCreateRequest.OrderItemRequest itemRequest) {
        if (itemRequest.getSubtotal() != null) {
            return itemRequest.getSubtotal();
        }
        if (itemRequest.getUnitPrice() != null && itemRequest.getQuantity() != null) {
            return itemRequest.getUnitPrice().multiply(itemRequest.getQuantity());
        }
        return BigDecimal.ZERO;
    }

    /**
     * validateStockSufficientForRequest（issue #8191，P2-1c）：实现点已搬到 {@link StockService}，本方法只留门面委托。
     */
    void validateStockSufficientForRequest(OrderCreateRequest request, String actionLabel) {
        orderStockService.validateStockSufficientForRequest(request, actionLabel);
    }

    /**
     * validateStockSufficientForItems（issue #8191，P2-1c）：实现点已搬到 {@link StockService}，本方法只留门面委托。
     */
    void validateStockSufficientForItems(List<OrderItem> items, String actionLabel) {
        orderStockService.validateStockSufficientForItems(items, actionLabel);
    }

    /**
     * 批次消耗台账（V116 / issue #5145 阶段 1）—— 装配不上就**显式抛错**，绝不静默跳过回补
     * （静默跳过 = 加工单作废了、批次余量还是扣着，而没有任何东西会变红）。
     *
     * <p>issue #8191（P2-1d）：{@code cancelOrder} 搬到 {@link OrderLifecycleService} 后**经门面**
     * 调用本访问器（判据 `OrderRollAllocationAuthorityTest` 同族的「门面持有唯一实现」口径）——
     * 因此放宽为<b>包内可见</b>，实现与「装配不上即抛」的守卫**一字未改**。</p>
     */
    StockBatchConsumptionService batchStock() {
        if (stockBatchConsumptionService == null) {
            throw new IllegalStateException(
                    "StockBatchConsumptionService 未装配 —— 加工单作废的批次回补不能静默跳过（issue #5145）");
        }
        return stockBatchConsumptionService;
    }
}
