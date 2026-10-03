// case_ids: PG-070
package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.dto.NotificationQueryRequest;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.security.PaginationParamInterceptor;
import com.migao.admin.validation.PaginationParamGate;
import com.migao.admin.service.NotificationService;
import com.migao.admin.service.OrderLogisticsService;
import com.migao.admin.service.OrderService;
import com.migao.admin.service.OrderShipmentService;
import com.migao.admin.service.StockLedgerService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.clearInvocations;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * issue #6222 **实例判据**（真 MVC 分发链 + 真 {@link PaginationParamInterceptor} +
 * 真 {@link GlobalExceptionHandler}）：列表读端点的非法分页入参 ⇒ **400**，
 * 且 **service 一次都没被调用**。
 *
 * <h2>修前的读数（本单的 bug，逐字）</h2>
 * <pre>
 * GET /api/admin/orders?page=1&amp;size=-5       ⇒ HTTP 200  data.total=0  data.items 长度=359
 * GET /api/admin/after-sales?page=1&amp;size=-5  ⇒ HTTP 200  data.total=0  data.items 长度=5
 * GET /api/admin/stock-ledger?page=1&amp;size=-5 ⇒ HTTP 200  data.total=0  data.items 长度=389
 * </pre>
 * 机制：MyBatis-Plus 的 {@code PaginationInnerInterceptor} 把负数 size 当「不查 count、不追加 LIMIT」
 * ⇒ 返回整表 + {@code total} 停在默认 0（客户端分页器据此判定「已到末页」⇒ 有数据却显示为空）。
 *
 * <h2>三个入口形态各取一个代表（本单「同一缺陷散在 N 个入口」的抽样）</h2>
 * <ul>
 *   <li>{@code OrderController#getOrders} —— DTO 无关的 {@code @RequestParam long size} 族；</li>
 *   <li>{@code StockLedgerController#getLedger} —— 同族 + 可选 {@code Long skuId}（确认不是只有订单面）；</li>
 *   <li>{@code NotificationController#getNotifications} —— 同族（通知面）。</li>
 * </ul>
 * 三个族的**共同点**才是本单的修复面：它们都经同一个 HTTP 参数集 ⇒ 单点准入（见
 * {@link PaginationParamGate}）。查询 DTO 族（{@code ProductQueryRequest} 等，属性名不保证等于
 * HTTP 参数名）由类级元守卫 {@code tests/unit_ci_workflows/test_pagination_param_gate.py} 覆盖。
 *
 * <h2>正对照（判据非空自证：不是「什么都拒」）</h2>
 * {@link #legalPageSize_stillReturns200()} —— 同一个端点、同一份装配，把 {@code size} 换成合法值
 * ⇒ 200 + service 真被调用；{@link #withoutTheInterceptor_theSameRequestIsNotRejected()} 把闸摘掉
 * ⇒ 同一请求当场不再 400 ⇒ 上面那三条 400 的读数**来自本包的接线**，不是空断言。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("#6222 列表端点非法分页入参 ⇒ 400（service 零调用）")
class PaginationParamGateEndpointTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock private OrderService orderService;
    @Mock private OrderLogisticsService orderLogisticsService;
    @Mock private OrderShipmentService orderShipmentService;
    @Mock private StockLedgerService stockLedgerService;
    @Mock private NotificationService notificationService;

    private OrderController orderController;
    private StockLedgerController stockLedgerController;
    private NotificationController notificationController;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        orderController = new OrderController(orderService, orderLogisticsService, orderShipmentService);
        stockLedgerController = new StockLedgerController(stockLedgerService);
        notificationController = new NotificationController(notificationService);
        mockMvc = withGate();
    }

    @Override
    @org.junit.jupiter.api.AfterEach
    void baseTearDown() {
        super.baseTearDown();
    }

    /** 与生产同构的装配：真控制器 + 真闸 + 真异常处理器（顺序同 WebConfig —— 闸在授权之后）。 */
    private MockMvc withGate() {
        return MockMvcBuilders.standaloneSetup(orderController, stockLedgerController, notificationController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .addInterceptors(new PaginationParamInterceptor())
                .build();
    }

    /** 把闸摘掉 —— 用于证明那些 400 来自本包的接线。 */
    private MockMvc withoutGate() {
        return MockMvcBuilders.standaloneSetup(orderController, stockLedgerController, notificationController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    private void stubEmptyPages() {
        when(orderService.getOrderPage(anyLong(), anyLong(), any(), any(), any(), any(), any(), any(),
                any(), any(), any(), any(), any(), any(), any())).thenReturn(PageResponse.of(0L, 1L, 20L, List.of()));
        when(stockLedgerService.getLedgerPage(any(), any(), any(), any(), anyLong(), anyLong()))
                .thenReturn(PageResponse.of(0L, 1L, 20L, List.of()));
        when(notificationService.queryNotifications(anyString(), any(NotificationQueryRequest.class)))
                .thenReturn(PageResponse.of(0L, 1L, 20L, List.of()));
    }

    // ────────────────────────── ① size<0 ⇒ 400 + service 零调用 ──────────────────────────

    @Test
    @DisplayName("🔴 GET /api/admin/orders?page=1&size=-5 ⇒ 400（修前 200 + total=0 + 整页行）")
    void orders_negativeSize_isBadRequest() throws Exception {
        mockMvc.perform(get("/api/admin/orders").param("page", "1").param("size", "-5"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.details[0].field").value("size"));
        verifyNoInteractions(orderService);
    }

    @Test
    @DisplayName("🔴 GET /api/admin/stock-ledger?page=1&size=-5 ⇒ 400（同族的另一个端点）")
    void stockLedger_negativeSize_isBadRequest() throws Exception {
        mockMvc.perform(get("/api/admin/stock-ledger").param("page", "1").param("size", "-5"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.details[0].field").value("size"));
        verifyNoInteractions(stockLedgerService);
    }

    @Test
    @DisplayName("🔴 GET /api/admin/notifications?page=1&size=-5 ⇒ 400（通知面同族）")
    void notifications_negativeSize_isBadRequest() throws Exception {
        mockMvc.perform(get("/api/admin/notifications").param("page", "1").param("size", "-5"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.details[0].field").value("size"));
        verifyNoInteractions(notificationService);
    }

    // ────────────────────────── ② page<1 ⇒ 400（同族非法下界） ──────────────────────────

    @Test
    @DisplayName("🔴 GET /api/admin/orders?page=-1&size=20 ⇒ 400，field=page")
    void orders_nonPositivePage_isBadRequest() throws Exception {
        mockMvc.perform(get("/api/admin/orders").param("page", "-1").param("size", "20"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.details[0].field").value("page"));
        verifyNoInteractions(orderService);
    }

    @Test
    @DisplayName("🔴 size 非整数（size=abc）⇒ 400（不落兜底 500，且与类型不符同形）")
    void orders_nonNumericSize_isBadRequest() throws Exception {
        mockMvc.perform(get("/api/admin/orders").param("page", "1").param("size", "abc"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"));
        verifyNoInteractions(orderService);
    }

    // ────────────────────────── ③ 正对照：合法入参逐字不变 ──────────────────────────

    @Test
    @DisplayName("✅ 正对照：同一端点 size=20 ⇒ 200 + service 真被调用（不是「什么都拒」）")
    void legalPageSize_stillReturns200() throws Exception {
        stubEmptyPages();
        mockMvc.perform(get("/api/admin/orders").param("page", "1").param("size", "20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.total").value(0))
                .andExpect(jsonPath("$.data.size").value(20));
        verify(orderService).getOrderPage(anyLong(), anyLong(), any(), any(), any(), any(), any(), any(),
                any(), any(), any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("✅ size=0 仍合法（零行 + 真 total ⇒ 语义自洽，不是本次要拒的形态）")
    void zeroSize_isAccepted() throws Exception {
        stubEmptyPages();
        mockMvc.perform(get("/api/admin/orders").param("page", "1").param("size", "0"))
                .andExpect(status().isOk());
    }

    @Test
    @DisplayName("✅ 不带分页参数 ⇒ 200（默认值路径不受影响）")
    void withoutPagingParams_stillReturns200() throws Exception {
        stubEmptyPages();
        mockMvc.perform(get("/api/admin/orders")).andExpect(status().isOk());
        verify(orderService).getOrderPage(anyLong(), anyLong(), any(), any(), any(), any(), any(), any(),
                any(), any(), any(), any(), any(), any(), any());
    }

    // ────────────────────────── ④ 摘线对照（判据非空自证） ──────────────────────────

    @Test
    @DisplayName("🔬 摘掉闸 ⇒ 同一请求不再 400（证明上面三条 400 来自本包的接线）")
    void withoutTheInterceptor_theSameRequestIsNotRejected() throws Exception {
        stubEmptyPages();
        // 注意：test-only 的「无闸」装配 —— 只用于本对照，不改变生产装配
        MockMvc ungated = withoutGate();
        ungated.perform(get("/api/admin/orders").param("page", "1").param("size", "-5"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(0));
        // 清掉上面那次调用（无闸路径**会**打到 service —— 这正是修前的行为）
        clearInvocations(orderService);
        // 反向：有闸装配下同一请求是 400，且 service 零调用
        mockMvc.perform(get("/api/admin/orders").param("page", "1").param("size", "-5"))
                .andExpect(status().isBadRequest());
        verify(orderService, never()).getOrderPage(anyLong(), anyLong(), any(), any(), any(), any(), any(),
                any(), any(), any(), any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("✅ 参数名大小写不敏感：?SIZE=-5 同样 400")
    void upperCaseSize_isRejected() throws Exception {
        mockMvc.perform(get("/api/admin/orders").param("SIZE", "-5"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.details[0].field").value("SIZE"));
        verifyNoInteractions(orderService);
    }
}
