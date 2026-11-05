package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.*;
import com.migao.admin.dto.agent.AgentOrderResolveResponse;
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
 * <p><b>门面委托的逐批退休（issue #8681，P2-1e）</b>：调用方迁到实现点之后，同名转发<b>删除</b>且不许回来
 * （看管见 {@code OrderFacadeForwarderRetirementTest}）。已退休：{@code existsForCurrentTenant} /
 * {@code resolveOrderId} / {@code isProcessingReadyForShip} / {@code resolveShipperName}（第一批）、
 * {@code getMyOrderPage}（第二批）、{@code getOrderPage} / {@code getOrderById}（第四批）、
 * {@code createOrder}（第五批：订单控制器直连 {@link OrderCreationService}，经 {@code this} 复用本类共享部件）、
 * 生命周期族 {@code updateOrderStatus} / {@code confirmPayment} / {@code cancelOrder} / {@code refundOrder} /
 * {@code shipWithLogistics}（两个重载）/ {@code revertProducingToConfirmed}（第六批：订单 / 生产控制器与
 * 加工单服务直连 {@link OrderLifecycleService}；门面不再声明这 7 个入口）、
 * 实体写面 {@code deleteOrder} / {@code addRemark} / {@code bindOrdersToUser} / {@code updateFollowStatus} /
 * {@code getFollowStatus} / {@code updateUrgency} / {@code updatePendingOrderContent}（第七批：订单控制器与
 * 小程序手机号绑定服务直连 {@link OrderEntityWriteService}；门面不再声明这 7 个入口，也不留这族的私有死委托）、
 * <b>Agent BFF</b>{@code createOrderForAgent} / {@code updateOrderForAgent} 与 {@code restoreStockForReturn}
 * （第八批：{@code createOrderForAgent} 由 Agent 订单控制器直连 {@link OrderCreationService}；
 * {@code updateOrderForAgent} 的编排实现体<b>整体搬到</b> {@link OrderAgentFacade}、事务注解逐字跟随；
 * 售后回补由 {@link AfterSalesTicketService} 直连 {@link OrderStockService}）。
 * 至此门面<b>不再声明任何转发</b>，只剩共享部件、两处判据（{@code hasProcessingItems} / {@code needsWork}）、
 * 状态常量表、{@code applyRollAllocation}（被 {@code OrderRollAllocationAuthorityTest} 钉死）与
 * {@code batchStock()} 访问器。</p>
 *
 * <p><b>行数</b>：1,142 → 1,057（第八批；<b>仍在 800–2,000 行的存量带内</b> ⇒ 尚未触发豁免台账销账）。
 * 目标 &lt; 500 的剩余部分是<b>共享部件族</b>（约 450 行）—— 它属<b>跨批设计决定</b>
 * （谁持有第三参、共享部件落在哪个服务），见 issue #8681 的下一批清单。</p>
 *
 * <p><b>包内可见的共享部件</b>（issue #8191，P2-1b）：建单与改单（{@code updatePendingOrderContent}）/
 * 确认支付共用同一份明细装配、取价、总额与库存前置校验（{@code assertItemAmountsValid} /
 * {@code priceItems} / {@code computeItemsTotal} / {@code persistOrderItems} /
 * {@code validateStockSufficientForRequest} / {@code generateOrderNo} 等）—— 它们是<b>唯一实现点</b>
 * （金额计算族 = P2-1c 的边界），故由 {@code private} 放宽为<b>包内可见</b>，供
 * {@link OrderCreationService} 与 {@link OrderEntityWriteService} 经门面传入的本类实例复用
 * （不产生第二份口径；两者的第三参都是门面实例，这是同一条既有口径）。</p>
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
     * <p>为什么这里必须有它：{@link OrderLifecycleService#cancelOrder} 对 {@code generated} 态加工单是**直接
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
    OrderQueryService queryService() {
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
    /**
     * 包内可见（issue #8681，P2-1e 第六批）：加工单服务要直连生命周期实现点，而它是**冻结面**
     * （{@code tests/unit_ci_workflows/loc_freeze_ledger.json} 的 4,402 行上限，一行都不许涨）
     * ⇒ 经本访问器取**同一份**实现点，不在那个文件里新增字段。
     */
    OrderLifecycleService lifecycleService() {
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
     * 订单**实体写面**（issue #8681，P2-1e 第七批）：删单 / 备注 / 手机号回填 / 跟进状态（读 + 写）/
     * 加急 / 待付款内容编辑的唯一实现点。
     *
     * <p>本类已<b>不再声明</b>这批入口（同名转发全部退休）；本访问器保留的唯一用途是
     * 「<b>取门面自己懒构造的那一份</b>」—— 既有单测（{@code @InjectMocks} / 直接 {@code new}）
     * 没有该 bean，通过它拿到的实例与拆分前是<b>同一条调用链、同一份协作者</b>
     * （Mapper / ObjectMapper / 业务时钟 / 测试改写过的可选协作者），断言因此可以一个字都不改。</p>
     */
    @Autowired(required = false)
    private OrderEntityWriteService orderEntityWriteService;

    OrderEntityWriteService entityWriteService() {
        OrderEntityWriteService service = this.orderEntityWriteService;
        if (service == null) {
            service = new OrderEntityWriteService(orderMapper, orderItemMapper, processingOrderMapper,
                    objectMapper, userService, auditLogService, businessClock);
            service.adoptOptionalCollaborators(poolChangeNotifier);
            this.orderEntityWriteService = service;
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
     * validateStockSufficientForRequest（issue #8191，P2-1c）：实现点已搬到 {@link StockService}，本方法只留门面委托。
     */
    void validateStockSufficientForRequest(OrderCreateRequest request, String actionLabel) {
        stockService().validateStockSufficientForRequest(request, actionLabel);
    }

    /**
     * validateStockSufficientForItems（issue #8191，P2-1c）：实现点已搬到 {@link StockService}，本方法只留门面委托。
     */
    void validateStockSufficientForItems(List<OrderItem> items, String actionLabel) {
        stockService().validateStockSufficientForItems(items, actionLabel);
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
