// case_ids: OR-045, OR-046, OR-049, DF-017
package com.migao.admin.shipment;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.entity.OrderShipment;
import com.migao.admin.entity.OrderShipmentItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.OrderShipmentItemMapper;
import com.migao.admin.mapper.OrderShipmentMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ImageRecognitionClient;
import com.migao.admin.service.OrderShipmentService;
import com.migao.admin.service.OrderStatusTransitions;
import com.migao.admin.worker.WorkerIdentity;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 🔴 工人发货链的**核心判据**（issue #5648）：打包 / 发货 / 撤销 / 实发明细 / 守卫 / 幂等 / 跨租户。
 *
 * <p>本类不碰 Spring 上下文（纯 Mockito）—— 它断言的是**服务层口径**：状态流转、写序、
 * 守卫位置、留痕内容。路由与门禁面（工人到得了 {@code /api/worker/**}、
 * 工人到不了 {@code /api/admin/**}）在 {@code WorkerShipmentContractTest}。</p>
 *
 * <p><b>本单必须显式回答的两个问题</b>（issue #5648 裁定要求，判据在这里）：</p>
 * <ol>
 *   <li>{@code packed → shipped} 能不能由工人**一步**完成？——
 *       {@link #shipFromConfirmedIsStillAllowedAndBackfillsPackedAt()}：能，但服务端**补记**
 *       {@code packed_at}（「发出去的货必然已经被打包过」是物理事实，不补记就留下"跳过打包"的无痕形态）。</li>
 *   <li>打包打错了**能不能撤销**？—— {@link #unpackLeavesTraceAndRequiresReason()} +
 *       {@link #merchantPathCannotRevertPackedWithoutReason()}：能，但**只能由工人**、
 *       **必须带理由**、且**留痕**；商家侧那条无理由的状态端点**做不到**（目标状态不在状态表里）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("工人发货链：打包 / 发货 / 撤销 / 实发明细 / 守卫 / 幂等 / 跨租户")
class WorkerShipmentFlowTest {

    private static final Long TENANT = 1L;
    private static final Long OTHER_TENANT = 2L;
    private static final String ORDER_ID = "order-1";
    private static final String ORDER_NO = "ORD-20260926-0001";
    private static final String ITEM_ID = "item-1";
    private static final String WORKER_ID = "worker-zhang";
    private static final String WORKER_NAME = "张三";
    private static final String KEY = "key-1";

    @Mock private OrderMapper orderMapper;
    @Mock private OrderItemMapper orderItemMapper;
    @Mock private OrderLogisticsMapper orderLogisticsMapper;
    @Mock private OrderShipmentMapper orderShipmentMapper;
    @Mock private OrderShipmentItemMapper orderShipmentItemMapper;
    @Mock private ProcessingOrderMapper processingOrderMapper;
    @Mock private ClientRequestIdService clientRequestIdService;
    @Mock private ImageRecognitionClient imageRecognitionClient;
    /** 真实 ObjectMapper（`processing_info` 的 JSON 字符串兼容解析要用它 —— 用 mock 会把那条路测成空跑）。 */
    @Mock private ObjectMapper objectMapper;

    @InjectMocks private OrderShipmentService service;

    /**
     * MyBatis-Plus 的 lambda 列名缓存（`LambdaUpdateWrapper` 要靠它把 `Order::getId` 翻成列名）。
     * 纯 Mockito 单测里没有 mapper 注册流程 ⇒ 必须手工初始化，否则每次 `transition()` 都抛
     * `can not find lambda cache for this entity`（那不是被测行为，是测试夹具缺一步）。
     */
    @BeforeAll
    static void initLambdaCache() {
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""), Order.class);
    }

    @BeforeEach
    void setUp() {
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(true);
        when(orderMapper.update(isNull(), any())).thenReturn(1);
        when(orderShipmentMapper.insert(any(OrderShipment.class))).thenAnswer(inv -> {
            OrderShipment s = inv.getArgument(0);
            if (s.getId() == null) {
                s.setId("ship-1");
            }
            return 1;
        });
    }

    // ── fixtures ─────────────────────────────────────────────────────────────

    private WorkerIdentity worker() {
        return new WorkerIdentity(WORKER_ID, WORKER_NAME,
                WorkerIdentity.SOURCE_SERVER_SESSION, "sess-1");
    }

    private Order order(String status) {
        return Order.builder().id(ORDER_ID).tenantId(TENANT).orderNo(ORDER_NO)
                .status(status).build();
    }

    /** 无加工项的普通订单行（`processing_info` 为空 ⇒ 加工单守卫放行）。 */
    private OrderItem plainItem() {
        return OrderItem.builder().id(ITEM_ID).orderId(ORDER_ID).tenantId(TENANT)
                .productName("遮光窗帘").quantity(new BigDecimal("12.00")).deleted(0).build();
    }

    /** 含加工项的订单行（`processing_info.processingItems` 非空 ⇒ 守卫要查加工单）。 */
    private OrderItem processingItem() {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("processingItems", List.of(Map.of("id", "pi-1", "name", "韩褶-布", "quantity", 3)));
        return OrderItem.builder().id(ITEM_ID).orderId(ORDER_ID).tenantId(TENANT)
                .productName("遮光窗帘").quantity(new BigDecimal("12.00"))
                .processingInfo(info).deleted(0).build();
    }

    private void givenOrderItems(OrderItem... items) {
        when(orderItemMapper.selectList(any())).thenReturn(new ArrayList<>(List.of(items)));
    }

    private Map<String, Object> shipBody() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("trackingNo", "SF123456");
        body.put("logisticsCompany", "顺丰");
        body.put("items", List.of(new LinkedHashMap<>(Map.of(
                "order_item_id", ITEM_ID,
                "product_name", "遮光窗帘",
                "shipped_quantity", new BigDecimal("10.00"),
                "unit", "米"))));
        return body;
    }

    private List<OrderShipmentItem> capturedItems() {
        org.mockito.ArgumentCaptor<OrderShipmentItem> captor =
                org.mockito.ArgumentCaptor.forClass(OrderShipmentItem.class);
        verify(orderShipmentItemMapper, org.mockito.Mockito.atLeastOnce()).insert(captor.capture());
        return captor.getAllValues();
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ① 工人身份：fail-closed（**不降级到 body 口径**）
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 无工人身份 ⇒ 拒绝（发货留痕是责任凭证，不能由前端自称）")
    void workerIdentityIsMandatory() {
        assertThatThrownBy(() -> service.ship(ORDER_ID, shipBody(), TENANT, KEY, null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("工人身份");
        // body 口径的身份（client_body）**不算**工人身份 —— 本路径没有第二条身份来源
        WorkerIdentity fromBody = WorkerIdentity.fromClientBody(WORKER_ID, WORKER_NAME);
        assertThatThrownBy(() -> service.ship(ORDER_ID, shipBody(), TENANT, KEY, fromBody))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("工人身份");
        verify(orderShipmentMapper, never()).insert(any(OrderShipment.class));
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ② 打包：状态机 + 留痕
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("打包：confirmed → packed，并留下「谁在何时打的包」")
    void packMovesConfirmedToPackedWithTrace() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("confirmed"));
        when(orderShipmentMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(new ArrayList<>());

        Map<String, Object> result = service.pack(ORDER_ID, TENANT, KEY, worker());

        assertThat(result.get("status")).isEqualTo("packed");
        org.mockito.ArgumentCaptor<OrderShipment> captor =
                org.mockito.ArgumentCaptor.forClass(OrderShipment.class);
        verify(orderShipmentMapper).insert(captor.capture());
        assertThat(captor.getValue().getPackedByWorkerId()).isEqualTo(WORKER_ID);
        assertThat(captor.getValue().getPackedByWorkerName()).isEqualTo(WORKER_NAME);
        assertThat(captor.getValue().getPackedAt()).isNotNull();
        verify(orderMapper).update(isNull(), any());
    }

    @Test
    @DisplayName("🔴 非法流转仍被拒：pending → packed 必须拒绝（状态机不许被绕过）")
    void packRejectsIllegalTransition() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("pending"));

        assertThatThrownBy(() -> service.pack(ORDER_ID, TENANT, KEY, worker()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许");
        verify(orderShipmentMapper, never()).insert(any(OrderShipment.class));
        verify(orderMapper, never()).update(isNull(), any());
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ③ 发货：实发明细 + 原子流转 + 一步到底补记 packed_at
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("发货：packed → shipped，实发明细落库（实发 10 米 ≠ 下单 12 米）")
    void shipWritesActualDetailsAndTransitions() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("packed"));
        givenOrderItems(plainItem());
        OrderShipment packed = OrderShipment.builder().id("ship-1").tenantId(TENANT)
                .orderId(ORDER_ID).shipmentNo("SH1").source(OrderShipmentService.SOURCE_WORKER)
                .packedAt(OffsetDateTime.now()).build();
        when(orderShipmentMapper.selectByOrderId(ORDER_ID, TENANT))
                .thenReturn(new ArrayList<>(List.of(packed)));

        Map<String, Object> result = service.ship(ORDER_ID, shipBody(), TENANT, KEY, worker());

        assertThat(result.get("status")).isEqualTo("shipped");
        List<OrderShipmentItem> items = capturedItems();
        assertThat(items).hasSize(1);
        assertThat(items.get(0).getShippedQuantity()).isEqualByComparingTo(new BigDecimal("10.00"));
        assertThat(items.get(0).getUnit()).isEqualTo("米");
        assertThat(items.get(0).getOrderItemId()).isEqualTo(ITEM_ID);
        // 缺值不填 0：套数/卷数没给 ⇒ null（0 是「一件都没发」的另一个意思）
        assertThat(items.get(0).getSetCount()).isNull();
        assertThat(items.get(0).getRollCount()).isNull();
        verify(orderLogisticsMapper).insert(any(OrderLogistics.class));
        verify(orderMapper).update(isNull(), any());
    }

    @Test
    @DisplayName("🔴 一步到底（confirmed → shipped）允许，但服务端**补记** packed_at（不留「跳过打包」的无痕形态）")
    void shipFromConfirmedIsStillAllowedAndBackfillsPackedAt() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("confirmed"));
        givenOrderItems(plainItem());
        when(orderShipmentMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(new ArrayList<>());

        service.ship(ORDER_ID, shipBody(), TENANT, KEY, worker());

        org.mockito.ArgumentCaptor<OrderShipment> captor =
                org.mockito.ArgumentCaptor.forClass(OrderShipment.class);
        verify(orderShipmentMapper).insert(captor.capture());
        OrderShipment saved = captor.getValue();
        assertThat(saved.getPackedAt()).as("发货必然已经打包过 —— 不补记就查不出谁打的包").isNotNull();
        assertThat(saved.getPackedByWorkerName()).isEqualTo(WORKER_NAME);
        assertThat(saved.getShippedAt()).isNotNull();
        assertThat(saved.getShippedByWorkerName()).isEqualTo(WORKER_NAME);
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ④ 加工单守卫（issue #3340）**不许被绕过** + 守卫在写之前
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 含加工项且加工单未完成 ⇒ 拒绝发货，且**一个字节都没写**（守卫在写之前）")
    void shipBlockedByProcessingGuardBeforeAnyWrite() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("packed"));
        givenOrderItems(processingItem());
        when(processingOrderMapper.countCompletedByOrderId(ORDER_ID, TENANT)).thenReturn(0L);

        assertThatThrownBy(() -> service.ship(ORDER_ID, shipBody(), TENANT, KEY, worker()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("须先完成加工单");

        verify(orderShipmentMapper, never()).insert(any(OrderShipment.class));
        verify(orderShipmentMapper, never()).updateById(any(OrderShipment.class));
        verify(orderShipmentItemMapper, never()).insert(any(OrderShipmentItem.class));
        verify(orderLogisticsMapper, never()).insert(any(OrderLogistics.class));
        verify(orderMapper, never()).update(isNull(), any());
    }

    @Test
    @DisplayName("反向护栏：加工单已完成 ⇒ 放行（守卫不是「含加工项就一律拒」）")
    void shipAllowedWhenProcessingOrderCompleted() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("packed"));
        givenOrderItems(processingItem());
        when(processingOrderMapper.countCompletedByOrderId(ORDER_ID, TENANT)).thenReturn(1L);
        when(orderShipmentMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(new ArrayList<>());

        assertThat(service.ship(ORDER_ID, shipBody(), TENANT, KEY, worker()).get("status"))
                .isEqualTo("shipped");
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ⑤ 原子性（结构判据 + 失败传播）：@Transactional 边界 + 状态流转在最后一步
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 原子性：pack/ship/unpack 各自是**一个** @Transactional(rollbackFor=Exception) 方法")
    void mutatingEntryPointsAreTransactional() throws Exception {
        for (String name : List.of("pack", "ship", "unpack")) {
            java.lang.reflect.Method method = java.util.Arrays.stream(
                            OrderShipmentService.class.getDeclaredMethods())
                    .filter(m -> m.getName().equals(name) && !m.isSynthetic())
                    .findFirst()
                    .orElseThrow(() -> new AssertionError("OrderShipmentService 缺方法 " + name));
            org.springframework.transaction.annotation.Transactional tx =
                    method.getAnnotation(org.springframework.transaction.annotation.Transactional.class);
            assertThat(tx).as("%s 必须是一个事务边界（否则「明细写了但状态没变」会出现）", name).isNotNull();
            assertThat(tx.rollbackFor())
                    .as("%s 必须对所有异常回滚（默认只回滚 RuntimeException —— 漏了 checked 就是半状态）", name)
                    .contains(Exception.class);
        }
    }

    @Test
    @DisplayName("🔴 原子性：状态流转失败（并发变更）⇒ 抛 ⇒ 整笔回滚（不吞成「发货成功」）")
    void shipPropagatesStatusTransitionFailure() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("packed"));
        givenOrderItems(plainItem());
        when(orderShipmentMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(new ArrayList<>());
        when(orderMapper.update(isNull(), any())).thenReturn(0); // 并发变更：状态没被改

        assertThatThrownBy(() -> service.ship(ORDER_ID, shipBody(), TENANT, KEY, worker()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("并发变更");
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ⑥ 幂等：同键重放不重复记明细、不重复流转
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 幂等：同键重放 ⇒ 不重复记明细、不重复流转，回放首次结果并打 replayed 标记")
    void sameKeyReplaysWithoutDuplicateWrites() {
        when(clientRequestIdService.claim(TENANT, KEY, OrderShipmentService.ENDPOINT_SHIP))
                .thenReturn(false);
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("status", "shipped");
        when(clientRequestIdService.replay(TENANT, KEY, Map.class))
                .thenReturn(java.util.Optional.of(snapshot));

        Map<String, Object> result = service.ship(ORDER_ID, shipBody(), TENANT, KEY, worker());

        assertThat(result.get(OrderShipmentService.REPLAYED_KEY)).isEqualTo(Boolean.TRUE);
        assertThat(result.get("status")).isEqualTo("shipped");
        verify(orderShipmentItemMapper, never()).insert(any(OrderShipmentItem.class));
        verify(orderShipmentMapper, never()).insert(any(OrderShipment.class));
        verify(orderMapper, never()).update(isNull(), any());
    }

    @Test
    @DisplayName("幂等 fail-closed：占位在飞/已失败（无快照）⇒ 409，不返回空结果（不静默当成功）")
    void inFlightKeyFailsClosed() {
        when(clientRequestIdService.claim(TENANT, KEY, OrderShipmentService.ENDPOINT_SHIP))
                .thenReturn(false);
        when(clientRequestIdService.replay(TENANT, KEY, Map.class))
                .thenReturn(java.util.Optional.empty());

        assertThatThrownBy(() -> service.ship(ORDER_ID, shipBody(), TENANT, KEY, worker()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("正在处理中");
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ⑦ 跨租户：A 租户的工人发不了 B 租户的单
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 跨租户：租户 A 的工人不能为租户 B 的订单发货（查不到 ⇒ 零写）")
    void crossTenantShipmentIsRejectedWithZeroWrites() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("packed")); // 属于 TENANT
        assertThatThrownBy(() -> service.ship(ORDER_ID, shipBody(), OTHER_TENANT, KEY, worker()))
                .isInstanceOf(BusinessException.class);

        verify(orderShipmentMapper, never()).insert(any(OrderShipment.class));
        verify(orderShipmentItemMapper, never()).insert(any(OrderShipmentItem.class));
        verify(orderMapper, never()).update(isNull(), any());
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ⑧ 撤销打包：可撤销，但必须带理由 + 留痕；商家侧无理由回退做不到
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 撤销打包：packed → producing 且留下理由 + 谁拆的包")
    void unpackLeavesTraceAndRequiresReason() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("packed"));
        OrderShipment packed = OrderShipment.builder().id("ship-1").tenantId(TENANT)
                .orderId(ORDER_ID).shipmentNo("SH1").source(OrderShipmentService.SOURCE_WORKER)
                .packedAt(OffsetDateTime.now()).packedByWorkerId(WORKER_ID).build();
        when(orderShipmentMapper.selectByOrderId(ORDER_ID, TENANT))
                .thenReturn(new ArrayList<>(List.of(packed)));

        Map<String, Object> result = service.unpack(ORDER_ID, "装错单了，拆开重打", TENANT, KEY, worker());

        assertThat(result.get("status")).isEqualTo("producing");
        org.mockito.ArgumentCaptor<OrderShipment> captor =
                org.mockito.ArgumentCaptor.forClass(OrderShipment.class);
        verify(orderShipmentMapper).updateById(captor.capture());
        assertThat(captor.getValue().getUnpackReason()).isEqualTo("装错单了，拆开重打");
        assertThat(captor.getValue().getUnpackedByWorkerId()).isEqualTo(WORKER_ID);
        assertThat(captor.getValue().getUnpackedAt()).isNotNull();
        assertThat(captor.getValue().getPackedAt()).isNull();
        verify(orderMapper).update(isNull(), any());
    }

    @Test
    @DisplayName("🔴 撤销打包必须带理由（不留痕不给撤 —— 已打包是涉责任状态）")
    void unpackWithoutReasonIsRejected() {
        assertThatThrownBy(() -> service.unpack(ORDER_ID, "  ", TENANT, KEY, worker()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("理由");
        verify(orderShipmentMapper, never()).updateById(any(OrderShipment.class));
    }

    @Test
    @DisplayName("🔴 商家侧那条无理由的状态端点**做不到**撤销打包（目标状态不在状态表里）")
    void merchantPathCannotRevertPackedWithoutReason() {
        assertThatThrownBy(() -> OrderStatusTransitions.assertTransitionAllowed("packed", "producing"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许");
        // 反向护栏：packed → shipped 仍在表里（撤销打包**不是**为了绕开发货）
        OrderStatusTransitions.assertTransitionAllowed("packed", "shipped");
    }

    @Test
    @DisplayName("仅「已打包」可撤销（producing/shipped 都拒 —— 撤销不是万能回退）")
    void unpackOnlyFromPacked() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        assertThatThrownBy(() -> service.unpack(ORDER_ID, "理由", TENANT, KEY, worker()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已打包");
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ⑨ 缺值不猜：数量 / 单位 / 订单行归属
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 缺值不猜：实发数量非正 / 单位缺失 / 明细为空 ⇒ 一律拒（不编造）")
    void missingValuesAreNeverGuessed() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("packed"));
        givenOrderItems(plainItem());

        Map<String, Object> empty = shipBody();
        empty.put("items", List.of());
        assertThatThrownBy(() -> service.ship(ORDER_ID, empty, TENANT, KEY, worker()))
                .isInstanceOf(BusinessException.class).hasMessageContaining("发货明细不能为空");

        Map<String, Object> zero = shipBody();
        zero.put("items", List.of(new LinkedHashMap<>(Map.of(
                "order_item_id", ITEM_ID, "shipped_quantity", BigDecimal.ZERO, "unit", "米"))));
        assertThatThrownBy(() -> service.ship(ORDER_ID, zero, TENANT, KEY, worker()))
                .isInstanceOf(BusinessException.class).hasMessageContaining("正数");

        Map<String, Object> noUnit = shipBody();
        noUnit.put("items", List.of(new LinkedHashMap<>(Map.of(
                "order_item_id", ITEM_ID, "shipped_quantity", new BigDecimal("10")))));
        assertThatThrownBy(() -> service.ship(ORDER_ID, noUnit, TENANT, KEY, worker()))
                .isInstanceOf(BusinessException.class).hasMessageContaining("单位");

        Map<String, Object> foreignItem = shipBody();
        foreignItem.put("items", List.of(new LinkedHashMap<>(Map.of(
                "order_item_id", "item-from-another-order",
                "shipped_quantity", new BigDecimal("1"), "unit", "件"))));
        assertThatThrownBy(() -> service.ship(ORDER_ID, foreignItem, TENANT, KEY, worker()))
                .isInstanceOf(BusinessException.class).hasMessageContaining("不属于该订单");
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ⑩ 读面：实发套/件/卷（#5651 消费的**唯一**真值）
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 读面直接回答「实际发了几套/几件/几卷」：套数、卷数只对填过的行求和，空值不当 0")
    void readShipmentAnswersActualShippedTotals() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("shipped"));
        OrderShipment s = OrderShipment.builder().id("ship-1").tenantId(TENANT).orderId(ORDER_ID)
                .shipmentNo("SH1").source(OrderShipmentService.SOURCE_WORKER_PHOTO)
                .photoRefs(List.of("https://cdn/x.jpg")).build();
        when(orderShipmentMapper.selectByOrderId(ORDER_ID, TENANT))
                .thenReturn(new ArrayList<>(List.of(s)));
        when(orderShipmentItemMapper.selectByShipmentId("ship-1", TENANT)).thenReturn(new ArrayList<>(List.of(
                OrderShipmentItem.builder().tenantId(TENANT).orderId(ORDER_ID).orderItemId(ITEM_ID)
                        .productName("遮光窗帘").shippedQuantity(new BigDecimal("10.00"))
                        .unit("米").rollCount(2).build(),
                OrderShipmentItem.builder().tenantId(TENANT).orderId(ORDER_ID).orderItemId("item-2")
                        .productName("纱帘").shippedQuantity(new BigDecimal("3.00"))
                        .unit("件").setCount(3).build())));

        Map<String, Object> read = service.readShipment(ORDER_ID, TENANT);

        assertThat(read.get("status")).isEqualTo("shipped");
        @SuppressWarnings("unchecked")
        Map<String, Object> totals = (Map<String, Object>) read.get("shipped_totals");
        assertThat(totals.get("set_count")).isEqualTo(new BigDecimal("3"));
        assertThat(totals.get("roll_count")).isEqualTo(new BigDecimal("2"));
        @SuppressWarnings("unchecked")
        Map<String, BigDecimal> byUnit = (Map<String, BigDecimal>) totals.get("by_unit");
        assertThat(byUnit.get("米")).isEqualByComparingTo("10.00");
        assertThat(byUnit.get("件")).isEqualByComparingTo("3.00");
        assertThat(read.get("shipments")).isNotNull();
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ⑪ 识别链：复用 #5321/#5052 的 vision 基建，只换 target（只认 shipment）
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 识别走**同一份** vision 基建（不新造第二条链），target 只认 shipment")
    void recognizeReusesTheSharedVisionKernelWithShipmentTarget() {
        when(imageRecognitionClient.recognize(any(), any())).thenReturn(null);

        service.recognize(List.of("https://cdn/label.jpg"));

        verify(imageRecognitionClient).recognize("shipment", List.of("https://cdn/label.jpg"));
    }
}
