// case_ids: OR-051, DF-024
package com.migao.admin.shipment;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.controller.OrderController;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderShipment;
import com.migao.admin.entity.OrderShipmentItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.OrderShipmentItemMapper;
import com.migao.admin.mapper.OrderShipmentMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ImageRecognitionClient;
import com.migao.admin.service.OrderShipmentService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;

import java.lang.annotation.Annotation;
import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.when;

/**
 * 🔴 <b>管理端（商家/桌面）发货读面</b>（issue #5651 收口）：{@code GET /api/admin/orders/{id}/shipments}。
 *
 * <h3>它补的是哪一个洞（issue #5651「挂链差一步」的原文）</h3>
 * <p>{@code order_shipment_items}（issue #5648）是「这一单实际发了多少」的<b>唯一真值载体</b>，
 * 但它落地时<b>只有工人读面</b>（{@code GET /api/worker/shipment/orders/{orderId}}，工人 session 准入）
 * ⇒ admin-web（销售单三联纸跑在那里）<b>拿不到实发数量</b>，销售单的数量列只能退回订单行数量。
 * 本类钉住补上的那一面，以及它的三条边界。</p>
 *
 * <h3>四条判据（每条都有注入式红证，见 {@code scripts/shipment-admin-read-red-proof.py}）</h3>
 * <ol>
 *   <li><b>路径形态与同族一致</b>：admin 订单子资源是 {@code /api/admin/orders/{id}/<子资源>}
 *       （既有 {@code /follow-status}、{@code /logistics}、{@code /refund}）⇒ 本面 = {@code /shipments}，
 *       且 {@code {id}} 带既有 UUID 正则约束（字面路径不被误吃）。</li>
 *   <li><b>权限码 = {@code order:list}</b>：与<b>同页既有读面</b> {@code GET /api/admin/orders/{id}}
 *       同一个码 —— 页面读得开、单据读不开是比"没有读面"更坏的形态（#4727 权限注解面审计）。
 *       红证：删掉 {@code @RequirePermission} ⇒ 本判据红，且
 *       {@code tests/unit_ci_workflows/test_agent_permission_parity.py} 判据 8（未注解端点必须登记）也红。</li>
 *   <li><b>只读</b>：GET 一个动词，没有 POST/PUT/PATCH/DELETE 落在该路径上（本单不新增写面）。</li>
 *   <li><b>跨租户 ⇒ 404 且与「不存在」逐字同一形态</b>（不泄露存在性）：别的租户的订单与不存在的订单
 *       必须给出<b>同一个</b> {@code code}/{@code message}/{@code httpStatus}。
 *       红证：把跨租户分支改成 403（{@code authFailed}）或让消息带上「跨租户」⇒ 本判据当场红。</li>
 * </ol>
 *
 * <p>⚠️ 本类断言的是<b>面</b>与<b>租户边界</b>；「实发套/件/卷」的算法口径由
 * {@code OrderShipmentServiceTest}（工人面同一份实现）负责 —— 两端共用
 * {@link OrderShipmentService#readShipment}，本类只证「第二面真的挂上了、且没有另造一份形状」。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("管理端发货读面：路径同族 / order:list / 只读 / 跨租户 404 不泄露存在性")
class AdminOrderShipmentReadTest {

    private static final long TENANT = 1L;
    private static final long OTHER_TENANT = 2L;
    private static final String ORDER_ID = "11111111-1111-1111-1111-111111111111";
    private static final String ITEM_ID = "22222222-2222-2222-2222-222222222222";

    @Mock private OrderMapper orderMapper;
    @Mock private OrderItemMapper orderItemMapper;
    @Mock private OrderLogisticsMapper orderLogisticsMapper;
    @Mock private OrderShipmentMapper orderShipmentMapper;
    @Mock private OrderShipmentItemMapper orderShipmentItemMapper;
    @Mock private ProcessingOrderMapper processingOrderMapper;
    @Mock private ClientRequestIdService clientRequestIdService;
    @Mock private ImageRecognitionClient imageRecognitionClient;

    private OrderShipmentService service() {
        return new OrderShipmentService(orderMapper, orderItemMapper, orderLogisticsMapper,
                orderShipmentMapper, orderShipmentItemMapper, processingOrderMapper,
                clientRequestIdService, imageRecognitionClient, new ObjectMapper());
    }

    private Order order(long tenantId) {
        Order order = new Order();
        order.setId(ORDER_ID);
        order.setTenantId(tenantId);
        order.setOrderNo("CSO260927-0001");
        order.setStatus("shipped");
        return order;
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ① 路径形态：admin 订单子资源同族
    // ══════════════════════════════════════════════════════════════════════════

    /** 读面方法（按 `@GetMapping` 的 `/shipments` 后缀定位；找不到 ⇒ 本单要补的那一面不存在）。 */
    private Method readEndpoint() {
        return Arrays.stream(OrderController.class.getDeclaredMethods())
                .filter(m -> m.getAnnotation(GetMapping.class) != null)
                .filter(m -> Arrays.stream(m.getAnnotation(GetMapping.class).value())
                        .anyMatch(v -> v.endsWith("/shipments")))
                .findFirst()
                .orElseThrow(() -> new AssertionError(
                        "admin 端**没有**发货读面（GET /api/admin/orders/{id}/shipments）—— "
                                + "这正是 issue #5651 的「挂链差一步」：order_shipment_items 只有工人读面，"
                                + "admin-web 拿不到实发数量 ⇒ 销售单的数量列只能是订单行投影"));
    }

    @Test
    @DisplayName("🔴 路径形态与同族一致：/api/admin/orders/{id}/shipments（UUID 约束 + admin 订单子资源）")
    void adminReadFaceLivesOnTheAdminOrderSubResourcePath() {
        RequestMapping classMapping = OrderController.class.getAnnotation(RequestMapping.class);
        assertThat(classMapping).as("类级 @RequestMapping 必须存在（否则路径由方法拼，机械核对无从下手）")
                .isNotNull();
        assertThat(classMapping.value()[0])
                .as("发货读面必须挂在 admin 订单面下（工人面 /api/worker/shipment/** 对桌面端不可达）")
                .isEqualTo("/api/admin/orders");

        GetMapping mapping = readEndpoint().getAnnotation(GetMapping.class);
        assertThat(mapping.value())
                .as("子资源路径形态照既有同族（/follow-status、/logistics、/refund）：{id}/<子资源>，"
                        + "且 {id} 带既有 UUID 正则约束（否则 statistics 这类字面路径会被误当 id）")
                .anySatisfy(v -> assertThat(v).contains("{id:[0-9a-fA-F-]+}"));
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ② 权限码：与同页既有读面同码（order:list）
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 权限码 = order:list（与 GET /api/admin/orders/{id} 同码；删注解 ⇒ 本判据红）")
    void adminReadFaceCarriesTheSameReadCodeAsTheOrderDetailPage() throws Exception {
        Method read = readEndpoint();
        RequirePermission code = read.getAnnotation(RequirePermission.class);
        assertThat(code)
                .as("端点必须带 @RequirePermission —— 漏注解 = 任何登录用户都能读（"
                        + "`test_agent_permission_parity.py` 判据 8 会判红：未注解端点必须登记，而本面**不该**登记豁免）")
                .isNotNull();
        assertThat(code.value())
                .as("读码取**既有**码 order:list（不新造权限码）：与同页既有读面同码 ⇒ "
                        + "不会出现「页面打得开、单据 403」的割裂；order:detail 今天只是菜单节点码、无端点承载")
                .isEqualTo("order:list");

        Method detail = Arrays.stream(OrderController.class.getDeclaredMethods())
                .filter(m -> m.getName().equals("getOrderById"))
                .findFirst().orElseThrow();
        assertThat(detail.getAnnotation(RequirePermission.class).value())
                .as("对照组：同页既有详情读面用的就是 order:list ⇒ 两读面同码（这条断言把「同码」钉成事实）")
                .isEqualTo(code.value());
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ③ 只读：本单不新增任何写面
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 只读：/shipments 只有 GET 一个动词（POST/PUT/PATCH/DELETE ⇒ 红）")
    void adminReadFaceIsReadOnly() {
        List<Class<? extends Annotation>> writers =
                List.of(PostMapping.class, PutMapping.class, PatchMapping.class, DeleteMapping.class);
        List<String> offenders = new ArrayList<>();
        for (Method m : OrderController.class.getDeclaredMethods()) {
            for (Class<? extends Annotation> writer : writers) {
                Annotation ann = m.getAnnotation(writer);
                if (ann == null) continue;
                List<String> values = new ArrayList<>();
                if (ann instanceof PostMapping p) values.addAll(List.of(p.value()));
                if (ann instanceof PutMapping p) values.addAll(List.of(p.value()));
                if (ann instanceof PatchMapping p) values.addAll(List.of(p.value()));
                if (ann instanceof DeleteMapping p) values.addAll(List.of(p.value()));
                for (String v : values) {
                    if (v.endsWith("/shipments")) offenders.add(m.getName() + " " + v);
                }
            }
        }
        assertThat(offenders)
                .as("发货读面必须是**只读**的（issue #5651 收口只补读面；写面归 #5648 的工人面）："
                        + "本单不新增任何写面")
                .isEmpty();
    }

    @Test
    @DisplayName("🔴 商家面不要求工人 session（带 X-Worker-Session-Id 参数 ⇒ 桌面端恒 401）")
    void adminReadFaceDoesNotRequireWorkerSession() {
        Method read = readEndpoint();
        List<String> headers = new ArrayList<>();
        for (Annotation[] anns : read.getParameterAnnotations()) {
            for (Annotation a : anns) {
                if (a instanceof RequestHeader rh) headers.addAll(List.of(rh.value()));
            }
        }
        assertThat(headers)
                .as("admin 读面靠商家 session（SecurityConfig 的 /api/admin/** 门禁），"
                        + "不得要求工人 session 头 —— 否则桌面端拿不到实发数量（= 本单要修的洞原地复发）")
                .doesNotContain("X-Worker-Session-Id");
    }

    // ══════════════════════════════════════════════════════════════════════════
    // ④ 租户面：租户内可取到实发；跨租户 ⇒ 404 且与「不存在」逐字同一形态
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("租户内：admin 读面拿到逐行实发（shipped_quantity / unit / set_count / roll_count）")
    void tenantScopedReadReturnsActualShippedDetails() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order(TENANT));
        OrderShipment shipment = OrderShipment.builder().id("ship-1").tenantId(TENANT).orderId(ORDER_ID)
                .shipmentNo("SH20260927000001").source(OrderShipmentService.SOURCE_WORKER_PHOTO)
                .build();
        when(orderShipmentMapper.selectByOrderId(ORDER_ID, TENANT))
                .thenReturn(new ArrayList<>(List.of(shipment)));
        when(orderShipmentItemMapper.selectByShipmentId("ship-1", TENANT)).thenReturn(new ArrayList<>(List.of(
                OrderShipmentItem.builder().tenantId(TENANT).orderId(ORDER_ID).orderItemId(ITEM_ID)
                        .productName("遮光窗帘").shippedQuantity(new BigDecimal("10.00"))
                        .unit("米").rollCount(2).build())));

        Map<String, Object> read = service().readShipment(ORDER_ID, TENANT);

        assertThat(read.get("order_id")).as("读面必须回订单号/状态，纸面据此判三态").isEqualTo(ORDER_ID);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> shipments = (List<Map<String, Object>>) read.get("shipments");
        assertThat(shipments).hasSize(1);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) shipments.get(0).get("items");
        assertThat(items)
                .as("实发明细是销售单数量列的**唯一**来源（#5648 的 owner 声明）：逐行给出实发数量与单位")
                .hasSize(1);
        assertThat(items.get(0).get("shipped_quantity")).isEqualTo(new BigDecimal("10.00"));
        assertThat(items.get(0).get("unit")).isEqualTo("米");
        assertThat(items.get(0).get("order_item_id")).isEqualTo(ITEM_ID);
        assertThat(read.get("shipped_totals")).as("汇总随读面一起给（纸面不再自算）").isNotNull();
    }

    @Test
    @DisplayName("🔴 跨租户 ⇒ 404（不是 403），且与「订单不存在」逐字同一形态（不泄露存在性）")
    void crossTenantReadIs404AndIndistinguishableFromMissingOrder() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order(TENANT));
        when(orderMapper.selectById("no-such-order")).thenReturn(null);

        BusinessException crossTenant = catchBusinessException(
                () -> service().readShipment(ORDER_ID, OTHER_TENANT));
        BusinessException missingOrder = catchBusinessException(
                () -> service().readShipment("no-such-order", OTHER_TENANT));

        assertThat(crossTenant.getHttpStatus())
                .as("跨租户必须是 404 —— 403 等于承认「这个 id 存在，只是不给你看」（存在性泄露，P2 口径）")
                .isEqualTo(404);
        assertThat(crossTenant.getHttpStatus()).isNotEqualTo(403);
        assertThat(crossTenant.getCode())
                .as("错误码两面必须同一个（否则响应体可区分「存在但越权」与「不存在」）")
                .isEqualTo(missingOrder.getCode());
        assertThat(crossTenant.getMessage())
                .as("消息必须**逐字同一形态**：任何差异（含「跨租户」这类字样）都是存在性泄露")
                .isEqualTo(missingOrder.getMessage());
    }

    private BusinessException catchBusinessException(Runnable call) {
        try {
            call.run();
        } catch (BusinessException e) {
            return e;
        }
        throw new AssertionError("预期抛出 BusinessException（跨租户 / 不存在都必须是 404 业务异常）");
    }

    @Test
    @DisplayName("红证方向自证：把跨租户改成 403 或改消息 ⇒ 上一条必红（此处钉住两种坏形态确实可区分）")
    void theTwoBadFormsAreDistinguishableFromTheCorrectOne() {
        BusinessException forbidden = BusinessException.authFailed("无权访问该订单");
        assertThat(forbidden.getHttpStatus())
                .as("坏形态 ①（403）与正确形态（404）在 httpStatus 上可区分 ⇒ 上一条断言有判别力")
                .isNotEqualTo(404);
        BusinessException leaky = new BusinessException("NOT_FOUND", "订单(跨租户)不存在", 404);
        assertThat(leaky.getMessage())
                .as("坏形态 ②（消息带上跨租户字样）与正确消息可区分 ⇒ 逐字比对有判别力")
                .isNotEqualTo(BusinessException.notFound("订单").getMessage());
        assertThatThrownBy(() -> {
            throw leaky;
        }).isInstanceOf(BusinessException.class);
    }
}
