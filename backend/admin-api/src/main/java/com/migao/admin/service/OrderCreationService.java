package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.OrderCreateRequest;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.dto.agent.AgentOrderCreateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 订单<b>创建族</b>服务（issue #8191，P2-1b）。
 *
 * <p>从 {@link OrderService}（3,164 行）拆出的<b>建单编排</b>与 <b>Agent 取价守卫</b>：
 * {@code createOrder}（全类最大方法）、{@code createOrderForAgent}、{@code validateAgentItemUnitPrice}
 * 一族、站内信 {@code notifyOrderCreated}。拆的是<b>位置</b>，<b>不是行为</b>：方法体逐字搬运
 * （分支 / 异常类型 / 日志 / 守卫顺序不变），{@code @Transactional} 边界跟着方法走；
 * {@link OrderService} 保留同名门面委托，现有调用方（控制器 / 其它服务 / 既有单测）零改动。</p>
 *
 * <h2>共享部件（有意不搬，P2-1c 再拆）</h2>
 * <p>建单与<b>改单</b>（{@code OrderService.updatePendingOrderContent}）、<b>确认支付</b>
 * 共用同一份明细装配 / 取价 / 总额 / 库存前置校验（{@code assertItemAmountsValid} /
 * {@code priceItems} / {@code computeItemsTotal} / {@code persistOrderItems} /
 * {@code validateStockSufficientForRequest} 等）—— 它们是<b>唯一实现点</b>，
 * 搬走会迫使改单或支付路径另起第二份口径，所以留在 {@link OrderService}（金额计算族 = P2-1c 的边界）。
 * 本服务通过门面传入的 {@code OrderService} 实例复用它们（同一份实现，不复制算法、不加第二份判据）。</p>
 *
 * <p>为什么用<b>参数</b>而不是字段注入：{@link OrderService} 依赖本服务（门面委托）、本服务又要用它的
 * 共享部件 ⇒ 字段注入会形成 Spring 构造期环（Boot 3 默认禁止循环引用）。参数形态让依赖<b>单向</b>
 * （门面 → 本服务），且传进来的是 OrderService 的<b>目标实例</b>（不是 AOP 代理），
 * 包内可见的共享部件可直接调用（不必为拆分把它们放宽到 public）。</p>
 *
 * <p><b>有意不搬</b>（P2-1b 的边界）：状态流转（cancel / 发货 / refund）、查询族（P2-1a 已在
 * {@link OrderQueryService}）、金额计算与明细装配族（P2-1c）、库存 SKU 匹配族
 * （{@code matchSkuId} 与确认支付 / 取消回补共用）与整卷分配
 * （{@code applyRollAllocation}，明细落库共用）—— 它们仍在 {@link OrderService}。</p>
 */
@Slf4j
@Service
public class OrderCreationService {

    private final OrderMapper orderMapper;
    private final ProductMapper productMapper;
    private final ProductSkuMapper productSkuMapper;
    /** 建单的授信闸门（issue #7370）与首次下单自动建档（issue #7711）。 */
    private final CustomerService customerService;
    /** 制单人解析（issue #5835）。 */
    private final UserService userService;
    /** 站内信：新订单待处理（issue #2965 v2）。 */
    private final NotificationService notificationService;
    /** 建单的 Agent 幂等键（issue #4037）：占位 / 回放 / 释放 / 落快照。 */
    private final ClientRequestIdService clientRequestIdService;
    /** 下单时的服务端定价（issue #7375 段 2）。 */
    private final OrderPricingService orderPricingService;
    /** 具名审批回填（issue #7374 段 1）：可空（切片上下文 / 直接 new 的单测仅少一次回填）。 */
    private final ApprovalService approvalService;

    /** Agent 建单写面的幂等键命名空间（与控制器端点一致）。 */
    private static final String ENDPOINT_CREATE_ORDER = "POST /api/admin/agent/orders";

    public OrderCreationService(OrderMapper orderMapper,
                                ProductMapper productMapper,
                                ProductSkuMapper productSkuMapper,
                                CustomerService customerService,
                                UserService userService,
                                NotificationService notificationService,
                                ClientRequestIdService clientRequestIdService,
                                OrderPricingService orderPricingService,
                                ApprovalService approvalService) {
        this.orderMapper = orderMapper;
        this.productMapper = productMapper;
        this.productSkuMapper = productSkuMapper;
        this.customerService = customerService;
        this.userService = userService;
        this.notificationService = notificationService;
        this.clientRequestIdService = clientRequestIdService;
        this.orderPricingService = orderPricingService;
        this.approvalService = approvalService;
    }

    /**
     * 创建订单（issue #8191，P2-1b：实现点已从 OrderService 搬到本服务，方法体逐字未改）。
     *
     * @param request      创建请求
     * @param tenantId     租户ID
     * @param orderService 门面实例（本类复用它的共享部件：明细装配 / 取价 / 库存前置；见类注释）
     * @return 订单详情响应
     */
    @Transactional(rollbackFor = Exception.class)
    public OrderDetailResponse createOrder(OrderCreateRequest request, Long tenantId, OrderService orderService) {
        // ── 资金/库存完整性闸门（issue #3622 / #3682）：数量 ≥ 1，单价 > 0 ──
        // issue #3666：数量已放宽为 BigDecimal（DECIMAL(10,2)），per_area 的合法数量就是小数
        // （门幅 2.8m × 3m = 8.4 ㎡）——但不能因此放行 <1。
        // issue #3682：下限从「> 0」收紧为「≥ 1」——`items[].quantity` 直接驱动库存/销量。
        // ⚠️ **该下限在 issue #5063 / V115 之后仍是必需的，但理由已变**：库存列已小数化，
        // 取整点（原先的四处 `intValue()`）已全部消除 ⇒ 0.5 米**能**被正确扣减了；
        // 下限 1 现在守的是**业务口径**（按米卖布的最小起订量，与 admin-web 表单 `min={1}`、
        // ai-agent 工具层同口径），不再是「防 0.5 静默漏扣」的技术护栏。
        // 旧实现（quantity 为 Integer + agent 工具层拒绝非整数）在下单前就挡回 0.5 并给可行动
        // 提示，故 <1 是 #3666 放宽后**新可达**的静默漏扣。裁定（#3682 方案 A）：下限 = 1，
        // 与 admin-web 表单页 `min={1}` 及 ai-agent 工具层同口径；≥1 的小数仍合法（保真落库）。
        // 为什么必须在 Service 层显式判定（而不是只靠 DTO 注解）：
        //   ① Agent 路径 `createOrderForAgent`（下方 BFF 段）是**手工 new `OrderCreateRequest`**
        //      再调用本方法 —— 程序化构造的 Bean **不经过 Bean Validation**，注解对它无效；
        //   ② 本方法是三条路径（表单 / Agent / 未来程序化调用）的**唯一共享入口**，判在这里才无死角。
        // 不判的后果：负数量 → `unitPrice × 负数` 算出**负金额**落库；库存前置校验
        // （下方 validateStockSufficientForRequest）判据「需求量 ≤ 库存」对**负需求恒真**
        // → **超卖防线被绕过**；0 < 数量 < 1 → 库存/销量零扣减（本条 issue #3682）。
        orderService.assertItemAmountsValid(request.getItems());

        // 安装信息（issue #7856）：归一 + 准入**在任何写之前**（超长 ⇒ 422，一行都不落 —— 与上面
        // 资金闸门同一条纪律；否则会先 insert 订单再抛，靠事务回滚兜，多一次白写）。
        // 两者都**可选**（用户 2026-10-26：「C 端/客服收单允许先空、后台再补」）⇒ 空白 = 不落键。
        String installCommunity = OrderInstallInfo.normalizeCommunity(request.getInstallCommunity());
        orderService.normalizeInstallRooms(request.getItems());

        // ── 服务端定价（issue #7375 段 2）──
        // 口径见 OrderPricingService：只有**价格本命中**（协议/等级/阶梯）才覆盖客户端价 ——
        // 那是「承诺过的价」；没有价格本依据时不动（覆盖 = 凭空改单，且存量订单会一夜变价）。
        // 判在任何金额计算之前，且挂在三条路径（表单 / Agent / 程序化）共用的唯一入口上。
        List<OrderPricingService.LinePricing> linePricings =
                orderPricingService.applyServerPrices(request.getItems(), request.getCustomerPhone(), tenantId);

        // 计算总金额（后端独立计算：unitPrice * quantity + 加工费，不依赖前端 subtotal 防止不一致）
        // ── 加工费取价（issue #4406，用户裁定 2026-09-19）──
        // 口径 = 「按选配组合匹配 `processing_fee_combinations` → 取单价 → × 加工费米数」；
        // **未命中 ⇒ 0 + fee_source=unpriced + 可行动提示，绝不回落 Σ 加工项、绝不套默认价**
        // （#4308「静默回落」同族纪律：静默 = 算错钱且无人知道）。
        // 逐行结果按**下标**与 request.items 对齐（此刻明细行还没 id）。
        List<ProcessingFeeCalculator.Fee> itemFees = orderService.priceItems(request.getItems(), tenantId);
        // 金额精度准入（issue #6228）：总额 = Σ(单价×数量) + Σ 行加工费，是**计算值**（"积"）——
        // 单价与数量各自合法不代表积合法（`2.8 × 1.005` 出 3 位小数）⇒ 必须在写之前落一次准入。
        // 判在这里、且在下方任何写（syncProcessingFeeCombinations / insert）之前。
        BigDecimal totalAmount = MoneyScale.requireTwoDecimalsOrNull(
                orderService.computeItemsTotal(request.getItems(), itemFees), "订单总额");

        // ── 授信额度闸门（issue #7370，P0-2 段 1）──
        // 口径见 CreditPolicy：NULL = 未启用（存量客户零回归）；0 = 零额度（拒一切赊销）。
        // 判在**任何写之前**，且挂在三条路径（表单 / Agent / 程序化）共用的唯一入口上。
        // 审批出口（issue #7374 段 1）：超限时可由「已通过且未用掉」的超授信审批放行（一笔一批）
        String creditApprovalId =
                customerService.assertWithinCreditOrApproved(tenantId, request.getCustomerPhone(), totalAmount);

        // ── 建单同步回加工费组合配置（issue #4872）──
        // 用户原话「当订单创建成功后，同步新增加工费组合&单价到加工费配置中」。
        // 口径：只对 **fee_source=manual** 的行（= 组合未命中活跃价目 ∧ 本行给了正数 override）
        // 按 `compositionKey` **同源口径**（取价结果原样带来的 key/items，不另拼一套）upsert
        // 组合价 + 追加版本台账。幂等三态见 ProcessingFeeCombinationCommandService#upsertFromOrderOverride。
        // 🔴 无 manual 行 ⇒ **零调用**（正常建单路径不多一次写库、不改任何既有金额）。
        orderService.syncProcessingFeeCombinations(itemFees, tenantId);

        // 优惠金额（默认 0）；若提供了实收款，校验 应收 - 优惠 ≈ 实收（容差 0.01）
        // 金额精度准入（issue #6228）：`orders.discount_amount` / `orders.actual_amount` 均 NUMERIC(10,2)，
        // 超 2 位有效小数会被 PG 静默四舍五入 ⇒ 在**任何写之前**显式拒绝（不静默取整、不归一成 0）。
        BigDecimal discountAmount = MoneyScale.requireTwoDecimalsOrNull(request.getDiscountAmount(), "优惠金额");
        if (discountAmount == null) {
            discountAmount = BigDecimal.ZERO;
        }
        if (discountAmount.compareTo(BigDecimal.ZERO) < 0) {
            throw BusinessException.validationError("优惠金额不能为负数");
        }
        BigDecimal requestedActual = MoneyScale.requireTwoDecimalsOrNull(request.getActualAmount(), "实收金额");
        if (requestedActual != null) {
            BigDecimal expected = totalAmount.subtract(discountAmount);
            if (expected.subtract(requestedActual).abs().compareTo(new BigDecimal("0.01")) > 0) {
                throw BusinessException.validationError(
                        String.format("实收金额与应收不一致：应收 %s - 优惠 %s = %s，实收 %s（容差 0.01）",
                                totalAmount, discountAmount, expected, requestedActual));
            }
        }

        // 前置库存校验：库存不足拒绝创建订单（提示前移至下单时，issue #2922）。
        // 与确认支付共用同一套 SKU 匹配/库存口径（validateStockSufficient），
        // 无 SKU 匹配的明细不校验（与扣减语义一致）。
        orderService.validateStockSufficientForRequest(request, "下单");

        // 创建订单实体
        Order order = new Order();
        order.setTenantId(tenantId);
        order.setOrderNo(orderService.generateOrderNo());
        order.setCustomerName(request.getCustomerName());
        order.setCustomerPhone(request.getCustomerPhone());
        order.setCustomerAddress(request.getCustomerAddress());
        order.setTotalAmount(totalAmount);
        // 实收款：用户输入值，未输入时默认等于订单总额
        order.setActualAmount(requestedActual != null ? requestedActual : totalAmount);
        // 优惠金额落库
        order.setDiscountAmount(discountAmount);
        order.setStatus("pending");
        order.setRemark(request.getRemark());
        // C 端数据隔离：绑定下单用户（可为空=游客/商户代录）
        order.setUserId(request.getUserId());
        // ── 制单人（issue #5835，V142）──
        // 用户 2026-09-30 逐字：「制单人这个字段可以不用加到订单详情中，但是要加到订单列表中，
        // 并且支持根据制单人过滤」。
        // **单点落库**：本方法是三条建单路径（B 端 admin-web 表单 / 黄金策 order_create /
        // 程序化调用）的**唯一共享入口** ⇒ 在这里统一解析当前操作者，各 controller 不各拼一遍
        // （在 controller 里拼会漏掉 `createOrderForAgent` 这条手工 new 出来的路径）。
        // 🔴 取不到（service 占位 internal-service / 匿名 / C 端自助下单）⇒ **两列都不写**
        //    （留 NULL ⇒ 列表显示「—」且不参与按人筛选）。**不猜**：留痕字段宁缺勿造。
        UserService.CurrentOperator creator = userService.resolveCurrentOperator();
        if (creator != null) {
            order.setCreatedBy(creator.userId());
            order.setCreatedByName(creator.displayName());
        }
        // 订单收货物流两列（issue #4872；用户原话「新增订单时收货信息中缺少用户的常用物流/快递以及常用公司」）：
        // `orders.logistics_type` / `orders.logistics_company`（V100 迁移）。
        // 🔴 **未传 ⇒ 不写**（MyBatis-Plus 默认策略下 null 字段不进 INSERT ⇒ 落列默认
        // `logistics_type='express'` / `logistics_company=NULL`）—— **不猜**调用方的意图。
        if (StringUtils.hasText(request.getLogisticsType())) {
            order.setLogisticsType(request.getLogisticsType().trim());
        }
        if (StringUtils.hasText(request.getLogisticsCompany())) {
            order.setLogisticsCompany(request.getLogisticsCompany().trim());
        }
        // 订单级加急 / 客户要求到货日（V120，issue #5177）—— 🔴 **缺省值不变**：
        // `isUrgent == null` ⇒ **不写该列**（MyBatis-Plus 默认策略下 null 字段不进 INSERT）
        // ⇒ 落列默认 FALSE = 今天的行为（所有单都不加急、都进池）；
        // `requiredDeliveryDate == null` ⇒ 不写 ⇒ NULL = **未指定**（不用今天/承诺交期顶替 —— 不猜）。
        // 这两列只影响**是否入池/派单时机**，不参与本方法任何金额计算
        //（totalAmount / actualAmount / discountAmount 的算式一字未动 ⇒ 对客口径逐值不变，判据 6）。
        if (request.getIsUrgent() != null) {
            order.setIsUrgent(request.getIsUrgent());
        }
        if (request.getRequiredDeliveryDate() != null) {
            order.setRequiredDeliveryDate(request.getRequiredDeliveryDate());
        }
        // 外发加工标记（V194）：与加急同一条纪律 —— 未传 ⇒ 不写列（落默认 FALSE），不猜。
        if (request.getIsOutsourced() != null) {
            order.setIsOutsourced(request.getIsOutsourced());
        }

        // 保存订单
        orderMapper.insert(order);

        // 保存订单明细
        // 安装小区（issue #7856）：**唯一写点扇出**在 persistOrderItems 里（逐行写进
        // `processing_info.installCommunity`）—— 订单级语义、行数组载体 ⇒ 落每行同一字符串。
        // 归一 + 准入（去空白 / 折叠内部换行 / ≤40 字，超长 422）在这里做一次，落库前就拒。
        orderService.persistOrderItems(order, request.getItems(), itemFees, tenantId, linePricings, installCommunity);

        // 审批留痕回填（issue #7374 段 1）：超授信是被审批放行的，把那笔审批的「用在哪」补成这张订单
        // （闸门跑在下单之前，那时还没有 order id —— 所以是事后回填，不是闸门内直接写）
        if (creditApprovalId != null && approvalService != null) {
            approvalService.attachConsumedRef(creditApprovalId, order.getId());
        }

        // 定价改写留痕（issue #7375 段 2，判据「不一致 ⇒ 服务端为准且记录差异」）：
        // 只在**真的改写了**某行时写一条审计（没有改写 = 没有差异 = 不制造噪音）。
        orderService.recordPriceOverrideAudit(order, linePricings);

        log.info("创建订单成功: id={}, orderNo={}, totalAmount={}", order.getId(), order.getOrderNo(), totalAmount);

        // 首次下单自动创建/收敛客户档案（失败不影响订单创建）
        // issue #7711：把订单里填的**收货人姓名/电话/地址 + 常用物流**一并带给档案（补空不覆盖），
        // 并带上 userId（C 端自助下单 ⇒ 用它解析 openid，和「登录建档那条」认成同一个人）。
        try {
            customerService.createFromOrder(tenantId, request.getCustomerName(),
                    request.getCustomerPhone(), request.getCustomerAddress(),
                    order.getLogisticsType(), order.getLogisticsCompany(), request.getUserId());
        } catch (Exception e) {
            log.warn("订单创建后自动建档客户失败，忽略: orderId={}, phone={}, error={}",
                    order.getId(), request.getCustomerPhone(), e.getMessage());
        }

        // 站内信：新订单创建成功，通知订单归属用户（无归属用户则跳过）
        notifyOrderCreated(tenantId, order, totalAmount);

        return orderService.getOrderById(order.getId());
    }

    /**
     * Agent 专用创建订单。
     *
     * <p><b>校验口径（issue #4089 · A17 收敛）</b>：入参是 {@link OrderCreateRequest} 的**子类型**
     * （{@code AgentOrderCreateRequest} 只多一个请求头注入的幂等键），约束全部来自共享类型，
     * 由 {@code AgentOrderController} 的 {@code @Valid} 执行；本方法**不再手工 {@code new}
     * 一个 {@code OrderCreateRequest} 逐字段搬运**（那正是「校验双写」的载体：手工 new 让
     * Bean Validation 失效 ⇒ 这里必须再判一遍 ⇒ 两处口径必然漂移），而是把请求**原对象**
     * 交给 {@link #createOrder}（同一入口、同一套断言、同一份文案）。</p>
     *
     * <p>只保留两条**Bean Validation 表达不了**的 agent 专属语义：
     * ① 姓名/电话非空 + 手机号格式（共享类型上的 {@code @NotBlank}/{@code @Pattern} 已在控制器层
     * 执行，这里保留同名同文案的显式判定，兜住绕过 HTTP 的程序化调用方 —— 与 {@code createOrder}
     * 的数量/单价闸门同族，不是第二套口径）；
     * ② 服务端取价校验 {@link #validateAgentItemUnitPrice}（SKU 权威价，见该方法）。</p>
     *
     * <p>幂等键（issue #4037，F19）：请求头 {@code X-Client-Request-Id} 非空时按
     * {@code (tenantId, 键)} 去重 —— 首次请求正常执行并把 {@link OrderDetailResponse} 快照落库，
     * 同键再次到达**不再执行**、直接回放首次结果（顾客/LLM 看到同一订单号）。无键 ⇒ 原路径逐字不变。</p>
     *
     * <p><b>并发语义（如实登记，不谎称「并发也直接回放」）</b>：本方法带
     * {@code @Transactional}，而 {@code claim}/{@code complete}/{@code discard} 跑在**同一个事务**里
     * ⇒ ① 成功才一起提交、失败一起回滚（占位不会残留）；② **并发同键**时第二个请求的
     * {@code INSERT ... ON CONFLICT DO NOTHING} 会**阻塞在唯一索引上**，直到第一个提交或回滚 ——
     * 提交后它读到已落库的快照并回放（同一订单号），回滚后它自己成为首次执行者。
     * 即并发是「串行等待」而非「立即回放」；这是刻意取舍（换取「不留残留占位」与更少机器），
     * 代价是同键并发第二个请求的响应时间被拉长。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public OrderDetailResponse createOrderForAgent(AgentOrderCreateRequest request, Long tenantId, OrderService orderService) {

        if (!StringUtils.hasText(request.getCustomerName())) {
            throw BusinessException.validationError("客户姓名不能为空");
        }
        if (!StringUtils.hasText(request.getCustomerPhone())) {
            throw BusinessException.validationError("客户电话不能为空");
        }
        // 手机号格式校验（与共享 DTO 的 @Pattern 同一条正则、同一句文案）
        String phone = request.getCustomerPhone().trim();
        if (!phone.matches("^1[3-9]\\d{9}$")) {
            throw BusinessException.validationError("手机号格式不正确，请输入11位中国大陆手机号");
        }
        request.setCustomerPhone(phone);

        if (request.getItems() == null || request.getItems().isEmpty()) {
            throw BusinessException.validationError("商品明细不能为空");
        }

        for (OrderCreateRequest.OrderItemRequest item : request.getItems()) {
            // GB/T 47746-2026 M3（issue #2806）：服务端取价校验——权威价**唯一可得**时，
            // unitPrice 必须与权威价严格一致（防 LLM 定价幻觉）。
            // ⚠️ issue #3881 缺陷二 / #4025 F11（本 PR）：改前此处是「解析不到不拦截防误伤」，
            // 即无 SKU 标识的行单价零核对落库；现在**无标识也要核**（按商品级唯一权威价），
            // 无从确定即 422 —— 判据见 validateAgentItemUnitPrice 的 javadoc。
            // 规格键（skuCode/colorName，以及工具层首选键 skuId）从 processingInfo 解析。
            validateAgentItemUnitPrice(item, tenantId);
            // subtotal 服务端强制重算（对抗 LLM 编造）—— 逐字保留收敛前的口径演算：
            // `order_items.subtotal` 直接喂 `products.sales_amount`（见 adjustStockAndSales），
            // 不能让客户端自称的小计进统计口径。这不是「第二套校验」（约束来自共享类型），
            // 是**唯一**的口径归一化点。
            if (item.getQuantity() != null && item.getUnitPrice() != null) {
                item.setSubtotal(item.getUnitPrice().multiply(item.getQuantity()));
            }
        }

        // ── 幂等键（issue #4037）：同 (tenantId, X-Client-Request-Id) 只真正执行一次 ──
        String clientRequestId = request.getClientRequestId();
        // 无幂等键（老 ai-agent / 表单类调用方）⇒ 原路径逐字不变：零 DB 往返、不因服务端升级而报错
        if (!StringUtils.hasText(clientRequestId)) {
            return createOrder(request, tenantId, orderService);
        }
        // ① 原子占位（INSERT ... ON CONFLICT DO NOTHING，按影响行数判首次）——
        //    不用「捕获唯一约束异常」探测冲突：PG 里冲突会让当前事务进入 aborted 状态，后续查询全失败
        if (!clientRequestIdService.claim(tenantId, clientRequestId, ENDPOINT_CREATE_ORDER)) {
            // ② 同键重复 ⇒ 不执行，直接回放首次成功快照（replay 对「占位但无结果」fail-closed 抛错）
            return clientRequestIdService.replay(tenantId, clientRequestId, OrderDetailResponse.class)
                    .orElseThrow(() -> new BusinessException("REQUEST_IN_PROGRESS",
                            "同一 X-Client-Request-Id 的请求正在处理中，本次未重复执行（请勿重复提交）",
                            409,
                            "请勿重复提交；请稍后用 order_query 查询确认结果（换新幂等键重试同样会造成重复下单）"));
        }
        OrderDetailResponse created;
        try {
            created = createOrder(request, tenantId, orderService);
        } catch (RuntimeException e) {
            // ④ 执行失败 ⇒ 释放占位：否则一次失败就把该键永久占死，之后的重试全被误判为「重复」
            clientRequestIdService.discard(tenantId, clientRequestId);
            throw e; // 原样抛出，不吞（失败必须对调用方可见）
        }
        // ③ 执行成功 ⇒ 落结果快照，同键后续请求回放它。放在 try 之外：
        //    快照写失败时**不得**释放占位（订单已经建出来了），宁可让同键请求 fail-closed 报错
        clientRequestIdService.complete(tenantId, clientRequestId, created);
        return created;
    }

    /**
     * Agent 下单明细单价的服务端取价校验（GB/T 47746-2026 M3，issue #2806）。
     *
     * 规则（严格一致才放行，用户已确认）：
     * - 明细声明了 SKU 身份键（键族与 {@link OrderService#matchSkuId} **同一族**：{@code skuId}（ID 族，
     *   工具层声明的「首选键」）/ {@code skuCode} / {@code colorName}）且能解析到唯一 SKU →
     *   请求 unitPrice 必须与 SKU 权威价一致（BigDecimal compareTo == 0），不一致抛 422 并附权威价供修正；
     * - 声明了键族却解析不到 / 命中多条无法唯一确定 → **不在此拦截**（防误伤），记 warn
     *   （库存路径另有 issue #4090 的显式拒绝，两层判据分工不同、不合并）；
     * - <b>未声明任何 SKU 身份键（issue #3881 缺陷二 / #4025 F11）→ 不再静默放过</b>：改前这里是
     *   {@code return}（单价**零核对**落库 —— 明细可以只有 product_name，{@code order_items.product_id}
     *   落 NULL，编造价一路进总额且无告警）。改后按**商品级权威价**核对
     *   （见 {@link #validateAgentItemUnitPriceByProductAuthority}）：权威价唯一可得
     *   （商品可解析且规格价唯一，或无 SKU 记录的简单商品有商品级价）⇒ 与声明键族的行
     *   **同一口径**严格核对；无从确定 ⇒ 422（可行动文案，指名缺什么）。</p>
     *
     * <p>规格键只在 {@code processingInfo} 内（issue #4089 收敛后 DTO 不再有顶层
     * {@code skuCode}/{@code colorName} 字段——那正是 issue 清单的 D1/D2：唯一生产者从不填它们，
     * 而库存匹配键族也不读它们）。</p>
     */
    private void validateAgentItemUnitPrice(OrderCreateRequest.OrderItemRequest item, Long tenantId) {
        if (item.getUnitPrice() == null) {
            return;
        }
        // SKU 标识从 processingInfo（商品销售信息）内解析 —— ai-agent order_create 与表单页
        // 两个生产者的真实形态
        String skuCode = null;
        String colorName = null;
        Long skuId = null;
        if (item.getProcessingInfo() instanceof Map<?, ?> info) {
            Object rawSku = info.get("skuCode");
            if (rawSku != null) {
                skuCode = String.valueOf(rawSku);
            }
            Object rawColor = info.get("colorName");
            if (rawColor != null) {
                colorName = String.valueOf(rawColor);
            }
            // issue #3881 缺陷二同族（本 PR 顺带修）：order_create 工具描述把 skuId 定为「首选键」，
            // 而本守卫此前**只认** skuCode/colorName ⇒ 照工具描述传 skuId 的行反被判成
            // 「无 SKU 标识」→ 静默放过（最精确的键落进 fail-open 分支）。
            skuId = toSkuIdOrNull(info.get("skuId"));
        }
        // ① ID 族最精确：直查该 SKU（归属同商品才认；陈旧/越界的 skuId 回落到键族，不在此拒绝）
        if (skuId != null) {
            ProductSku byId = productSkuMapper.selectById(skuId);
            if (byId != null && byId.getPrice() != null
                    && (item.getProductId() == null
                        || item.getProductId().equals(byId.getProductId()))) {
                assertUnitPriceMatchesAuthority(item, byId.getPrice());
                return;
            }
            log.warn("[order] 取价校验：processingInfo.skuId 不可用（库中不存在或不属于该商品），回落键族/商品级: productId={} skuId={}",
                    item.getProductId(), skuId);
        }
        // ② 字符串键族（skuCode / colorName）：现口径逐字保留
        if (StringUtils.hasText(item.getProductId())
                && (StringUtils.hasText(skuCode) || StringUtils.hasText(colorName))) {
            LambdaQueryWrapper<ProductSku> wrapper = new LambdaQueryWrapper<>();
            wrapper.eq(ProductSku::getTenantId, tenantId)
                    .eq(ProductSku::getProductId, item.getProductId());
            if (StringUtils.hasText(skuCode)) {
                wrapper.eq(ProductSku::getSkuCode, skuCode);
            } else {
                wrapper.eq(ProductSku::getColorName, colorName);
            }
            wrapper.orderByAsc(ProductSku::getId)
                    .last("LIMIT 2"); // 取 2 条探测歧义
            List<ProductSku> skus = productSkuMapper.selectList(wrapper);
            if (skus == null || skus.isEmpty()) {
                log.warn("[order] 取价校验跳过（SKU 未解析到）: productId={} skuCode={} colorName={}",
                        item.getProductId(), skuCode, colorName);
                return;
            }
            if (skus.size() > 1) {
                log.warn("[order] 取价校验跳过（SKU 不唯一，无法确定权威价）: productId={} skuCode={}",
                        item.getProductId(), skuCode);
                return;
            }
            BigDecimal authoritative = skus.get(0).getPrice();
            if (authoritative == null) {
                return; // SKU 无价格，无从校验
            }
            assertUnitPriceMatchesAuthority(item, authoritative);
            return;
        }
        // ③ 无（有效）SKU 身份键 ⇒ 商品级权威价核对 / fail-closed（issue #3881 缺陷二、#4025 F11）
        validateAgentItemUnitPriceByProductAuthority(item, tenantId);
    }

    /**
     * 无 SKU 身份键时的**商品级**取价校验（issue #3881 缺陷二 / #4025 F11：fail-open → fail-closed）。
     *
     * <p>改前形态（本方法要修的那一行）：{@code !productId || !hasSkuKey ⇒ return}（只记 warn）
     * —— 单价零核对落库。#3881 原文：「工具描述『不传时服务端通过 product_name 自动匹配』
     * —— OrderService 无此逻辑（grep 无命中），product_id 落库为 NULL」。</p>
     *
     * <p><b>只拦真正无从核价的那种（合法形态不受影响）</b>：商品可解析且其 SKU 价集合唯一
     * （或无 SKU 记录但有商品级价的简单商品 —— 卖布行那种「商品级一个价」的形态）⇒ 该价即
     * 权威价，与声明键族的行同一口径核对；只有「商品解析不到 / 多个不同规格价而未声明规格 /
     * 完全无价」才 422。<b>商品名唯一匹配</b>不是新造口径：ai-agent 工具层接地解析
     * （{@code order_create._resolve_library_grounded}）用的就是「product_id 或 product_name
     * 唯一匹配」，此处只是让服务端守卫不再把它当「无标识」放过。</p>
     */
    private void validateAgentItemUnitPriceByProductAuthority(OrderCreateRequest.OrderItemRequest item,
                                                             Long tenantId) {
        Product product = resolveProductForUnitPrice(item, tenantId);
        if (product == null) {
            throw noAuthorityReject(item, productMissingReason(item),
                    "请补齐商品标识后重试：用 product_detail 拿到商品 id 填入 items[].product_id；"
                            + "该商品有多个规格价时，还要在 items[].processing_info 里带上 skuId"
                            + "（product_detail 的 skus[].id，最精确；也可用 skuCode / colorName，多门幅时附 doorWidth）。");
        }
        List<ProductSku> skus = productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getTenantId, tenantId)
                .eq(ProductSku::getProductId, product.getId())
                .orderByAsc(ProductSku::getId));
        BigDecimal authoritative;
        if (skus != null && !skus.isEmpty()) {
            authoritative = uniquePriceOf(skus);
            if (authoritative == null) {
                throw noAuthorityReject(item,
                        String.format("该商品 %d 个 SKU 存在多个不同规格价，而本行未声明规格", skus.size()),
                        "请在 items[].processing_info 里补 skuId（product_detail 的 skus[].id，最精确）"
                                + "或 skuCode / colorName（多门幅时附 doorWidth），再按该规格的库价下单。");
            }
        } else {
            // 无 SKU 记录的商品（简单商品 / 卖布行形态）：权威价 = 商品级价，**显式允许**
            // （#3881 的 P0 建议原文：「无 SKU 时 base_price 且须显式允许」）
            authoritative = product.getBasePrice();
            if (authoritative == null) {
                throw noAuthorityReject(item, "该商品既没有 SKU 记录也没有商品级价",
                        "请先在商品库为该商品配置价格（商品级价或 SKU 价）后再下单。");
            }
        }
        assertUnitPriceMatchesAuthority(item, authoritative);
    }

    /** 无权威价可核对 ⇒ 422（复用既有 {@code VALIDATION_ERROR} 信封 + suggestion，不另造错误形状）。 */
    private BusinessException noAuthorityReject(OrderCreateRequest.OrderItemRequest item,
                                                String reason, String suggestion) {
        String message = String.format(
                "商品「%s」单价 %s 元无法核对（%s）—— 按 fail-closed 拒绝下单（issue #3881）。",
                item.getProductName(), item.getUnitPrice().toPlainString(), reason);
        log.warn("[order] 取价校验拒绝（无权威价可核对，fail-closed）: productId={} productName={} unitPrice={} reason={}",
                item.getProductId(), item.getProductName(), item.getUnitPrice(), reason);
        return new BusinessException("VALIDATION_ERROR", message, 422, suggestion);
    }

    private String productMissingReason(OrderCreateRequest.OrderItemRequest item) {
        if (StringUtils.hasText(item.getProductId())) {
            return String.format("商品标识 product_id=%s 在商品库中不存在或不属于本租户", item.getProductId());
        }
        if (StringUtils.hasText(item.getProductName())) {
            return String.format("商品名「%s」在商品库中匹配不到唯一商品（查不到或同名多条）", item.getProductName());
        }
        return "该行既没有 product_id 也没有 product_name";
    }

    /**
     * 取价校验用的商品解析：{@code productId} 优先（**归属同租户**才算），否则按商品名**唯一**匹配
     * （同名多条 ⇒ 返回 null，不猜是哪一个 —— 猜错商品 = 按错价核对）。
     */
    private Product resolveProductForUnitPrice(OrderCreateRequest.OrderItemRequest item, Long tenantId) {
        if (StringUtils.hasText(item.getProductId())) {
            Product byId = productMapper.selectById(item.getProductId());
            return byId != null && tenantId != null && tenantId.equals(byId.getTenantId()) ? byId : null;
        }
        if (!StringUtils.hasText(item.getProductName())) {
            return null;
        }
        List<Product> byName = productMapper.selectList(new LambdaQueryWrapper<Product>()
                .eq(Product::getTenantId, tenantId)
                .eq(Product::getName, item.getProductName().trim())
                .orderByAsc(Product::getId)
                .last("LIMIT 2"));
        return byName != null && byName.size() == 1 ? byName.get(0) : null;
    }

    /** 候选 SKU 的**唯一**权威价：价格集合去重后恰一个 ⇒ 返回它；多个不同价 / 全无价 ⇒ null。 */
    private static BigDecimal uniquePriceOf(List<ProductSku> skus) {
        BigDecimal only = null;
        for (ProductSku sku : skus) {
            BigDecimal price = sku == null ? null : sku.getPrice();
            if (price == null) {
                continue;
            }
            if (only == null) {
                only = price;
            } else if (only.compareTo(price) != 0) {
                return null;
            }
        }
        return only;
    }

    /** 单价必须与权威价严格一致（BigDecimal compareTo == 0），否则 422 并附权威价供修正。 */
    private void assertUnitPriceMatchesAuthority(OrderCreateRequest.OrderItemRequest item,
                                                BigDecimal authoritative) {
        if (item.getUnitPrice().compareTo(authoritative) != 0) {
            log.warn("[order] 取价校验拒绝（LLM 单价≠权威价）: productId={} request={} authoritative={}",
                    item.getProductId(), item.getUnitPrice(), authoritative);
            throw BusinessException.validationError(
                    String.format("商品「%s」单价与系统价格不一致：请求 %.2f 元，系统价 %.2f 元。请以系统价重新下单。",
                            item.getProductName(), item.getUnitPrice(), authoritative));
        }
    }

    /** {@code processingInfo.skuId} 解析：非数字/空 ⇒ 视为未声明（回落由键族负责，不在此拒绝）。 */
    private static Long toSkuIdOrNull(Object raw) {
        if (raw == null) {
            return null;
        }
        if (raw instanceof Number number) {
            return number.longValue();
        }
        try {
            return Long.valueOf(String.valueOf(raw).trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /**
     * 站内信：新订单待处理（order_created 事件）
     *
     * 接收人路由（issue #2965 v2）：只有存在归属用户（C 端自助下单）时才属于
     * 「新订单待处理」场景，通知租户管理员（B 端铃铛）——管理员据此跟进确认；
     * 商户代录的订单（无归属用户）由录入者自行感知，不发送避免噪音。
     */
    private void notifyOrderCreated(Long tenantId, Order order, BigDecimal totalAmount) {
        if (order.getUserId() == null || order.getUserId().isBlank()) {
            log.debug("[notify] 订单无归属用户（商户代录），跳过新订单通知: orderId={}", order.getId());
            return;
        }
        try {
            Map<String, String> vars = new HashMap<>();
            vars.put("orderNo", order.getOrderNo() != null ? order.getOrderNo() : order.getId());
            vars.put("amount", totalAmount != null ? totalAmount.toPlainString() : "0.00");
            notificationService.triggerForTenantAdmins(tenantId, "order_created", vars);
        } catch (Exception e) {
            log.warn("[notify] 新订单站内信发送失败，忽略: orderId={}, error={}",
                    order.getId(), e.getMessage());
        }
    }
}
