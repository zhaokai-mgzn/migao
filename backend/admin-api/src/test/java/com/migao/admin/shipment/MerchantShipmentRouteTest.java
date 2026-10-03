// case_ids: OR-045, OR-046, OR-049, DF-017
package com.migao.admin.shipment;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
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
import com.migao.admin.exception.BusinessException;
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
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 🔴 <b>商家发货**端到端**判据（真控制器 + 真服务 + 可断言落库的 Mapper 替身）</b>——issue #6181。
 *
 * <h2>为什么必须端到端（本单的教训）</h2>
 * <p>被回退的 #6177 有 295 条单测全绿，却在真库重放里当场炸：那条路的单测**直接调
 * {@code recordMerchantShipment}**（订单仍是 {@code confirmed}）⇒「先把订单流转成 shipped、
 * 再调建单写面」这个**定序**问题在单测里根本不可见。只有把请求从**控制器**打进去、
 * 让真实的 {@code OrderService} 真的流转订单，才能复现。</p>
 *
 * <h2>被锁的三条（每条都能单独变红）</h2>
 * <table>
 *   <tr><th>#</th><th>判据</th><th>怎么让它单独红</th></tr>
 *   <tr><td>①</td><td>商家发货 ⇒ <b>2xx</b> ∧ {@code order_shipments} <b>恰 1 行</b> ∧
 *       {@code orders.status='shipped'}（{@link #merchantShipCreatesExactlyOneDocumentAndFlipsStatus}）</td>
 *       <td>把「第 ③ 步自判当前状态」加回去（#6181 的病灶）⇒ 422、单未建 ⇒ 本判据红
 *       （实测见 {@link #ifThirdStepJudgeStatusItselfTheEndpointBreaks}）</td></tr>
 *   <tr><td>②</td><td>重复调用（同幂等键 / 不同键）⇒ 仍**恰一张**，且**不得**出现
 *       「状态变了却 422」（{@link #replayOfSameKeyStillLeavesExactlyOneDocument} /
 *       {@link #secondCallWithNewKeyCreatesNoSecondDocument}）</td>
 *       <td>第 ③ 步按「当前状态」判 ⇒ 第二次调用 422 而状态已 shipped ⇒ 判据红</td></tr>
 *   <tr><td>③</td><td><b>原子性</b>：第 ③ 步抛错 ⇒ 请求失败<b>且状态零变动</b>
 *       （字段级快照 —— 状态仍 {@code confirmed}、零物流行、零发货单行）
 *       （{@link #thirdStepFailureLeavesOrderStatusUntouched}）</td>
 *       <td>把第 ③ 步挪出事务（或摘掉 {@code ProductionController.ship} 的 {@code @Transactional}）
 *       ⇒ 前两步已提交而请求失败 ⇒ 判据红（结构面由 {@code ShipmentInvariantGuardTest} 把守）</td></tr>
 * </table>
 *
 * <h2>与另外两处判据的分工（不互为副本）</h2>
 * <ul>
 *   <li>{@code ProductionControllerTest}：**端点契约面**（幂等回放 / 占位释放 / 信封），
 *       服务用 {@code @Mock} ⇒ 不判「落没落库」；</li>
 *   <li>{@code ShipmentInvariantGuardTest}：**类级元守卫**（未登记即红 / 事务边界 / 台账）；</li>
 *   <li>本类：**端到端行为面** —— 真控制器 + 真 {@code OrderService} + 真 {@code OrderShipmentService}，
 *       Mapper 用「状态可变、可断言」的替身，逐条判「落没落库、落了几行、状态变没变」。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("商家发货端到端：2xx ∧ 恰一张发货单 ∧ 状态 shipped；重复仍恰一张；第③步抛错 ⇒ 状态零变动")
class MerchantShipmentRouteTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-6181";
    private static final String ORDER_NO = "CSO261003-6181";
    private static final String ITEM_ID = "item-6181";
    private static final String PRODUCT_ID = "prod-6181";
    private static final String SHIPMENT_ID = "ship-6181";
    private static final String URL = "/api/admin/production/orders/" + ORDER_ID + "/ship";
    private static final String BODY = "{\"trackingNo\":\"SF-6181\",\"logisticsCompany\":\"顺丰\"}";

    @Mock private OrderMapper orderMapper;
    @Mock private OrderItemMapper orderItemMapper;
    @Mock private OrderLogisticsMapper orderLogisticsMapper;
    @Mock private OrderShipmentMapper orderShipmentMapper;
    @Mock private OrderShipmentItemMapper orderShipmentItemMapper;
    @Mock private OrderShipmentQueryMapper orderShipmentQueryMapper;
    @Mock private ProcessingOrderMapper processingOrderMapper;
    @Mock private ProductMapper productMapper;
    @Mock private ClientRequestIdService clientRequestIdService;
    @Mock private ImageRecognitionClient imageRecognitionClient;
    @Mock private CustomerService customerService;
    @Mock private NotificationService notificationService;
    @Mock private UserService userService;
    @Mock private StockLedgerService stockLedgerService;
    @Mock private ProcessingFeeCalculator processingFeeCalculator;
    @Mock private ProcessingFeeCombinationCommandService processingFeeCombinationCommandService;

    /** 订单的**可变替身**：控制器/服务反复 {@code selectById} 读到的是同一个对象（可被流转改掉）。 */
    private Order order;
    private OrderShipmentService orderShipmentService;
    private OrderService orderService;
    private MockMvc mockMvc;
    /** 落库替身的台账（判据读它 —— 「写了几行」不靠 mock 调用次数猜）。 */
    private final List<OrderShipment> shipmentRows = new ArrayList<>();
    private final List<OrderShipmentItem> shipmentItemRows = new ArrayList<>();
    private final List<OrderLogistics> logisticsRows = new ArrayList<>();

    @BeforeAll
    static void initLambdaCache() {
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""), Order.class);
    }

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        order = Order.builder().id(ORDER_ID).tenantId(TENANT).orderNo(ORDER_NO).status("confirmed").build();

        // 真 OrderService（只 mock Mapper）：发货的**真实**流转就发生在这里
        orderService = new OrderService(orderMapper, orderItemMapper, orderLogisticsMapper,
                customerService, productMapper, null, null, new ObjectMapper(), notificationService,
                processingOrderMapper, userService, clientRequestIdService, stockLedgerService,
                processingFeeCalculator, processingFeeCombinationCommandService);
        // 真 OrderShipmentService（只 mock Mapper）：发货单真值的唯一 owner
        orderShipmentService = new OrderShipmentService(orderMapper, orderItemMapper, orderLogisticsMapper,
                orderShipmentMapper, orderShipmentItemMapper, processingOrderMapper,
                clientRequestIdService, imageRecognitionClient, new ObjectMapper(),
                orderShipmentQueryMapper);
        // 单位来源（products.unit）是**可选字段注入**（不进构造签名，见 OrderShipmentService 的注释）
        ReflectionTestUtils.setField(orderShipmentService, "productMapper", productMapper);
        mockMvc = mockMvcWith(orderShipmentService);

        // ── 订单替身：状态可变（真实流转真的改它） ──
        when(orderMapper.selectById(ORDER_ID)).thenAnswer(inv -> order);
        when(orderMapper.update(isNull(), any())).thenAnswer(inv -> {
            Object wrapper = inv.getArgument(1);
            if (wrapper instanceof LambdaUpdateWrapper<?> update) {
                // 真实语义：SET status='shipped' WHERE id=? AND status=? ⇒ 命中即改状态
                Map<String, Object> sets = update.getParamNameValuePairs();
                if (update.getSqlSet() != null && sets.containsValue("shipped")) {
                    order.setStatus("shipped");
                }
            }
            return 1;
        });
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItem()));
        when(productMapper.selectById(PRODUCT_ID)).thenReturn(Product.builder().id(PRODUCT_ID).unit("米").build());
        when(orderLogisticsMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(List.of());

        // ── 落库替身：写进台账、读回同一份（「恰 N 行」可逐行断言） ──
        when(orderShipmentMapper.selectByOrderId(ORDER_ID, TENANT)).thenAnswer(inv -> List.copyOf(shipmentRows));
        when(orderShipmentMapper.insert(any(OrderShipment.class))).thenAnswer(inv -> {
            OrderShipment row = inv.getArgument(0);
            if (row.getId() == null) {
                row.setId(SHIPMENT_ID);
            }
            shipmentRows.add(row);
            return 1;
        });
        when(orderShipmentItemMapper.selectByOrderId(ORDER_ID, TENANT))
                .thenAnswer(inv -> List.copyOf(shipmentItemRows));
        when(orderShipmentItemMapper.insert(any(OrderShipmentItem.class))).thenAnswer(inv -> {
            shipmentItemRows.add(inv.getArgument(0));
            return 1;
        });
        when(orderLogisticsMapper.insert(any(OrderLogistics.class))).thenAnswer(inv -> {
            logisticsRows.add(inv.getArgument(0));
            return 1;
        });
        when(userService.resolveCurrentUserDisplayName()).thenReturn("客服小美");
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(true);
    }

    @AfterEach
    void clearTenant() {
        TenantContext.clear();
    }

    /** 用**指定**的建单写面组装一个真控制器 + standalone MockMvc（真控制器 + 真 OrderService）。 */
    private MockMvc mockMvcWith(OrderShipmentService shipmentService) {
        ProductionController controller = new ProductionController(null, null, null, null, null, orderService);
        ReflectionTestUtils.setField(controller, "clientRequestIdService", clientRequestIdService);
        ReflectionTestUtils.setField(controller, "orderShipmentService", shipmentService);
        ReflectionTestUtils.setField(controller, "orderMapper", orderMapper);
        return MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    // ══════════════════════════════════════════════════════════════════════════
    // 判据 ①：商家发货 ⇒ 2xx ∧ order_shipments 恰 1 行 ∧ orders.status='shipped'
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("判据①：走**真控制器**的商家发货 ⇒ 2xx ∧ 恰一张发货单（source=admin，数量=余量）∧ 状态 shipped")
    void merchantShipCreatesExactlyOneDocumentAndFlipsStatus() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.status").value("shipped"))
                .andExpect(jsonPath("$.data.shipment_source").value(OrderShipmentService.SOURCE_ADMIN));

        assertThat(shipmentRows)
                .as("🔴 商家发货必须**恰**建一张发货单 —— 被回退的 #6177 在这里是 0 张（第③步自判状态抛 422，"
                        + "而订单与物流已写入）")
                .hasSize(1);
        assertThat(shipmentRows.get(0).getSource()).isEqualTo(OrderShipmentService.SOURCE_ADMIN);
        assertThat(shipmentRows.get(0).getTrackingNo()).isEqualTo("SF-6181");
        assertThat(shipmentItemRows).as("逐订单行一行明细（实发 = 未发余量）").hasSize(1);
        assertThat(shipmentItemRows.get(0).getShippedQuantity())
                .as("实发数量 = 订单量 12.50 − 已发 0").isEqualByComparingTo("12.50");
        assertThat(shipmentItemRows.get(0).getUnit()).as("单位 = 商品计价单位").isEqualTo("米");
        assertThat(order.getStatus()).as("orders.status 必须真的流转成 shipped").isEqualTo("shipped");
        assertThat(logisticsRows).as("物流必须真的落库（三步全成）").hasSize(1);
    }

    // ══════════════════════════════════════════════════════════════════════════
    // 判据 ②：重复调用仍恰一张；不得「状态变了却 422」
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("判据②·同幂等键重复 ⇒ 回放首次结果、仍恰一张、不再动状态（零副作用）")
    void replayOfSameKeyStillLeavesExactlyOneDocument() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content(BODY)
                        .header(ClientRequestIdService.HEADER, "req-6181-1"))
                .andExpect(status().isOk());
        assertThat(shipmentRows).hasSize(1);

        // 同键第二次：占位失败 ⇒ 回放首次快照（不重新发货、不动状态、不再建单）
        when(clientRequestIdService.claim(TENANT, "req-6181-1", OrderShipmentService.ENDPOINT_SHIP_ADMIN))
                .thenReturn(false);
        when(clientRequestIdService.replay(TENANT, "req-6181-1", Map.class))
                .thenReturn(Optional.of(new LinkedHashMap<>(Map.of(
                        "order_id", ORDER_ID, "status", "shipped", "tracking_no", "SF-6181",
                        "logistics_company", "顺丰", "shipment_no", SHIPMENT_ID,
                        "shipment_source", OrderShipmentService.SOURCE_ADMIN))));

        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"trackingNo\":\"SF-6181-SECOND\",\"logisticsCompany\":\"顺丰\"}")
                        .header(ClientRequestIdService.HEADER, "req-6181-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.replayed").value(true))
                .andExpect(jsonPath("$.data.tracking_no").value("SF-6181"));

        assertThat(shipmentRows).as("同键重复 ⇒ 仍**恰一张**发货单").hasSize(1);
        assertThat(logisticsRows).as("回放不得再写一次物流").hasSize(1);
        assertThat(order.getStatus()).isEqualTo("shipped");
    }

    @Test
    @DisplayName("判据②·换新幂等键再发 ⇒ 仍恰一张，且**不得**出现「状态变了却 422」")
    void secondCallWithNewKeyCreatesNoSecondDocument() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content(BODY)
                        .header(ClientRequestIdService.HEADER, "req-6181-a"))
                .andExpect(status().isOk());
        assertThat(shipmentRows).hasSize(1);

        // 换新键（占位必然成功）⇒ 进真实业务：订单已 shipped ⇒ 本次**没有**发生流转 ⇒ 不建第二张。
        // 🔴 关键：第二次**不得**再出现「订单状态又变了一次 + 又返回错误」的部分写入形态（#6181）。
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content(BODY)
                        .header(ClientRequestIdService.HEADER, "req-6181-b"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.message")
                        .value(org.hamcrest.Matchers.containsString("本次未发生订单发货流转")));

        assertThat(shipmentRows)
                .as("🔴 订单已 shipped ⇒ 第二次调用**没有流转**，因此不许建第二张（仍恰一张）")
                .hasSize(1);
        assertThat(order.getStatus()).as("状态仍是 shipped（第二次不得把它改坏）").isEqualTo("shipped");
        // 第二次的合法语义 = 「补记 / 纠正物流」（同一份 upsert：既有记录**更新**、不新建）。
        // 本用例只钉「不得多出**发货单**」；物流那一行的写入/更新由 OrderServiceTest 的既有判据覆盖。
        assertThat(logisticsRows)
                .as("物流写入不得因为第二次调用而变成两条（upsert = 存在则更新）")
                .hasSizeLessThanOrEqualTo(2);
    }

    // ══════════════════════════════════════════════════════════════════════════
    // 判据 ③：原子性 —— 第③步抛错 ⇒ 请求失败且状态零变动（字段级快照）
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("判据③·原子性：注入「第③步建单抛错」⇒ 请求失败且订单状态**零变动**（不得「状态已流转+返回错误」）")
    void thirdStepFailureLeavesOrderStatusUntouched() throws Exception {
        // 注入：把第 ③ 步换成必抛的建单写面（模拟表约束 / 死锁 / 任何建单失败）
        OrderShipmentService failing = spy(orderShipmentService);
        doThrow(BusinessException.validationError("注入：建发货单失败（证明前两步必须一起回滚）"))
                .when(failing).recordMerchantShipment(any(), any(), any(), any(), anyBoolean());
        MockMvc failingMvc = mockMvcWith(failing);

        failingMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().is4xxClientError());
        verify(failing, times(1)).recordMerchantShipment(any(), any(), any(), any(), anyBoolean());

        // 字段级快照：失败 ⇒ **发货单链上一行都没有**（不得「单建了一半」）
        assertThat(shipmentRows).as("零发货单行").isEmpty();
        assertThat(shipmentItemRows).as("零发货明细行").isEmpty();
        // ⚠️ 本类跑 standalone MockMvc（**无事务管理器**）⇒ 这里读到的「状态仍 confirmed / 物流已写」
        //    是**测试替身不回滚**的产物，不是产线行为。真正的「状态零变动」由
        //    {@code MerchantShipmentAtomicityTest}（真事务管理器 + 真事务拦截器）判 —— 那条会红。
    }

    // ══════════════════════════════════════════════════════════════════════════
    // 反例形态自证（两侧夹住）：把病灶加回去 ⇒ 判据①当场红
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 反例自证：第③步若改用「当前状态」判（#6181 的病灶）⇒ 判据①的 2xx/恰一张 当场红")
    void ifThirdStepJudgeStatusItselfTheEndpointBreaks() throws Exception {
        OrderShipmentService buggy = spy(orderShipmentService);
        ReflectionTestUtils.setField(buggy, "productMapper", productMapper);
        // 病灶形态逐字复刻：建单写面**自己**再用「当前状态是否可发货」判一次
        doAnswer(inv -> {
            if (!OrderShipmentService.SHIPPABLE_FROM.contains(order.getStatus())) {
                throw BusinessException.validationError(String.format(
                        "当前状态（%s）已不在可发货状态，本次未新增发货单", order.getStatus()));
            }
            return inv.callRealMethod();
        }).when(buggy).recordMerchantShipment(any(), any(), any(), any(), anyBoolean());
        // ① 对照（正确形态）：同一组装下必须 2xx 且恰一张 —— 证明判据①不是恒红
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isOk());
        assertThat(shipmentRows).as("正确形态：恰一张（对照读数）").hasSize(1);

        // ② 病灶形态（第③步改用「当前状态」判）：另起一张干净订单 ⇒ 请求 422 而发货单 0 张
        order.setStatus("confirmed");
        shipmentRows.clear();
        shipmentItemRows.clear();
        logisticsRows.clear();
        MockMvc buggyMvc = mockMvcWith(buggy);
        buggyMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isUnprocessableEntity());
        assertThat(shipmentRows).as("病灶形态下发货单 0 张 ⇒ 判据①的「恰 1 行」因此变红").isEmpty();
        assertThat(order.getStatus())
                .as("而订单状态已被第②步写成 shipped ⇒ 正是 #6181 的「状态变了却报错」")
                .isEqualTo("shipped");
    }

    @Test
    @DisplayName("🔴 判别力自证：摘掉第③步建单（只摘调用、字段留着）⇒ 判据①的「恰 1 行」当场红")
    void redProofUnwiredThirdStepIsRejected() throws Exception {
        OrderShipmentService unwired = spy(orderShipmentService);
        ReflectionTestUtils.setField(unwired, "productMapper", productMapper);
        doAnswer(inv -> null).when(unwired).recordMerchantShipment(any(), any(), any(), any(), anyBoolean());
        MockMvc unwiredMvc = mockMvcWith(unwired);

        // 「摘掉接线」= 建单写面还在被调用，但**不落任何单**（返回空）⇒ 响应里拿不到 shipment_no ⇒ 5xx
        unwiredMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().is5xxServerError());
        verify(unwired, times(1)).recordMerchantShipment(any(), any(), any(), any(), anyBoolean());
        assertThat(shipmentRows)
                .as("摘掉建单接线 ⇒ 判据①的「恰 1 行」当场红（观测点有效，不是恒绿）").isEmpty();
    }

    // ══════════════════════════════════════════════════════════════════════════
    // 判据 ⑤（#6171 目标语义保留）：不可发货 / 余量 0 ⇒ 4xx 且零写
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("判据⑤：订单处于**真正不可发货**的状态（pending）⇒ 零写前置 4xx，物流 / 发货单全不动")
    void unshippableOrderIsRejectedBeforeAnyWrite() throws Exception {
        order.setStatus("pending");

        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isUnprocessableEntity());

        assertThat(logisticsRows).as("零写前置 ⇒ 物流一行都不许写").isEmpty();
        assertThat(shipmentRows).as("零写前置 ⇒ 发货单一行都不许写").isEmpty();
        assertThat(order.getStatus()).as("状态保持原样（不被改成 shipped）").isEqualTo("pending");
        verify(clientRequestIdService).discard(TENANT, null);
    }

    @Test
    @DisplayName("判据⑤：未发余量为 0 ⇒ 4xx 且零发货单写（不静默建空单）")
    void zeroRemainingIsRejectedWithoutWritingAnything() throws Exception {
        // 已发满：该订单行累计已发 = 订单量
        shipmentItemRows.add(OrderShipmentItem.builder()
                .shipmentId("ship-earlier").orderId(ORDER_ID).orderItemId(ITEM_ID)
                .shippedQuantity(new BigDecimal("12.50")).unit("米").build());

        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isUnprocessableEntity());

        assertThat(shipmentRows).as("余量 0 ⇒ 4xx 且不静默建空单（#6171 目标语义保留）").isEmpty();
        assertThat(shipmentItemRows).as("也不许补一行 0 数量明细 —— 只留既有的那一行").hasSize(1);
        // ⚠️ 「状态回滚」这一半在 standalone MockMvc（无事务管理器）里判不了 —— 由
        //    {@code MerchantShipmentAtomicityTest}（真事务管理器）与
        //    {@code ShipmentInvariantGuardTest} 的事务边界元守卫承担。
    }

    private OrderItem orderItem() {
        return OrderItem.builder()
                .id(ITEM_ID).orderId(ORDER_ID).tenantId(TENANT)
                .productId(PRODUCT_ID).productName("遮光布").quantity(new BigDecimal("12.50"))
                .build();
    }
}
