package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.*;
import com.migao.admin.dto.agent.AgentOrderCreateRequest;
import com.migao.admin.dto.agent.AgentOrderResolveResponse;
import com.migao.admin.dto.agent.AgentOrderUpdateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.PrintLogMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.time.BusinessClock;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.ThreadLocalRandom;
import java.util.stream.Collectors;

/**
 * 订单服务类
 * 处理订单的增删改查、状态更新等操作
 *
 * <p><b>拆分沿革（issue #8191）</b>：查询族已搬到 {@link OrderQueryService}（P2-1a）、
 * 创建族已搬到 {@link OrderCreationService}（P2-1b）、库存与财务流水族已搬到
 * {@link OrderStockService} / {@link OrderFeeSupport}（P2-1c）、取消 / 退款 / 发货 / 状态流转族已搬到
 * {@link OrderLifecycleService}（P2-1d）；本类保留同名<b>门面委托</b>，调用方零改动。</p>
 *
 * <p><b>包内可见的共享部件</b>（issue #8191，P2-1b）：建单与改单（{@code updatePendingOrderContent}）/
 * 确认支付共用同一份明细装配、取价、总额与库存前置校验（{@code assertItemAmountsValid} /
 * {@code priceItems} / {@code computeItemsTotal} / {@code persistOrderItems} /
 * {@code validateStockSufficientForRequest} / {@code generateOrderNo} 等）—— 它们是<b>唯一实现点</b>
 * （金额计算族 = P2-1c 的边界），故由 {@code private} 放宽为<b>包内可见</b>，供
 * {@link OrderCreationService} 经门面传入的本类实例复用（不产生第二份口径）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrderService extends ServiceImpl<OrderMapper, Order> {

    /** 业务时钟（issue #3802）：业务「今天」的唯一来源。Spring 注入单例；**不扫描 @Component 的切片上下文**
     * （@WebMvcTest / ApplicationContextRunner）与直接 new 构造的既有单测没有该 bean ⇒ required=false +
     * 默认实例（同为 +08 口径，行为一致），不因引入时钟让任何既有上下文启动失败（实测 OssEmptyConfigContextTest）。 */
    @Autowired(required = false)
    private BusinessClock businessClock = new BusinessClock();

    /**
     * 订单列表的**默认回溯窗口**（issue #7404：用户裁定「不允许查全部」／「最多回溯近 3 年」）。
     *
     * <p>只在不给下单时间范围时生效（见 {@code getOrderPage}）—— 显式区间原样透传，不被截断。
     * 取 3 年而不是 12 个月：常见诉求是「翻去年的单 / 客户查三年前的记录」，
     * 而 3 年窗口下单租户的订单量仍是万级（月订单几千），关键词 {@code LIKE '%kw%'} 逐行匹配在毫秒级。</p>
     */
    static final int DEFAULT_LOOKBACK_MONTHS = 36;

    /** 订单列表的生效时间窗：半开区间 {@code [start, end)}，两条边界**恒非空**（兜底在 {@link #resolveListWindow}）。 */
    record ListDateWindow(OffsetDateTime start, OffsetDateTime end) {
    }

    /**
     * 解析订单列表的**生效**下单时间窗（issue #7404）。
     *
     * <p>口径（顺序即安全顺序）：</p>
     * <ol>
     *   <li>显式给了 {@code startDate}/{@code endDate} ⇒ **原样**使用（要查更早的历史单，自己选日期即可）；</li>
     *   <li>没给起点 ⇒ 起点 = 「终止日（没给就是今天）− {@value #DEFAULT_LOOKBACK_MONTHS} 个月」；</li>
     *   <li>没给终点 ⇒ 终点 = 「今天 + 1 天」（与显式区间同口径的半开区间）。</li>
     * </ol>
     *
     * <p>⇒ 「忘选 / 清空日期」不再退化成**无时间谓词**的查询。为什么必须兜底：关键词是
     * {@code LIKE '%kw%'}（name / phone / order_no 三列 OR），B-tree 用不上 ⇒ 无时间谓词时是
     * 「本租户全部订单逐行匹配」，且分页每次 {@code COUNT(*)} 都要再来一遍。</p>
     *
     * <p>为什么是「补齐」而不是 400 拒绝：AI 侧 {@code logistics_track} 工具用
     * {@code GET /api/admin/orders?keyword=<单号>}（**不带日期**）解析订单号 —— 拒绝会让物流追踪当场坏掉。</p>
     */
    static ListDateWindow resolveListWindow(String startDate, String endDate, BusinessClock clock) {
        boolean hasStart = StringUtils.hasText(startDate);
        boolean hasEnd = StringUtils.hasText(endDate);
        LocalDate today = clock.today();
        LocalDate startDay = hasStart
                ? LocalDate.parse(startDate)
                : (hasEnd ? LocalDate.parse(endDate) : today).minusMonths(DEFAULT_LOOKBACK_MONTHS);
        LocalDate endDayExclusive = hasEnd ? LocalDate.parse(endDate).plusDays(1) : today.plusDays(1);
        return new ListDateWindow(clock.startOfDay(startDay), clock.startOfDay(endDayExclusive));
    }

    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;
    private final OrderLogisticsMapper orderLogisticsMapper;
    private final CustomerService customerService;
    private final ProductMapper productMapper;
    private final ProductSkuMapper productSkuMapper;
    private final FinanceTransactionMapper financeTransactionMapper;
    private final ObjectMapper objectMapper;
    private final NotificationService notificationService;
    private final ProcessingOrderMapper processingOrderMapper;
    /** 发货人兜底解析（issue #3768）：当前登录用户姓名 */
    private final UserService userService;
    /** 写请求幂等键（issue #4037）：去重 / 结果回放 / 占位释放 */
    private final ClientRequestIdService clientRequestIdService;
    /**
     * 库存流水/台账（issue #4137）：订单腿（下单扣减 / 取消回补）的落账写入方。
     * 落账唯一语义点在该服务（delta 由 after-before 算出），本类只提供「变更前快照 + 变更点」。
     */
    private final StockLedgerService stockLedgerService;
    /**
     * 加工费**取价点**（issue #4406）：选配组合 → {@code processing_fee_combinations} 单价 × 加工费米数。
     * 加工费只有这一个算法（本类不再自己 Σ 加工项 —— 那正是「配了组合费用订单金额一分不变」的病根）。
     */
    private final ProcessingFeeCalculator processingFeeCalculator;
    /**
     * 加工费组合定价**写面**（issue #4872）：建单成功时把「人工改价」的组合同步回配置
     * （{@code processing_fee_combinations} + 版本台账）。为什么不直接注 Mapper：版本台账
     * ({@code appendVersion}) 是写面的既有机制，绕过去 = 改价无痕。
     */
    private final ProcessingFeeCombinationCommandService processingFeeCombinationCommandService;

    /**
     * 池化事件通知点（issue #5182）：**既有业务完成之后**追加的一句 fail-soft 通知。
     *
     * <p><b>字段注入</b>的理由同 {@code ProcessingOrderService.stockBatchConsumptionService}：
     * 本类构造签名被多处测试显式装配，加参数会把它们全改一遍。{@code required = false}
     * 且调用侧走 {@link PoolChangeNotifier#notifySafely}（{@code null} ⇒ 跳过并留痕）——
     * 通知点是**优化触发**，绝不因为它未装配/抛异常让确认支付失败。</p>
     */
    @Autowired(required = false)
    private PoolChangeNotifier poolChangeNotifier;

    /**
     * 单据联动工序（issue #7165）：字段注入理由同 {@code poolChangeNotifier} —— 本类构造签名被
     * 多处测试显式装配，加参数会把它们全改一遍；{@code null}（单测切片）⇒ 跳过联动，
     * 发货守卫行为不变。
     */
    @Autowired(required = false)
    private DocumentOperationLinkage documentOperationLinkage;

    /**
     * 批次消耗台账（V116，issue #5145 阶段 1）：**订单取消自动作废加工单**这条路上的批次回补。
     *
     * <p>为什么这里必须有它：{@link #cancelOrder} 对 {@code generated} 态加工单是**直接
     * {@code updateById} 置 cancelled**、<b>绕过</b> {@code ProcessingOrderService.updateStatus}
     * —— 派工扣减的对称回补挂在后者。不在这里接同一句话，「订单取消 → 加工单自动作废」这一条路
     * 就成了**只扣不回补**的单向账（判据「对称回补」在这条路上直接不成立）。</p>
     *
     * <p>字段注入而非构造参数：本类构造签名被测试显式装配（{@code OrderStockLedgerTest} /
     * {@code StockLedgerTest}），加参数会改动既有测试装配 —— 同
     * {@code ProductionController.processingFeeQueryService} 的先例与理由。
     * Spring 生产装配下一定非 null；真装配不上时 {@link #batchStock()} **显式抛错**，
     * 绝不静默跳过回补。</p>
     */
    @org.springframework.beans.factory.annotation.Autowired
    private StockBatchConsumptionService stockBatchConsumptionService;

    /**
     * 打印流水（V201，issue #7902）：订单列表「是否已打印」三个读数（{@code printedAt} / {@code printCount} /
     * {@code printedDocTypes}）的唯一数据面。
     *
     * <p><b>字段注入而非构造参数</b>，理由同 {@link #stockBatchConsumptionService}：本类构造签名被多处
     * 测试显式装配（{@code new OrderService(...)}），加参数会把它们全改一遍。
     * <b>Spring 生产装配下一定非 null</b>；单测切片里为 null ⇒ 三个读数是「未打印」的确定值
     * （{@code null / 0 / []}，与「这单确实没打过」同形 —— 列表不会因此报错，也不会编出一个打印时间）。
     * 判据：{@code OrderServicePrintStatusTest}（批量只查一次 / 未打印是确定值 / 空页不发查询）。</p>
     */
    @org.springframework.beans.factory.annotation.Autowired(required = false)
    private PrintLogMapper printLogMapper;

    /**
     * 审计留痕（issue #5842）：订单**内容编辑**的前后差异落 {@code audit_logs}。
     *
     * <p>字段注入而非构造参数：本类构造签名被测试与其它装配点显式引用，
     * 加参数会改动既有测试装配 —— 同 {@link #stockBatchConsumptionService} 的先例与理由
     * （{@code OrderShipGuard} 的类注释也记着同一件事：给它加一个构造依赖会波及
     * 全部 {@code new OrderService(...)} / {@code @InjectMocks} 的既有单测）。</p>
     *
     * <p>{@code required} 不置 false：留痕是**必须发生**的事（不是可选的优化触发）——
     * 装配不上应当在启动期就失败，而不是在商家改单时静默丢掉审计。</p>
     */
    @Autowired
    private AuditLogService auditLogService;

    /**
     * 下单时的服务端定价（issue #7375 段 2）：价格本命中 ⇒ 以服务端为准 + 逐行留痕。
     * 只在请求带 SKU（或能按货号定位）时生效 ⇒ 存量调用零回归。
     */
    @Autowired(required = false)
    private OrderPricingService orderPricingService = OrderPricingService.NOOP;

    /**
     * 具名审批（issue #7374 段 1）：超授信下单被审批放行时，回填「这条审批用在哪」。
     * 可空注入（切片上下文 / 直接 new 的单测没有该 bean ⇒ 仅少一次回填，不影响下单）。
     */
    @Autowired(required = false)
    private ApprovalService approvalService;

    /**
     * 订单**查询族**（issue #8191，P2-1a）：列表 / 详情 / 统计 / 单号解析的唯一实现点。
     *
     * <p>本类只留<b>门面委托</b>（调用方零改动）。字段注入而非构造参数，理由同
     * {@link #stockBatchConsumptionService}：本类构造签名被多处测试显式装配，加参数会把它们全改一遍。</p>
     */
    @Autowired(required = false)
    private OrderQueryService orderQueryService;

    /**
     * 取查询服务：Spring 装配下 = 上面的 bean；**直接 new / {@code @InjectMocks} 的既有单测**
     * （Mockito 只做构造注入、不注入字段）没有该 bean ⇒ 用本类已装配的协作者就地构造一个
     * （同一份 Mapper / ObjectMapper 实例）⇒ 行为与拆分前逐字一致。
     */
    private OrderQueryService queryService() {
        OrderQueryService service = this.orderQueryService;
        if (service == null) {
            service = new OrderQueryService(orderMapper, orderItemMapper, orderLogisticsMapper,
                    productMapper, productSkuMapper, objectMapper, printLogMapper, businessClock);
            this.orderQueryService = service;
        }
        return service;
    }

    /**
     * 订单**创建族**（issue #8191，P2-1b）：建单编排（{@code createOrder} / {@code createOrderForAgent}）
     * 与 Agent 取价守卫的唯一实现点。
     *
     * <p>本类只留<b>门面委托</b>（调用方零改动）。字段注入而非构造参数，理由同
     * {@link #stockBatchConsumptionService}：本类构造签名被多处测试显式装配，加参数会把它们全改一遍。</p>
     */
    @Autowired(required = false)
    private OrderCreationService orderCreationService;

    /**
     * 取创建服务：Spring 装配下 = 上面的 bean；**直接 new / {@code @InjectMocks} 的既有单测**
     * （Mockito 只做构造注入、不注入字段）没有该 bean ⇒ 用本类已装配的协作者就地构造一个
     * （同一份 Mapper / Service 实例）⇒ 行为与拆分前逐字一致。
     */
    private OrderCreationService creationService() {
        OrderCreationService service = this.orderCreationService;
        if (service == null) {
            service = new OrderCreationService(orderMapper, productMapper, productSkuMapper,
                    customerService, userService, notificationService, clientRequestIdService,
                    orderPricingService, approvalService, queryService());
            this.orderCreationService = service;
        }
        return service;
    }

    /**
     * 订单**库存与销量族**（issue #8191，P2-1c）：库存前置校验 / 扣减 / 回补 / SKU 定位的唯一实现点。
     *
     * <p>本类只留<b>门面委托</b>（调用方零改动）。字段注入而非构造参数，理由同
     * {@link #stockBatchConsumptionService}：本类构造签名被多处测试显式装配，加参数会把它们全改一遍。</p>
     */
    @Autowired(required = false)
    private OrderStockService orderStockService;

    /**
     * 取库存服务：Spring 装配下 = 上面的 bean；**直接 new / {@code @InjectMocks} 的既有单测**
     * （Mockito 只做构造注入、不注入字段）没有该 bean ⇒ 用本类已装配的协作者就地构造一个
     * （同一份 Mapper / Service 实例）⇒ 行为与拆分前逐字一致。
     */
    private OrderStockService stockService() {
        OrderStockService service = this.orderStockService;
        if (service == null) {
            service = new OrderStockService(orderMapper, orderItemMapper, productMapper,
                    productSkuMapper, stockLedgerService);
            this.orderStockService = service;
        }
        return service;
    }

    /**
     * 订单**财务流水族**（issue #8191，P2-1c）：实收取数 / 收款退款流水登记 / 流水号生成的唯一实现点。
     *
     * <p>本类只留<b>门面委托</b>（调用方零改动）。字段注入而非构造参数，理由同上。</p>
     */
    @Autowired(required = false)
    private OrderFeeSupport orderFeeSupport;

    /**
     * 取财务流水服务：Spring 装配下 = 上面的 bean；**直接 new / {@code @InjectMocks} 的既有单测**
     * 没有该 bean ⇒ 用本类已装配的协作者就地构造一个（同一份 Mapper / 时钟实例）
     * ⇒ 行为与拆分前逐字一致。
     */
    private OrderFeeSupport feeSupport() {
        OrderFeeSupport service = this.orderFeeSupport;
        if (service == null) {
            service = new OrderFeeSupport(financeTransactionMapper, businessClock);
            this.orderFeeSupport = service;
        }
        return service;
    }

    /**
     * 订单**生命周期族**（issue #8191，P2-1d）：取消 / 退款 / 发货 / 状态流转的唯一实现点。
     *
     * <p>本类只留<b>门面委托</b>（公开签名与调用方零改动）。字段注入而非构造参数，理由同
     * {@link #stockBatchConsumptionService}：本类构造签名被多处测试显式装配，加参数会把它们全改一遍。</p>
     */
    @Autowired(required = false)
    private OrderLifecycleService orderLifecycleService;

    /**
     * 取生命周期服务：Spring 装配下 = 上面的 bean；**直接 new / {@code @InjectMocks} 的既有单测**
     * 没有该 bean ⇒ 用本类已装配的协作者就地构造一个（同一份 Mapper / 服务 / 时钟实例，
     * 并把测试改写过的可选协作者一并带过去）⇒ 行为与拆分前逐字一致。
     */
    private OrderLifecycleService lifecycleService() {
        OrderLifecycleService service = this.orderLifecycleService;
        if (service == null) {
            service = new OrderLifecycleService(orderMapper, orderItemMapper, orderLogisticsMapper,
                    processingOrderMapper, objectMapper, notificationService, userService,
                    stockService(), feeSupport(), businessClock);
            service.adoptOptionalCollaborators(poolChangeNotifier, documentOperationLinkage);
            this.orderLifecycleService = service;
        }
        return service;
    }

    /**
     * <b>测试探针</b>（issue #6955，生产恒为 {@code 0}）：转发到 {@link OrderLifecycleService} 的同名探针
     * —— 探针的注入点与观察点都随 {@code cancelOrder} 搬到实现点（issue #8191，P2-1d）。
     *
     * <p>门面上的这三个入口**逐字保留**（包内可见）：既有真实 DB 判据
     * {@code ProcessingOrderStatusCasRaceRealDbTest} 仍按 {@code OrderService.xxx} 引用它 ⇒ 调用点零改动。</p>
     */
    static void setCancelOrderPoProbePauseMillisForTest(long millis) {
        OrderLifecycleService.setCancelOrderPoProbePauseMillisForTest(millis);
    }

    /** 测试观察点：转发到实现点（见上）。 */
    static boolean cancelOrderPoProbePausedForTest() {
        return OrderLifecycleService.cancelOrderPoProbePausedForTest();
    }

    /** 测试观察点：转发到实现点（见上）。 */
    static long cancelOrderPoProbeMillisForTest() {
        return OrderLifecycleService.cancelOrderPoProbeMillisForTest();
    }

    /**
     * 订单号序列号（线程安全）
     */
    private static final AtomicInteger ORDER_SEQ = new AtomicInteger(0);

    /**
     * 合法的状态流转定义
     * key: 当前状态, value: 允许流转到的目标状态集合
     */
    private static final Map<String, Set<String>> STATUS_TRANSITIONS =
            OrderStatusTransitions.STATUS_TRANSITIONS;

    /**
     * 订单状态 → 中文业务术语（错误消息用）—— 仍是 {@link OrderStatusTransitions#ORDER_STATUS_LABELS}
     * 的**同一对象**（issue #8198 的「唯一取值载体」）。
     *
     * <p>issue #8191（P2-1d）后本类的使用点随状态流转族搬到 {@link OrderLifecycleService}（那边另有
     * 一个同样的别名，指向**同一个** Map）；本字段**有意保留**：判据
     * {@code OrderStatusTransitionsTest.stateMachineHasASingleImplementation} 逐对象核对它，
     * 删掉它 = 把「唯一实现点」那条判据的前提一起删掉。</p>
     */
    private static final Map<String, String> ORDER_STATUS_LABELS =
            OrderStatusTransitions.ORDER_STATUS_LABELS;

    /**
     * 手机号回填绑定：把「该手机号下 user_id 为空的本租户订单」绑定到指定用户。
     *
     * 场景：小程序客户授权绑定手机号后，商户代录/历史订单（仅存 customer_phone、
     * user_id 为空）据此归属到本人——V23 回填 SQL 的运行时等价物。
     * 防误绑：只更新 user_id IS NULL 的订单（已归属他人的不动）；tenant 由
     * TenantLineInnerInterceptor 自动注入。
     *
     * @param tenantId 租户ID
     * @param userId   当前用户ID
     * @param phone    用户刚绑定（且校验过未被同租户其他用户占用）的手机号
     * @return 受影响行数
     */
    public int bindOrdersToUser(Long tenantId, String userId, String phone) {
        if (!StringUtils.hasText(phone) || phone.isBlank()) {
            log.info("[bind-orders] 跳过：手机号为空 tenantId={}", tenantId);
            return 0;
        }
        if (userId == null || userId.isBlank() || "internal-service".equals(userId)) {
            log.info("[bind-orders] 跳过：用户标识缺失 tenantId={}", tenantId);
            return 0;
        }
        LambdaUpdateWrapper<Order> wrapper = new LambdaUpdateWrapper<>();
        wrapper.isNull(Order::getUserId)
                .eq(Order::getCustomerPhone, phone.trim())
                .set(Order::getUserId, userId);
        int updated = orderMapper.update(null, wrapper);
        log.info("[bind-orders] 手机号回填完成: tenantId={}, userId={}, phone={}****, bound={}",
                tenantId, userId, phone.substring(0, 3), updated);
        return updated;
    }

    /**
     * 创建订单（issue #8191，P2-1b）：实现点在 {@link OrderCreationService}，本方法只留门面委托（调用方零改动）。
     *
     * <p>事务注解随方法体搬到新服务（{@code @Transactional} 逐字跟随，边界不变）；本类把建单与改单共用的
     * 明细装配 / 取价 / 库存前置（唯一实现点，见类注释）经 {@code this} 交给新服务复用。</p>
     */
    public OrderDetailResponse createOrder(OrderCreateRequest request, Long tenantId) {
        return creationService().createOrder(request, tenantId, this);
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
     * 编辑请求的明细 → 建单行类型（**共用下游所有写面部件**的前提）。
     *
     * <p>为什么不给编辑另造一套行类型：加工项取价 / 行要素物化 / 整卷分配 / 库存校验全部以
     * {@code OrderCreateRequest.OrderItemRequest} 为输入 —— 另造一套就要把这些部件复制一遍
     * （issue #5842 的口径是「加工项写侧与建单**同源**」）。</p>
     *
     * <p>{@code subtotal} 在此**由服务端算出**（编辑 DTO 没有该字段）⇒
     * {@code resolveItemSubtotal} 拿到的一定是服务端值，客户端无从影响。</p>
     */
    private List<OrderCreateRequest.OrderItemRequest> toCreateItems(List<OrderContentUpdateRequest.Item> items) {
        List<OrderCreateRequest.OrderItemRequest> result = new ArrayList<>(items.size());
        for (OrderContentUpdateRequest.Item source : items) {
            OrderCreateRequest.OrderItemRequest target = new OrderCreateRequest.OrderItemRequest();
            target.setProductId(source.getProductId());
            target.setProductName(source.getProductName());
            target.setQuantity(source.getQuantity());
            target.setUnitPrice(source.getUnitPrice());
            target.setWidth(source.getWidth());
            target.setHeight(source.getHeight());
            target.setProcessingInfo(source.getProcessingInfo());
            // 安装位置（issue #7856）：改单请求的**件级**字段同样接到建单行类型上 ——
            // 下游写面只有一份（persistOrderItems），两处各搬一遍迟早分叉。
            target.setInstallRoom(source.getInstallRoom());
            target.setSellingMethod(source.getSellingMethod());
            if (source.getUnitPrice() != null && source.getQuantity() != null) {
                target.setSubtotal(source.getUnitPrice().multiply(source.getQuantity()));
            }
            result.add(target);
        }
        return result;
    }

    /**
     * 编辑请求的明细 → 库存校验用的**草稿明细**（不落库；与建单的 {@code validateStockSufficientForRequest}
     * 同一形状 —— 只带 SKU 匹配需要的三样：productId / productName / quantity / processingInfo）。
     */
    private List<OrderItem> draftItems(List<OrderCreateRequest.OrderItemRequest> items) {
        List<OrderItem> draftItems = new ArrayList<>(items.size());
        for (OrderCreateRequest.OrderItemRequest itemRequest : items) {
            OrderItem draft = new OrderItem();
            draft.setProductId(itemRequest.getProductId());
            draft.setProductName(itemRequest.getProductName());
            draft.setQuantity(itemRequest.getQuantity());
            draft.setProcessingInfo(itemRequest.getProcessingInfo());
            draftItems.add(draft);
        }
        return draftItems;
    }

    /**
     * 订单内容快照（**审计留痕**的前后差异载体，issue #5842）。
     *
     * <p>只记「人可复核、且改动会影响下游」的字段：收货三件套 / 三个金额 / 逐行
     * 商品名 + 数量 + 单价 + 宽高 + **加工项名**。刻意不整对象序列化 —— 审计读面是给人看的，
     * 倒进整个实体只会让真正的差异被淹没。</p>
     */
    private Map<String, Object> contentSnapshot(Order order, List<OrderItem> items) {
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("customerName", order.getCustomerName());
        snapshot.put("customerPhone", order.getCustomerPhone());
        snapshot.put("customerAddress", order.getCustomerAddress());
        snapshot.put("totalAmount", order.getTotalAmount());
        snapshot.put("discountAmount", order.getDiscountAmount());
        snapshot.put("actualAmount", order.getActualAmount());
        List<Map<String, Object>> lines = new ArrayList<>();
        for (OrderItem item : items) {
            Map<String, Object> line = new LinkedHashMap<>();
            line.put("productName", item.getProductName());
            line.put("quantity", item.getQuantity());
            line.put("unitPrice", item.getUnitPrice());
            line.put("width", item.getWidth());
            line.put("height", item.getHeight());
            line.put("processingItems", OrderShipGuard.extractProcessingItems(objectMapper, item.getProcessingInfo())
                    .stream().map(OrderDetailResponse.ProcessingItemBrief::getName).collect(Collectors.toList()));
            lines.add(line);
        }
        snapshot.put("items", lines);
        return snapshot;
    }

    /**
     * **待付款订单内容编辑**（issue #5842；用户 2026-10-01 裁定「范围 = 全改」）。
     *
     * <p>可改三面：收货信息 / 商品明细（商品·数量·单价·宽高）/ 加工项；金额**一律服务端重算**。</p>
     *
     * <h3>六道判据（缺一条都会静默出错）</h3>
     * <ol>
     *   <li><b>状态闸门</b>：只有 {@code pending} 可改，其余 **422** —— 判定走
     *       {@link OrderStatusTransitions#assertContentEditable}（状态机唯一实现点）；</li>
     *   <li><b>已有加工单 ⇒ 拒绝</b>：内容已固化进加工单快照，改订单会让快照漂移。
     *       （发货侧还有第二道 —— {@link OrderShipGuard#hasProcessingDrift} —— 两处都留，
     *       因为"编辑与生成不会同时发生"是一个**没有判据的时序假设**。）</li>
     *   <li><b>金额重算</b>：{@code totalAmount} 由服务端按新明细 + 新加工项重算
     *       （{@link #computeItemsTotal}），随后照建单同口径校验
     *       「应收 − 优惠 ≈ 实收（容差 0.01）」；</li>
     *   <li><b>库存前置校验按新明细重跑</b>（{@code validateStockSufficientForItems}，与确认支付同一套
     *       SKU 匹配）：{@code pending} 单**尚未扣库存**（扣减发生在确认支付）⇒
     *       <b>不回滚库存</b>，但必须保证「改完仍买得起」；</li>
     *   <li><b>明细整体替换</b>：旧行软删（{@code @TableLogic}）+ 新行落库，落库走与建单**同一份**
     *       {@link #persistOrderItems}；</li>
     *   <li><b>审计留痕</b>：前后快照（{@link #contentSnapshot}）写 {@code audit_logs}
     *       （{@code action=update_content} / {@code resourceType=order}）。</li>
     * </ol>
     *
     * <p>⚠️ <b>不回滚库存这件事的前提**在本方法内被显式保证**</b>：状态闸门只放 {@code pending}，
     * 而扣减只发生在 {@code pending → confirmed}（{@link #confirmPayment}）⇒ 走到这里时该单一定没扣过。
     * 若将来放宽可编辑状态，回滚/重算库存必须同批补上（本注释就是那件事的坐标）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public OrderDetailResponse updatePendingOrderContent(String id, OrderContentUpdateRequest request) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        Long tenantId = order.getTenantId();
        // ① 状态闸门（唯一实现点 = OrderStatusTransitions；其余状态一律 422 + 中文文案）
        OrderStatusTransitions.assertContentEditable(order.getStatus());
        // ② 已生成活跃加工单 ⇒ 内容已固化进快照，拒绝（发货侧另有漂移守卫兜底）
        ProcessingOrder active = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        if (active != null) {
            throw BusinessException.validationError(String.format(
                    "订单已生成加工单（%s），内容不能再修改；如需改内容请先作废该加工单",
                    active.getProcessingOrderNo()));
        }

        // ③ 新明细：服务端闸门 → 加工费取价 → 总额重算（**不信客户端任何金额**）
        List<OrderCreateRequest.OrderItemRequest> items = toCreateItems(request.getItems());
        assertItemAmountsValid(items);
        List<ProcessingFeeCalculator.Fee> itemFees = priceItems(items, tenantId);
        // 金额精度准入（issue #6228）：总额是计算值（"积"），合法单价×合法数量仍可出 3 位小数。
        BigDecimal totalAmount = MoneyScale.requireTwoDecimalsOrNull(computeItemsTotal(items, itemFees), "订单总额");
        syncProcessingFeeCombinations(itemFees, tenantId);

        // ④ 优惠 / 实收：未传 ⇒ **沿用原值**（不清零、不猜）；随后照建单同口径校验
        // 金额精度准入（issue #6228）：只有**请求带来的**值需要准入 —— 沿用值来自库列 NUMERIC(10,2) 回读。
        BigDecimal requestedDiscount = MoneyScale.requireTwoDecimalsOrNull(request.getDiscountAmount(), "优惠金额");
        BigDecimal discountAmount = requestedDiscount != null
                ? requestedDiscount
                : (order.getDiscountAmount() != null ? order.getDiscountAmount() : BigDecimal.ZERO);
        if (discountAmount.compareTo(BigDecimal.ZERO) < 0) {
            throw BusinessException.validationError("优惠金额不能为负数");
        }
        BigDecimal requestedActual = MoneyScale.requireTwoDecimalsOrNull(request.getActualAmount(), "实收金额");
        BigDecimal actualAmount = requestedActual != null
                ? requestedActual
                : (order.getActualAmount() != null
                        ? order.getActualAmount()
                        : totalAmount.subtract(discountAmount));
        BigDecimal expected = totalAmount.subtract(discountAmount);
        if (expected.subtract(actualAmount).abs().compareTo(new BigDecimal("0.01")) > 0) {
            throw BusinessException.validationError(String.format(
                    "实收金额与应收不一致：应收 %s - 优惠 %s = %s，实收 %s（容差 0.01）",
                    totalAmount, discountAmount, expected, actualAmount));
        }

        // ⑤ 前置库存校验**按新明细重跑**（与建单/确认支付共用 validateStockSufficientForItems）。
        //    `pending` 未扣库存 ⇒ 无需回滚，但"改完还买得起"必须现在成立。
        validateStockSufficientForItems(draftItems(items), "修改订单");

        // ⑥ 审计留痕：改动前快照（下一行起 order 对象就被就地改写了）
        //   明细取一次复用：「安装小区」的「未传 = 沿用原值」要靠改动前的行（见下方 ⑧）。
        List<OrderItem> existingItems = loadOrderItems(order.getId(), tenantId);
        Map<String, Object> before = contentSnapshot(order, existingItems);
        // 安装信息（issue #7856）：归一 + 准入同样**在任何写之前**（⑦ 的订单更新 / ⑧ 的明细替换都不落半成品）
        String installCommunity = resolveUpdatedInstallCommunity(request.getInstallCommunity(), existingItems);
        normalizeInstallRooms(items);

        // ⑦ 落库：收货信息 + 三金额
        orderMapper.update(null, new LambdaUpdateWrapper<Order>()
                .eq(Order::getId, order.getId())
                .set(Order::getCustomerName, request.getCustomerName())
                .set(Order::getCustomerPhone, request.getCustomerPhone())
                .set(Order::getCustomerAddress, request.getCustomerAddress())
                .set(Order::getTotalAmount, totalAmount)
                .set(Order::getDiscountAmount, discountAmount)
                .set(Order::getActualAmount, actualAmount));

        // ⑧ 明细整体替换：旧行**软删**（@TableLogic）后按新明细落库（与建单同一份 persistOrderItems）
        orderItemMapper.delete(new LambdaQueryWrapper<OrderItem>().eq(OrderItem::getOrderId, order.getId()));
        // 改单路径不做服务端定价（改价属于 P1-2 审批面）：传 null ⇒ 不写定价依据列
        // 安装小区（issue #7856）：**未传 ⇒ 沿用原值**（改动前明细第一条非空），传空串 ⇒ 清空；
        // 与 discountAmount / actualAmount 的「未传 = 不改、不猜、不清零」同一口径
        // （明细被**整体替换** ⇒ 不沿用就会在「只想改收货地址」时静默抹掉安装小区）。
        persistOrderItems(order, items, itemFees, tenantId, null, installCommunity);

        recordContentEditAudit(order, before,
                contentSnapshot(orderMapper.selectById(order.getId()), loadOrderItems(order.getId(), tenantId)));
        log.info("订单内容已修改: id={}, orderNo={}, totalAmount={}, 明细 {} 行",
                order.getId(), order.getOrderNo(), totalAmount, items.size());
        return queryService().getOrderById(order.getId());
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
     * 内容更新时「安装小区」的取值（issue #7856）。
     *
     * <p>{@code null}（未传）⇒ **沿用原值**（改动前明细第一条非空）；空白 ⇒ **清空**；
     * 其余 ⇒ 归一 + 准入（≤40 字，超长 422）。与 {@code discountAmount} / {@code actualAmount}
     * 的「未传 = 不改」同一口径 —— 明细是**整体替换**，不沿用就会在「只改收货地址」时静默抹掉安装小区。</p>
     */
    private String resolveUpdatedInstallCommunity(String requested, List<OrderItem> existingItems) {
        if (requested == null) {
            return OrderInstallInfo.firstCommunity(existingItems, objectMapper);
        }
        return OrderInstallInfo.normalizeCommunity(requested);
    }

    /**
     * 内容编辑的审计留痕（issue #5842）：{@code action=update_content} / {@code resourceType=order}
     * + **前后差异**。操作者取不到（无认证 / 服务占位身份）⇒ 两个身份字段留空，
     * 但**留痕本身照写**（审计的意义是"改过"，不是"谁改的"都有答案 —— 后者留空可见）。
     */
    private void recordContentEditAudit(Order order, Map<String, Object> before, Map<String, Object> after) {
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("before", before);
        details.put("after", after);
        Long tenantId = order.getTenantId();
        UserService.CurrentOperator operator = userService.resolveCurrentOperator();
        auditLogService.recordLog(tenantId,
                operator != null ? operator.userId() : null,
                operator != null ? operator.displayName() : null,
                "update_content", "order", null,
                order.getId(), order.getOrderNo(), details, null, null);
    }

    /**
     * 更新订单状态（issue #8191，P2-1d）：实现点已搬到 {@link OrderLifecycleService}，本方法只留门面委托。
     */
    public void updateOrderStatus(String id, String status) {
        lifecycleService().updateOrderStatus(id, status, this);
    }

    /**
     * 删除订单（逻辑删除，仅允许待确认状态）
     *
     * @param id 订单ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteOrder(String id) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }

        // 仅允许待确认状态的订单被删除
        if (!OrderStatusTransitions.PENDING.equals(order.getStatus())) {
            throw BusinessException.validationError("仅允许删除待确认状态的订单，当前状态: " + order.getStatus());
        }

        // issue #7633：已生成**活跃作业单** ⇒ 拒绝删除，否则作业单悬挂、作业看板对已删父订单扇出 404。
        // 口径与 updatePendingOrderContent 同源（同一 selectActiveByOrderId：未软删 + 非 cancelled + 同租户）；
        // 待付款订单自 #7626 起也能先生成作业单 ⇒ 这道闸是「删单前必须先作废作业单」。
        // 订单**不做物理删除**（deleteById 走 @TableLogic 软删，语义未改）；本闸只给出口、不给旁路。
        ProcessingOrder active = processingOrderMapper.selectActiveByOrderId(order.getId(), order.getTenantId());
        if (active != null) {
            throw BusinessException.validationError(String.format(
                    "订单已生成作业单（%s），不能删除；请先作废该作业单", active.getProcessingOrderNo()));
        }

        // 逻辑删除订单
        // issue #6956 · 现象 C：判影响行数（并发双删只许一次成功；0 行 = 已被别人删掉）
        if (orderMapper.deleteById(id) == 0) {
            throw BusinessException.notFound("订单");
        }

        // 逻辑删除订单明细
        LambdaQueryWrapper<OrderItem> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(OrderItem::getOrderId, id);
        List<OrderItem> items = orderItemMapper.selectList(wrapper);
        for (OrderItem item : items) {
            orderItemMapper.deleteById(item.getId());
        }

        log.info("删除订单成功: id={}, orderNo={}", id, order.getOrderNo());
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
     * 该订单是否含加工项（订单明细的 {@code processing_info} 非空）。
     *
     * <p><b>这是「含加工项」的唯一一份判据</b>（issue #3340 的发货守卫与 issue #5641 的生产待办
     * 都读它）—— 自己再写一份 {@code extractProcessingItems} 调用就会是两处口径。</p>
     *
     * <p>必须走 BaseMapper 加载（见 {@link #loadOrderItems}）：自定义 {@code @Select} 不经过
     * {@code JacksonTypeHandler}，{@code processing_info} 会以 JSON <b>字符串</b>返回 ⇒ 加工项解析
     * 恒为空 ⇒ 判据静默失效（issue #3340 验收实战：真实对话生成加工单被判「无加工项」）。</p>
     */
    public boolean hasProcessingItems(Order order) {
        // #5648 合并后：本体在 OrderShipGuard（单一实现点），本方法只做参数搬运。
        return OrderShipGuard.hasProcessingItems(orderItemMapper, objectMapper, order);
    }

    /**
     * 该订单是否**有需要报工的作业**（issue #7079）= 含加工项 **或** 有卖布行。
     *
     * <p>卖布单（{@code processing_info.saleForm = 布料}）按米卖布、行上**没有加工项**，
     * 但它仍要经过「裁剪 → 打包」两道工序并给工人报工计件 ⇒ 只读 {@link #hasProcessingItems}
     * 会把它判成「无需报工」。生产待办的「待排产」/「待发货」两处过滤读本方法
     * （与发货守卫 {@link #isProcessingReadyForShip} 同一份判据）。</p>
     *
     * <p>本体在 {@code OrderShipGuard.needsWork}（单一实现点），本方法只做参数搬运 ——
     * 同 {@link #hasProcessingItems} 的范式。</p>
     */
    public boolean needsWork(Order order) {
        return OrderShipGuard.needsWork(orderItemMapper, objectMapper, order);
    }

    /**
     * 加载订单明细（走 BaseMapper，确保 processing_info 经 JacksonTypeHandler 反序列化为 Map）。
     * 与 getOrderById 的既有约定一致（见查询明细处的注释）。
     */
    private List<OrderItem> loadOrderItems(String orderId, Long tenantId) {
        return OrderShipGuard.loadOrderItems(orderItemMapper, orderId, tenantId);
    }

    /**
     * 加工单取消联动（issue #8191，P2-1d）：实现点已搬到 {@link OrderLifecycleService}，本方法只留门面委托。
     */
    public void revertProducingToConfirmed(String orderId, String reason) {
        lifecycleService().revertProducingToConfirmed(orderId, reason);
    }

    private BigDecimal toBigDecimal(Object value) {
        return OrderShipGuard.toBigDecimal(value);
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
     * SKU 身份兜底（issue #7219）—— **纯函数**，判据见 {@code OrderServiceSkuBackfillTest}。
     *
     * <p>口径：① 两个键都有 ⇒ 原样返回（**不覆盖**既有快照）；② {@code skuId} 命中 ⇒ 用那个 SKU；
     * ③ 没有 skuId 但商品**只有一个 SKU** ⇒ 用唯一 SKU；④ 多 SKU 且产品名以
     * {@code -颜色-门幅} 结尾、**唯一命中**一个 SKU ⇒ 用它（历史/回归单的既有命名形态）；
     * ⑤ 其余（无法唯一判定）⇒ 原样返回，**不猜**（猜错比空更贵：纸面会把 A 的颜色印到 B 的行上）。
     * 只补**缺的那一半**。</p>
     */
    static Map<String, Object> backfillSkuIdentity(Map<String, Object> info, List<ProductSku> skus, String productName) {
        // 口径单点在 OrderQueryService（issue #8191，P2-1a）；本留静态入口因为既有单测按 OrderService.backfillSkuIdentity 引用。
        return OrderQueryService.backfillSkuIdentity(info, skus, productName);
    }

    // ==================== 订单统计与跟进状态 ====================

    /**
     * 获取订单统计（使用 COUNT 查询，避免全量加载到内存）
     */
    public OrderStatisticsResponse getOrderStatistics(Long tenantId) {
        long total = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId));
        long pending = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, OrderStatusTransitions.PENDING));
        long confirmed = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, OrderStatusTransitions.CONFIRMED));
        long producing = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, OrderStatusTransitions.PRODUCING));
        long shipped = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, OrderStatusTransitions.SHIPPED));
        long completed = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, OrderStatusTransitions.COMPLETED));
        long cancelled = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, OrderStatusTransitions.CANCELLED));

        return OrderStatisticsResponse.builder()
                .totalCount(total)
                .pendingCount(pending)
                .confirmedCount(confirmed)
                .producingCount(producing)
                .shippedCount(shipped)
                .completedCount(completed)
                .cancelledCount(cancelled)
                .unpaidCount(pending)
                .paidCount(confirmed + producing + shipped + completed)
                .refundedCount(cancelled) // 退款订单即已取消的订单
                .build();
    }

    /**
     * 获取跟进状态统计（使用 COUNT 查询，避免全量加载到内存）
     */
    public FollowStatusStatsResponse getFollowStatusStats(Long tenantId) {
        long total = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId));
        long following = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getFollowStatus, "following"));
        long completedFollow = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getFollowStatus, "completed"));
        // pending = total - following - completed（含 null 值）
        long pendingFollow = total - following - completedFollow;

        return FollowStatusStatsResponse.builder()
                .pending(pendingFollow)
                .following(following)
                .completed(completedFollow)
                .total(total)
                .build();
    }

    /**
     * 确认支付（issue #8191，P2-1d）：实现点已搬到 {@link OrderLifecycleService}，本方法只留门面委托。
     */
    public void confirmPayment(String id) {
        lifecycleService().confirmPayment(id);
    }

    /**
     * validateStockSufficientForRequest（issue #8191，P2-1c）：实现点已搬到 {@link StockService}，本方法只留门面委托。
     */
    void validateStockSufficientForRequest(OrderCreateRequest request, String actionLabel) {
        stockService().validateStockSufficientForRequest(request, actionLabel);
    }

    /**
     * validateStockSufficientForItems（issue #8191，P2-1c）：实现点已搬到 {@link StockService}，本方法只留门面委托。
     */
    private void validateStockSufficientForItems(List<OrderItem> items, String actionLabel) {
        stockService().validateStockSufficientForItems(items, actionLabel);
    }

    /**
     * 取消/关闭订单（issue #8191，P2-1d）：实现点已搬到 {@link OrderLifecycleService}，本方法只留门面委托。
     */
    public void cancelOrder(String id, String closeReason) {
        lifecycleService().cancelOrder(id, closeReason, this);
    }

    /**
     * 退款（issue #8191，P2-1d）：实现点已搬到 {@link OrderLifecycleService}，本方法只留门面委托。
     */
    public void refundOrder(String id, BigDecimal refundAmount, String refundReason) {
        lifecycleService().refundOrder(id, refundAmount, refundReason);
    }

    /**
     * 获取订单跟进状态
     */
    public FollowStatusResponse getFollowStatus(String id) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        return FollowStatusResponse.builder()
                .orderId(id)
                .followStatus(order.getFollowStatus() != null ? order.getFollowStatus() : "pending")
                .updatedAt(order.getUpdatedAt())
                .build();
    }

    /**
     * 更新跟进状态
     */
    @Transactional(rollbackFor = Exception.class)
    public void updateFollowStatus(String id, String followStatus) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        Set<String> validStatuses = Set.of("pending", "following", "completed");
        if (!validStatuses.contains(followStatus)) {
            throw BusinessException.validationError("无效的跟进状态: " + followStatus + "，可选值: pending/following/completed");
        }
        // 🔴 只写本方法负责的列（issue #6955）：修前是 orderMapper.updateById(order) —— 整实体回写会把
        // selectById 时读到的**旧 status 一并写回** ⇒ 静默回滚并发的状态变更（F1 的类级根因）。
        orderMapper.update(null, new LambdaUpdateWrapper<Order>()
                .eq(Order::getId, order.getId())
                .set(Order::getFollowStatus, followStatus));
        log.info("更新跟进状态成功: id={}, followStatus={}", id, followStatus);
    }

    /**
     * 更新订单级**加急标记 / 客户要求到货日**（V120，issue #5177 的「改单」半边）。
     *
     * <h2>三态语义（与 {@link OrderUrgencyUpdateRequest} 逐字同源，不在两处各写一份）</h2>
     * 每个字段各自「不传 = 不改」；{@code requiredDeliveryDate} 传**空串**才表示清空
     * （{@code null} 与 {@code ""} 必须是两件事，否则「只改加急」会把到货日静默抹掉）。
     *
     * <h2>为什么用 {@code LambdaUpdateWrapper} 而不是 {@code updateById(order)}</h2>
     * 本仓既有的改单写法是「{@code selectById} → 改实体 → {@code updateById(order)}」，但
     * MyBatis-Plus 默认字段策略是 {@code NOT_NULL} ⇒ **null 字段不进 SET** ⇒ 用那条路
     * **永远清不掉**到货日（「清空」会静默变成「不改」，而界面显示已清空）。
     * ⇒ 清空必须走显式 {@code set(col, null)}；{@code updatedAt} 也随之**显式**写
     * （{@code update(entity, wrapper)} 的自动填充不在本路径上，不写它就留下陈旧时间戳）。
     *
     * <p>🔴 <b>只写这两列</b>：不碰金额、状态、售后工单的任何字段
     * （判据 1 零联动 / 判据 6 不损失客户）。</p>
     *
     * @param isUrgent                  {@code null} = 不改；否则显式设值（{@code false} 是「取消加急」的真值）
     * @param requiredDeliveryDateRaw   {@code null} = 不改；{@code ""} = 清空；{@code YYYY-MM-DD} = 设值；其它 ⇒ 422
     */
    @Transactional(rollbackFor = Exception.class)
    public void updateUrgency(String id, Boolean isUrgent, Boolean isOutsourced,
                              String requiredDeliveryDateRaw) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        LambdaUpdateWrapper<Order> update = new LambdaUpdateWrapper<Order>().eq(Order::getId, id);
        boolean changed = false;
        if (isUrgent != null) {
            update.set(Order::getIsUrgent, isUrgent);
            changed = true;
        }
        if (isOutsourced != null) {
            update.set(Order::getIsOutsourced, isOutsourced);
            changed = true;
        }
        if (requiredDeliveryDateRaw != null) {
            update.set(Order::getRequiredDeliveryDate, parseRequiredDeliveryDate(requiredDeliveryDateRaw));
            changed = true;
        }
        if (!changed) {
            // 两个字段都没传 ⇒ 这次改单什么都没改。**显式拒绝**而不是静默 200：
            // 静默成功会让调用方以为改动生效了（同族纪律：不静默）。
            throw BusinessException.validationError(
                    "isUrgent / isOutsourced / requiredDeliveryDate 至少要传一个（本次改单没有任何变更）");
        }
        update.set(Order::getUpdatedAt, OffsetDateTime.now());
        orderMapper.update(null, update);
        log.info("更新订单生产标记成功: id={}, isUrgent={}, isOutsourced={}, requiredDeliveryDate={}",
                id, isUrgent, isOutsourced, requiredDeliveryDateRaw);
        // 🔴 事件驱动自动成批（issue #5182 挂载点 ③-a）：改单会同时改两件事 ——
        // 加急单**永不入池**（改为加急 ⇒ 立刻单派）、到货日变了 ⇒ 兜底的「最晚派单日」跟着变。
        PoolChangeNotifier.notifySafely(poolChangeNotifier, order.getTenantId(),
                PoolChangeNotifier.TRIGGER_ORDER_UPDATED);
    }

    /**
     * 到货日解析（issue #5177）：{@code ""} ⇒ **清空**（返回 {@code null}）；
     * {@code YYYY-MM-DD} ⇒ 该日期；其它形态 ⇒ **显式拒绝**（不静默回落、不当成清空）。
     *
     * <p>为什么空白串不按「清空」办：{@code "  "} 这种输入更像**误输入**，把它当清空
     * 就是静默丢数据；而 {@code ""} 是调用方**明确**表达的「清空」（前端清空日期框发出的就是它）。</p>
     */
    private static LocalDate parseRequiredDeliveryDate(String raw) {
        if (raw.isEmpty()) {
            return null;
        }
        try {
            return LocalDate.parse(raw.trim(), DateTimeFormatter.ISO_LOCAL_DATE);
        } catch (DateTimeParseException e) {
            throw BusinessException.validationError(
                    "到货日格式不正确：" + raw + "（期望 YYYY-MM-DD，或传空串清空到货日）");
        }
    }

    /**
     * 添加订单备注（追加模式）
     *
     * @param id      订单ID
     * @param content 备注内容
     */
    @Transactional(rollbackFor = Exception.class)
    public void addRemark(String id, String content) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        if (content == null || content.isBlank()) {
            throw BusinessException.validationError("备注内容不能为空");
        }
        if (content.length() > 2000) {
            throw BusinessException.validationError("备注内容不能超过 2000 个字符");
        }
        String timestamp = businessClock.now()
                .format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"));
        String remarkEntry = "[" + timestamp + "] " + content;
        String existing = order.getRemark() != null ? order.getRemark() : "";
        String merged = existing.isEmpty() ? remarkEntry : existing + "\n" + remarkEntry;
        // 🔴 只写 remark（issue #6955）：修前是 orderMapper.updateById(order) —— 整实体回写会把
        // selectById 时读到的**旧 status 一并写回** ⇒ 静默回滚并发的状态变更（F1 的类级根因）。
        orderMapper.update(null, new LambdaUpdateWrapper<Order>()
                .eq(Order::getId, order.getId())
                .set(Order::getRemark, merged));
        log.info("添加订单备注成功: id={}", id);
    }

    /**
     * restoreStockForReturn（issue #8191，P2-1c）：实现点已搬到 {@link StockService}，本方法只留门面委托。
     */
    public void restoreStockForReturn(String orderId) {
        stockService().restoreStockForReturn(orderId);
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

    // ======================== Agent BFF 方法 ========================

    /**
     * Agent 专用创建订单（issue #8191，P2-1b）：实现点在 {@link OrderCreationService}，本方法只留门面委托。
     *
     * <p>幂等键 / 取价守卫 / 事务边界随方法体搬到新服务（逐字跟随）；调用方零改动。</p>
     */
    public OrderDetailResponse createOrderForAgent(AgentOrderCreateRequest request, Long tenantId) {
        return creationService().createOrderForAgent(request, tenantId, this);
    }

    /**
     * Agent 专用统一订单更新。
     * ID 可传 UUID 或订单号（ORD-xxx），服务端自动解析。
     * 通过 action 字段路由到具体的操作方法。
     */
    @Transactional(rollbackFor = Exception.class)
    public Object updateOrderForAgent(String rawId, AgentOrderUpdateRequest request, Long tenantId) {
        // 解析订单 ID
        String resolvedId = resolveOrderIdToUuid(rawId, tenantId);
        if (resolvedId == null) {
            throw new BusinessException("ORDER_NOT_FOUND",
                    "无法找到订单：" + rawId + "。请使用 order_query 查询正确的订单号后重试。", 404);
        }

        String action = request.getAction();
        if (!StringUtils.hasText(action)) {
            throw BusinessException.validationError("action 不能为空");
        }

        return switch (action) {
            case "update_status" -> {
                if (!StringUtils.hasText(request.getStatus())) {
                    throw BusinessException.validationError("status 不能为空");
                }
                updateOrderStatus(resolvedId, request.getStatus());
                yield queryService().getOrderById(resolvedId);
            }
            case "confirm_payment" -> {
                confirmPayment(resolvedId);
                yield queryService().getOrderById(resolvedId);
            }
            case "cancel" -> {
                cancelOrder(resolvedId, request.getCancelReason());
                yield queryService().getOrderById(resolvedId);
            }
            case "refund" -> {
                refundOrder(resolvedId, request.getRefundAmount(), request.getRefundReason());
                yield queryService().getOrderById(resolvedId);
            }
            case "update_logistics" -> {
                if (!StringUtils.hasText(request.getLogisticsCompany())) {
                    throw BusinessException.validationError("logisticsCompany 不能为空");
                }
                if (!StringUtils.hasText(request.getTrackingNumber())) {
                    throw BusinessException.validationError("trackingNumber 不能为空");
                }
                lifecycleService().upsertLogistics(resolvedId, request.getLogisticsCompany().trim(),
                        request.getTrackingNumber().trim(), null, request.getLogisticsType());
                // 发货语义：记录物流后将订单流转为 shipped（与契约 order_manage(update_logistics) 可发货一致）
                lifecycleService().shipOrderIfApplicable(resolvedId);
                yield queryService().getOrderById(resolvedId);
            }
            default -> throw BusinessException.validationError(
                    "不支持的操作类型: " + action + "，可选: update_status/update_logistics/confirm_payment/cancel/refund");
        };
    }

    /**
     * 发货（issue #8191，P2-1d）：实现点已搬到 {@link OrderLifecycleService}，本方法只留门面委托。
     * 公开类型 {@link OrderShipmentOutcome} 与签名**逐字保留**（调用方零改动）。
     */
    public OrderShipmentOutcome shipWithLogistics(String orderId, String trackingNo, String logisticsCompany) {
        return lifecycleService().shipWithLogistics(orderId, trackingNo, logisticsCompany);
    }

    /**
     * 发货（issue #8191，P2-1d）：实现点已搬到 {@link OrderLifecycleService}，本方法只留门面委托。
     */
    public OrderShipmentOutcome shipWithLogistics(String orderId, String trackingNo, String logisticsCompany,
                                                  OrderLogisticsWriter.ShippingDetails details) {
        return lifecycleService().shipWithLogistics(orderId, trackingNo, logisticsCompany, details);
    }

    /**
     * 商家/工人发货路的**结果 ＋ 本次是否真的发生了流转**（issue #6181）。
     *
     * <p>为什么要有第二个字段（而不是让调用方读结果快照里的 {@code status}）：那里的
     * {@code status} 是**文案常量**（本路对「补记物流」也回 {@code shipped}），它回答不了
     * 「这一步有没有发生状态变更」；而这一步的**下游**（建发货单）必须知道答案 —— 否则就会
     * 「订单本来就已发货」时凭空多建一张单，或用「订单状态」这个**会被自己写脏的谓词**去猜
     * （#6181 的根因形态）。</p>
     *
     * @param result       结果快照（幂等回放载体，进 {@code ClientRequestIdService}）
     * @param transitioned 本次调用是否真的把订单从 {@code confirmed|producing} 流转成 {@code shipped}；
     *                     {@code false} = 订单本来就已是 {@code shipped}（本路只补记/纠正物流）
     */
    public record OrderShipmentOutcome(Map<String, Object> result, boolean transitioned) {
    }

    /**
     * 订单 ID 解析：UUID 精确匹配 → 订单号匹配 → UUID 前缀匹配。
     *
     * @return 解析出的 UUID，未找到返回 null
     */
    private String resolveOrderIdToUuid(String raw, Long tenantId) {
        // 解析口径单点在 OrderQueryService（issue #8191，P2-1a）；本留私有入口给写入路径 updateOrderForAgent。
        return queryService().resolveOrderIdToUuid(raw, tenantId);
    }

    /**
     * 订单状态筛选：支持**逗号分隔多值**（issue #5792）。
     *
     * <p>为什么需要：前端「待发货」在业务上是 **`confirmed` + `producing`** 两个状态之和
     * （`frontend/admin-web/src/types/index.ts` 的映射注释已这么写），而后端此前只收单值
     * ⇒ 列表比计数少（看板卡说 N 条、点进去只看到其中一部分）。
     * 现按 `in` 处理 ⇒ 与计数的口径取齐（本仓同族缺陷的修法见 issue #5792 的口径整改）。</p>
     */
    static void applyStatusFilter(
            com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<com.migao.admin.entity.Order> wrapper,
            String status) {
        if (!StringUtils.hasText(status)) {
            return;
        }
        java.util.List<String> statuses = java.util.Arrays.stream(status.split(","))
                .map(String::trim)
                .filter(x -> !x.isEmpty())
                .distinct()
                .collect(java.util.stream.Collectors.toList());
        if (statuses.size() == 1) {
            wrapper.eq(com.migao.admin.entity.Order::getStatus, statuses.get(0));
        } else {
            wrapper.in(com.migao.admin.entity.Order::getStatus, statuses);
        }
    }
}
