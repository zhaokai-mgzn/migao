// case_ids: OR-045, OR-046, OR-049, DF-017
package com.migao.admin.shipment;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.controller.ProductionController;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.entity.OrderShipment;
import com.migao.admin.entity.OrderShipmentItem;
import com.migao.admin.entity.Product;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.OrderShipmentItemMapper;
import com.migao.admin.mapper.OrderShipmentMapper;
import com.migao.admin.mapper.OrderShipmentQueryMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.CustomerService;
import com.migao.admin.service.ImageRecognitionClient;
import com.migao.admin.service.NotificationService;
import com.migao.admin.service.OrderService;
import com.migao.admin.service.OrderShipmentService;
import com.migao.admin.service.ProcessingFeeCalculator;
import com.migao.admin.service.ProcessingFeeCombinationCommandService;
import com.migao.admin.service.StockLedgerService;
import com.migao.admin.service.UserService;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import org.springframework.transaction.support.AbstractPlatformTransactionManager;
import org.springframework.transaction.support.DefaultTransactionStatus;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 商家发货路的原子性判据（issue #6181 要求 1 的承载体）——真事务拦截器 + 事务感知的内存存储。
 *
 * <h2>为什么需要本类</h2>
 * <p>issue #6181 的病历是部分写入：orders.status 已改成 shipped、物流已写、发货单没建、接口却回错误。
 * 要判死这个形态，必须同时具备两样：① 真事务边界（ProductionController.ship 上的
 * {@code @Transactional(rollbackFor = Exception.class)} 真的被事务拦截器执行）；② 可观测的回滚
 * （有东西记账 commit/rollback，且回滚真的把替身状态恢复回去，否则「状态零变动」读到的只是脏值）。</p>
 * <p>本类的做法：InMemoryTxManager 在 doBegin 拍快照、doRollback 恢复快照（AtomicityStore），
 * 端点经 ProxyFactory + TransactionInterceptor 包上真事务拦截器 —— 事务属性只来自生产代码里的
 * {@code @Transactional} 注解。不依赖任何数据库。</p>
 *
 * <h2>会怎么红</h2>
 * <ul>
 *   <li>摘掉 ProductionController.ship 的 {@code @Transactional} ⇒ 拦截器找不到事务属性、不开事务
 *       （begun == 0）⇒ 红；</li>
 *   <li>把第 ③ 步挪到事务外（或 REQUIRES_NEW）⇒ 回滚不再覆盖前两步 ⇒ 红；</li>
 *   <li>去掉 rollbackFor = Exception.class ⇒ 回滚覆盖不再成立 ⇒ 红。</li>
 * </ul>
 */
@DisplayName("商家发货原子性：第③步建单失败 ⇒ 同一事务回滚（订单状态零变动）")
class MerchantShipmentAtomicityTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-6181-atomic";
    private static final String ITEM_ID = "item-6181-atomic";
    private static final String PRODUCT_ID = "prod-6181-atomic";
    private static final String URL = "/api/admin/production/orders/" + ORDER_ID + "/ship";
    private static final String BODY = "{\"trackingNo\":\"SF-ATOMIC\",\"logisticsCompany\":\"顺丰\"}";

    private final AtomicityStore store = new AtomicityStore();
    private InMemoryTxManager txManager;
    private OrderMapper orderMapper;
    private OrderItemMapper orderItemMapper;
    private OrderLogisticsMapper orderLogisticsMapper;
    private ProductMapper productMapper;
    private ClientRequestIdService clientRequestIdService;
    private CustomerService customerService;
    private NotificationService notificationService;
    private UserService userService;
    private StockLedgerService stockLedgerService;
    private ProcessingFeeCalculator processingFeeCalculator;
    private ProcessingFeeCombinationCommandService processingFeeCombinationCommandService;
    private ProcessingOrderMapper processingOrderMapper;
    private OrderShipmentMapper orderShipmentMapper;
    private OrderShipmentItemMapper orderShipmentItemMapper;
    private OrderShipmentQueryMapper orderShipmentQueryMapper;
    private ImageRecognitionClient imageRecognitionClient;

    private Order order;
    private AnnotationConfigApplicationContext context;
    private MockMvc mockMvc;

    @BeforeAll
    static void initLambdaCache() {
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""), Order.class);
    }

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        order = Order.builder().id(ORDER_ID).tenantId(TENANT).orderNo("CSO261003-ATOMIC")
                .status("confirmed").build();
        orderMapper = mock(OrderMapper.class);
        orderItemMapper = mock(OrderItemMapper.class);
        orderLogisticsMapper = mock(OrderLogisticsMapper.class);
        productMapper = mock(ProductMapper.class);
        clientRequestIdService = mock(ClientRequestIdService.class);
        customerService = mock(CustomerService.class);
        notificationService = mock(NotificationService.class);
        userService = mock(UserService.class);
        stockLedgerService = mock(StockLedgerService.class);
        processingFeeCalculator = mock(ProcessingFeeCalculator.class);
        processingFeeCombinationCommandService = mock(ProcessingFeeCombinationCommandService.class);
        processingOrderMapper = mock(ProcessingOrderMapper.class);
        orderShipmentMapper = mock(OrderShipmentMapper.class);
        orderShipmentItemMapper = mock(OrderShipmentItemMapper.class);
        orderShipmentQueryMapper = mock(OrderShipmentQueryMapper.class);
        imageRecognitionClient = mock(ImageRecognitionClient.class);

        when(orderMapper.selectById(ORDER_ID)).thenAnswer(inv -> order);
        when(orderMapper.update(isNull(), any())).thenAnswer(inv -> {
            // 真库语义：SET status='shipped' 落到存储（回滚 = 事务管理器恢复快照）
            store.status = "shipped";
            order.setStatus("shipped");
            return 1;
        });
        when(orderItemMapper.selectList(any())).thenReturn(List.of(OrderItem.builder()
                .id(ITEM_ID).orderId(ORDER_ID).tenantId(TENANT).productId(PRODUCT_ID)
                .productName("遮光布").quantity(new BigDecimal("12.50")).build()));
        when(productMapper.selectById(PRODUCT_ID)).thenReturn(Product.builder().id(PRODUCT_ID).unit("米").build());
        when(orderLogisticsMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(List.of());
        when(orderLogisticsMapper.insert(any(OrderLogistics.class))).thenAnswer(inv -> {
            store.logisticsRows.add("log");
            return 1;
        });
        when(orderShipmentMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(List.of());
        when(orderShipmentMapper.insert(any(OrderShipment.class))).thenAnswer(inv -> {
            store.shipmentRows.add("ship");
            return 1;
        });
        when(orderShipmentItemMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(List.of());
        when(orderShipmentItemMapper.insert(any(OrderShipmentItem.class))).thenAnswer(inv -> {
            store.shipmentItemRows.add("item");
            return 1;
        });
        when(userService.resolveCurrentUserDisplayName()).thenReturn("客服小美");
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(true);
        // `order` 与 store 必须同源：回滚时把内存订单行也恢复（判据读 order.getStatus()）
        store.onRollbackStatus = status -> order.setStatus(status);
        txManager = new InMemoryTxManager(store);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
        if (context != null) {
            context.close();
        }
    }

    @Test
    @DisplayName("🔴 第③步建单失败 ⇒ 事务回滚（rollback=1 / commit=0），订单状态零变动")
    void thirdStepFailureRollsBackTheWholeMerchantShipRoute() throws Exception {
        // 注入：建单写面的唯一落库动作（insert order_shipments）炸掉 —— 表约束 / 死锁这类真实故障
        when(orderShipmentMapper.insert(any(OrderShipment.class)))
                .thenThrow(new DuplicateKeyException("注入：建发货单失败（模拟表约束 / 死锁）"));
        bootContext();

        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content(BODY))
                // 基础设施级失败（表约束 / 死锁）⇒ 5xx；关键是它回滚了整笔事务
                .andExpect(status().is5xxServerError());

        assertThat(txManager.begun)
                .as("端点必须在一个事务里跑完整条路（摘掉 @Transactional ⇒ 这里就是 0）")
                .isEqualTo(1);
        assertThat(txManager.rolledBack)
                .as("第③步失败 ⇒ 必须回滚（据此订单状态与物流一起撤销）").isEqualTo(1);
        assertThat(txManager.committed)
                .as("绝不允许「提交了状态流转、再抛错」—— 那正是 #6181 的部分写入病历").isZero();
        assertThat(order.getStatus())
                .as("字段级快照：回滚后订单状态必须仍是 confirmed（不是 shipped）")
                .isEqualTo("confirmed");
        assertThat(store.status)
                .as("字段级快照（落库替身）：回滚后 orders.status 必须仍是 confirmed").isEqualTo("confirmed");
        assertThat(store.shipmentRows).as("零发货单行（回滚）").isEmpty();
        assertThat(store.logisticsRows).as("零物流行（回滚 —— 第②步的写也必须撤销）").isEmpty();
    }

    @Test
    @DisplayName("对照：三步全成 ⇒ 事务提交（commit=1 / rollback=0），状态真的流转")
    void happyPathCommitsTheTransaction() throws Exception {
        bootContext();

        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isOk());

        assertThat(txManager.begun).isEqualTo(1);
        assertThat(txManager.committed)
                .as("成功路径必须提交（否则上面那条「必须回滚」就成了恒真断言）").isEqualTo(1);
        assertThat(txManager.rolledBack).isZero();
        assertThat(order.getStatus()).isEqualTo("shipped");
        assertThat(store.shipmentRows).as("成功路径真的建了一张发货单").hasSize(1);
    }

    @Test
    @DisplayName("判别力自证：注入的建单失败确实被执行到（发货单一行都没落）")
    void failingInjectionReallyFires() throws Exception {
        when(orderShipmentMapper.insert(any(OrderShipment.class)))
                .thenThrow(new DuplicateKeyException("注入：建发货单失败"));
        bootContext();

        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().is5xxServerError());

        assertThat(store.shipmentRows)
                .as("注入的替身必须真的在写面上生效（否则「回滚」判据可能因为别的原因才红）")
                .isEmpty();
    }

    /**
     * 在真事务拦截器下装配端点。
     *
     * <p>为什么用显式 ProxyFactory 而不是 @EnableTransactionManagement 的自动代理：后者的自动代理
     * 只作用于由 BeanDefinition 创建的 bean（registerSingleton 注册的实例不保证被代理 —— 实测
     * begun == 0）。本类要判的恰恰是「ProductionController.ship 上那条 @Transactional 真的会开启并
     * 回滚一个事务」—— 所以直接把它挂到事务拦截器上：摘掉注解 ⇒ AnnotationTransactionAttributeSource
     * 找不到事务属性 ⇒ 拦截器不开启事务 ⇒ begun == 0 ⇒ 判据红。</p>
     */
    private void bootContext() {
        context = new AnnotationConfigApplicationContext();
        context.registerBean(InMemoryTxManager.class, () -> txManager);
        context.registerBean(OrderMapper.class, () -> orderMapper);
        context.registerBean(OrderItemMapper.class, () -> orderItemMapper);
        context.registerBean(OrderLogisticsMapper.class, () -> orderLogisticsMapper);
        context.registerBean(OrderShipmentMapper.class, () -> orderShipmentMapper);
        context.registerBean(OrderShipmentItemMapper.class, () -> orderShipmentItemMapper);
        context.registerBean(OrderShipmentQueryMapper.class, () -> orderShipmentQueryMapper);
        context.registerBean(ProductMapper.class, () -> productMapper);
        context.registerBean(ProcessingOrderMapper.class, () -> processingOrderMapper);
        context.registerBean(ClientRequestIdService.class, () -> clientRequestIdService);
        context.registerBean(ImageRecognitionClient.class, () -> imageRecognitionClient);
        context.refresh();

        OrderService orderService = new OrderService(orderMapper, orderItemMapper, orderLogisticsMapper,
                customerService, productMapper, null, null, new ObjectMapper(), notificationService,
                processingOrderMapper, userService, clientRequestIdService, stockLedgerService,
                processingFeeCalculator, processingFeeCombinationCommandService);
        OrderShipmentService shipmentService = new OrderShipmentService(
                orderMapper, orderItemMapper, orderLogisticsMapper, orderShipmentMapper,
                orderShipmentItemMapper, processingOrderMapper, clientRequestIdService,
                imageRecognitionClient, new ObjectMapper(), orderShipmentQueryMapper);
        ReflectionTestUtils.setField(shipmentService, "productMapper", productMapper);

        ProductionController controller = new ProductionController(null, null, null, null, null, orderService);
        ReflectionTestUtils.setField(controller, "clientRequestIdService", clientRequestIdService);
        ReflectionTestUtils.setField(controller, "orderShipmentService", shipmentService);
        ReflectionTestUtils.setField(controller, "orderMapper", orderMapper);
        mockMvc = MockMvcBuilders.standaloneSetup(withTransactionInterceptor(controller))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    /** 把端点包进真事务拦截器：事务属性只认 @Transactional 注解（生产代码的契约）。 */
    private ProductionController withTransactionInterceptor(ProductionController target) {
        ProxyFactory factory = new ProxyFactory(target);
        factory.setProxyTargetClass(true);
        factory.addAdvice(new TransactionInterceptor(txManager,
                new AnnotationTransactionAttributeSource()));
        return (ProductionController) factory.getProxy();
    }

    /** 事务感知的内存存储：真回滚 = 恢复快照（判据因此能读字段级事实）。 */
    static class AtomicityStore {
        String status = "confirmed";
        final List<String> shipmentRows = new ArrayList<>();
        final List<String> shipmentItemRows = new ArrayList<>();
        final List<String> logisticsRows = new ArrayList<>();
        /** 回滚时同步恢复内存订单行（与 store.status 同源）。 */
        java.util.function.Consumer<String> onRollbackStatus = status -> { };
        private String snapshotStatus;
        private int snapshotShipments;
        private int snapshotItems;
        private int snapshotLogistics;

        void begin() {
            snapshotStatus = status;
            snapshotShipments = shipmentRows.size();
            snapshotItems = shipmentItemRows.size();
            snapshotLogistics = logisticsRows.size();
        }

        void rollback() {
            status = snapshotStatus;
            onRollbackStatus.accept(snapshotStatus);
            while (shipmentRows.size() > snapshotShipments) {
                shipmentRows.remove(shipmentRows.size() - 1);
            }
            while (shipmentItemRows.size() > snapshotItems) {
                shipmentItemRows.remove(shipmentItemRows.size() - 1);
            }
            while (logisticsRows.size() > snapshotLogistics) {
                logisticsRows.remove(logisticsRows.size() - 1);
            }
        }
    }

    /** 内存事务管理器：记账 + 真回滚语义（快照/恢复，不依赖任何数据库）。 */
    static class InMemoryTxManager extends AbstractPlatformTransactionManager {
        private final AtomicityStore store;
        int begun;
        int committed;
        int rolledBack;

        InMemoryTxManager(AtomicityStore store) {
            this.store = store;
        }

        @Override
        protected Object doGetTransaction() {
            return new Object();
        }

        @Override
        protected void doBegin(Object transaction, TransactionDefinition definition) {
            begun++;
            store.begin();
        }

        @Override
        protected void doCommit(DefaultTransactionStatus status) throws TransactionException {
            committed++;
        }

        @Override
        protected void doRollback(DefaultTransactionStatus status) throws TransactionException {
            rolledBack++;
            store.rollback();
        }
    }
}
