package com.migao.admin.service;

import com.migao.admin.dto.*;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.PrintLogMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.time.BusinessClock;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.Set;

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
 * 至此门面<b>不再声明任何转发</b>，只剩状态常量表与六处「手写 new 的单测取同一份实现点」的包内访问器。</p>
 *
 * <p><b>第九批（共享部件族收口，issue #8681 P2-1e）：</b>建单 / 改单 / Agent 三条写单路径共用的
 * 明细装配 · 取价 · 总额 · 加工费组合同步 · 库存前置 · 单号 · 定价留痕，以及整卷分配的私有步骤
 * （{@code applyRollAllocation} 一族）与 {@code batchStock()} 访问器，<b>整体搬到</b>
 * {@link OrderSharedParts}。⇒ 三个服务（建单 / 实体写面 / 生命周期）的**第三参从门面实例换成共享部件实例**，
 * 门面不再随调用链传播；「不许复制第二份」由 {@code OrderSharedPartsTest} 固化。
 * 整卷分配的权威点随之改由 {@code OrderRollAllocationAuthorityTest} 指向新承载文件（五条判据一字未改，
 * 只换载体常量 —— 这就是「载体搬家同批登记」）。</p>
 *
 * <p><b>行数</b>：1,142 → 1,065（第八批）→ 547（第九批）→ <b>454</b>（第十批 · 收尾，−93，**&lt; 500 判据达成**）。
 * 跌破 800 行的登记带时 {@code tests/unit_ci_workflows/loc_ratchet_exemptions.json} 里本文件的条目
 * 已在第九批<b>同批销账</b>；{@code loc_freeze_ledger.json} 里本文件从未有条目 ⇒ 本批无需再销账。</p>
 *
 * <p><b>第十批（收尾批，issue #8681 P2-1e）：&lt; 500 判据达成。</b>搬走两族：
 * ① 订单域<b>公共 API</b> {@code hasProcessingItems} / {@code needsWork}（生产待办逐字引用的那两个判据）
 * → {@link OrderQueryService}（读面：它本来就在 {@code getOrderDetail} 里算同一份判据）；
 * ② 列表<b>时间窗</b>与<b>状态筛选</b>（{@code DEFAULT_LOOKBACK_MONTHS} / {@code ListDateWindow} /
 * {@code resolveListWindow} / {@code applyStatusFilter}）→ 新建 {@link OrderListCriteria}
 * （唯一生产消费方是查询族；并进 {@link OrderQueryService} 会越过 800 行登记阈值）。</p>
 *
 * <p><b>有意不搬（判据强度不许降，不是「文件不许动」）</b>：① 状态常量表
 * {@code STATUS_TRANSITIONS} / {@code ORDER_STATUS_LABELS} —— 它们<b>只为一条权威判据而存在</b>
 * （{@code OrderStatusTransitionsTest.stateMachineHasASingleImplementation} 用反射
 * {@code OrderService.class.getDeclaredField(...)} 逐对象核对），删字段 = 把那条断言的对象一起删掉；
 * 那<b>不是载体搬家</b>（载体改名做不到，只能重写断言）⇒ 按集成侧裁定的「载体搬家三条」它属越界；
 * ② 六处包内访问器（{@code queryService()} 等）—— 手写 new 的既有单测靠它们取「同一份实现点」，
 * 现取 16 处 {@code ReflectionTestUtils.invokeMethod}；动它 = 改测试装配面，收益不抵风险。</p>
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
                    objectMapper, userService, auditLogService, businessClock, queryService());
            service.adoptOptionalCollaborators(poolChangeNotifier);
            this.orderEntityWriteService = service;
        }
        return service;
    }

    /**
     * 订单<b>共享部件族</b>（issue #8681，P2-1e 第九批）：建单 / 改单 / Agent 三条写单路径共用的
     * 明细装配 · 取价 · 总额 · 库存前置 · 单号 · 定价留痕的<b>唯一实现点</b>，见 {@link OrderSharedParts}。
     *
     * <p><b>它为什么是第三参</b>：{@link OrderCreationService} / {@link OrderEntityWriteService} /
     * {@link OrderLifecycleService} 此前吃的是<b>门面实例</b>（「把 OrderService 传进去、调它的共享部件」）
     * —— 那条口径让门面永远删不掉。换成共享部件实例之后，依赖面收窄成一个**不含门面**的组件，
     * 门面不再随调用链传播。</p>
     *
     * <p>字段注入而非构造参数，理由同 {@link #stockBatchConsumptionService}：本类构造签名被多处测试
     * 显式装配，加参数会把它们全改一遍。<b>直接 new / {@code @InjectMocks} 的既有单测</b>没有该 bean
     * ⇒ 用本类已装配的协作者就地构造一个（同一份 Mapper / Service / 时钟实例）⇒ 行为与拆分前逐字一致。</p>
     */
    @Autowired(required = false)
    private OrderSharedParts orderSharedParts;

    /**
     * 取共享部件：Spring 装配下 = 上面的 bean；手写 new 的既有单测下就地构造一份
     * （同一个 {@code objectMapper} / 同一批 Mapper 替身 / 同一份 {@link #stockService()}）⇒
     * 测试里被反射改写的协作者仍然生效，断言可以一个字都不改。
     */
    OrderSharedParts sharedParts() {
        OrderSharedParts parts = this.orderSharedParts;
        if (parts == null) {
            parts = new OrderSharedParts(orderItemMapper, objectMapper, productMapper,
                    processingFeeCalculator, processingFeeCombinationCommandService, businessClock,
                    userService, auditLogService, stockService(), stockBatchConsumptionService);
            this.orderSharedParts = parts;
        }
        return parts;
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

}
