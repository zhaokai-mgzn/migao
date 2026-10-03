// case_ids: AS-013
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.controller.OrderController;
import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingFeeCombinationMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.hamcrest.Matchers.containsString;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 退款金额**小数位准入**（issue #6221）：`PUT /api/admin/orders/{id}/refund` 的 `refund_amount`
 * 此前只校 `>= 0` 与 `<= 实收`，**不校小数位数**，而库列是 `NUMERIC(·,2)`
 * （`orders.refund_amount` / `finance_transactions.amount` 均 `NUMERIC(12,2)`）⇒ `0.001` 得 200，
 * 写库时被 PG 舍成 `0.00`：**订单与资金流水两处同时静默归零，`refund_at` 却已写入**。
 *
 * <h2>本文件按铁律 8 分两层</h2>
 * <ol>
 *   <li><b>实例判据</b>（本文件）：`0.001 / 0.004 / 0.005 / 0.009` ⇒ **422 显式拒绝**且
 *       订单与流水**零写入**、`refund_at` 不写；`0.01`（正对照）⇒ 200 且**订单与流水两侧逐字相等**；
 *       退款封顶（累计 ≤ 实收）与状态白名单**一字未动**（正对照）。</li>
 *   <li><b>类级元守卫</b>：{@code MoneyEntryPrecisionMetaGuardTest}（全仓金额入口扫描，
 *       未登记即红 / 豁免台账只许缩短）。</li>
 * </ol>
 *
 * <h2>「两侧逐字相等」怎么在本层判（无真库时的口径）</h2>
 * 订单侧走 `UpdateWrapper.setSql("refund_amount = COALESCE(refund_amount, 0) + <applied>")`
 * ⇒ 捕获 wrapper 的 SQL 字面量；流水侧走 `FinanceTransaction.amount` ⇒ 捕获实体。
 * 两处都取 `toPlainString()` 逐字比对（`0.01` 就是 `0.01`，不是 `1E-2`、不是 `0.010`）。
 * ⚠️ 边界（如实登记）：本层证明的是**送进 SQL/实体的字面量**；库层的 `numeric(12,2)` 落值
 * 证据见 issue #6221 的逐字读数（`0.01 ⇒ 两侧 0.01`、`0.001 ⇒ 两侧 0`），本包不另起真库腿。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("退款金额小数位准入（issue #6221）")
class OrderRefundMoneyPrecisionTest {

    private static final String ORDER_ID = "abcd0001-0000-0000-0000-000000000001";

    @InjectMocks
    private OrderService orderService;

    @Mock
    private UserService userService;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private StockBatchConsumptionService stockBatchConsumptionService;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private OrderLogisticsMapper orderLogisticsMapper;
    @Mock
    private ProductMapper productMapper;
    @Mock
    private ProductSkuMapper productSkuMapper;
    @Mock
    private FinanceTransactionMapper financeTransactionMapper;
    @org.mockito.Spy
    private ObjectMapper objectMapper = new ObjectMapper();
    @Mock
    private NotificationService notificationService;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private StockLedgerService stockLedgerService;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    @Mock
    private ProcessingFeeCombinationMapper processingFeeCombinationMapper;
    @Mock
    private ProductionRouteRuleMapper routeRuleMapper;
    @Mock
    private ProcessingFeeCombinationCommandService processingFeeCombinationCommandService;
    @Mock
    private OrderLogisticsService orderLogisticsService;
    @Mock
    private OrderShipmentService orderShipmentService;

    private MockMvc mockMvc;
    private Order testOrder;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
        // 字段注入面（与 OrderServiceTest 同装配）：@InjectMocks 只做构造注入
        ReflectionTestUtils.setField(orderService, "processingFeeCalculator",
                new ProcessingFeeCalculator(processingFeeCombinationMapper, routeRuleMapper));
        ReflectionTestUtils.setField(orderService, "stockBatchConsumptionService",
                stockBatchConsumptionService);
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);

        testOrder = Order.builder()
                .id(ORDER_ID)
                .tenantId(1L)
                .orderNo("ORD-20260801-0001")
                .customerName("张三")
                .customerPhone("13800138000")
                .customerAddress("北京市朝阳区")
                .totalAmount(new BigDecimal("599.00"))
                .actualAmount(new BigDecimal("599.00"))
                .status("confirmed")
                .remark("退款精度判据")
                .build();

        mockMvc = MockMvcBuilders
                .standaloneSetup(new OrderController(orderService, orderLogisticsService, orderShipmentService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ════════════════ ① 实例判据：超 2 位小数 ⇒ 422 且零写入 ════════════════

    @Test
    @DisplayName("0.001（3 位小数）⇒ 422 显式拒绝：订单与资金流水零写入、refund_at 不写")
    void refundOrder_threeDecimals_isRejectedWithNoWrites() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(testOrder);
        // 修前形态对照用：不加准入时这条 update 会**真被执行**（返回 1 = 落库成功，200）
        when(orderMapper.update(any(), any(UpdateWrapper.class))).thenReturn(1);

        assertThatThrownBy(() -> orderService.refundOrder(ORDER_ID, new BigDecimal("0.001"), "子分级退款"))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(e.getMessage())
                            .contains("退款金额")
                            .contains("最多支持 2 位小数")
                            .contains("0.001");
                });

        // 订单**一字未改**：不落退款额、不写退款时间、不动库
        verify(orderMapper, never()).update(any(), any(UpdateWrapper.class));
        // 资金流水**零新增**（修前：1 行 amount=0 —— "退款成功"却一分未落）
        verify(financeTransactionMapper, never()).insert(any(FinanceTransaction.class));
        assertThat(testOrder.getRefundAmount()).isNull();
        assertThat(testOrder.getRefundAt()).isNull();
    }

    @Test
    @DisplayName("HTTP 入口同判据：PUT /refund {refund_amount:0.001} ⇒ 422（走 controller→service 全链）")
    void refundEndpoint_threeDecimals_is4xx() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(testOrder);
        when(orderMapper.update(any(), any(UpdateWrapper.class))).thenReturn(1);

        mockMvc.perform(put("/api/admin/orders/{id}/refund", ORDER_ID)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"refund_amount\":0.001,\"refund_reason\":\"子分级退款\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(content().string(containsString("最多支持 2 位小数")));

        verify(orderMapper, never()).update(any(), any(UpdateWrapper.class));
        verify(financeTransactionMapper, never()).insert(any(FinanceTransaction.class));
    }

    @Test
    @DisplayName("子分级值 0.004 / 0.005 / 0.009 一律 422（修前：200 + PG 半进位静默取整）")
    void refundOrder_subCentAmounts_areAllRejected() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(testOrder);
        when(orderMapper.update(any(), any(UpdateWrapper.class))).thenReturn(1);

        for (String raw : List.of("0.004", "0.005", "0.009")) {
            assertThatThrownBy(() -> orderService.refundOrder(ORDER_ID, new BigDecimal(raw), null))
                    .as("子分级退款额 %s 必须被显式拒绝", raw)
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("最多支持 2 位小数");
        }
        verify(orderMapper, never()).update(any(), any(UpdateWrapper.class));
        verify(financeTransactionMapper, never()).insert(any(FinanceTransaction.class));
    }

    // ════════════════ ② 正对照：0.01 仍成功且两侧逐字相等 ════════════════

    @Test
    @DisplayName("正对照 0.01：200 且 orders.refund_amount 与 finance_transactions.amount 逐字相等")
    void refundOrder_oneCent_succeedsWithBothSidesLiterallyEqual() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(testOrder);
        when(orderMapper.update(any(), any(UpdateWrapper.class))).thenReturn(1);

        mockMvc.perform(put("/api/admin/orders/{id}/refund", ORDER_ID)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"refund_amount\":0.01,\"refund_reason\":\"退一分\"}"))
                .andExpect(status().isOk());

        ArgumentCaptor<UpdateWrapper<Order>> wrapperCaptor = ArgumentCaptor.forClass(UpdateWrapper.class);
        verify(orderMapper).update(isNull(), wrapperCaptor.capture());
        String sqlSet = String.valueOf(wrapperCaptor.getValue().getSqlSet());
        assertThat(sqlSet).as("订单侧写库字面量").contains("refund_amount = COALESCE(refund_amount, 0) + 0.01");

        ArgumentCaptor<FinanceTransaction> txnCaptor = ArgumentCaptor.forClass(FinanceTransaction.class);
        verify(financeTransactionMapper).insert(txnCaptor.capture());
        assertThat(txnCaptor.getValue().getType()).isEqualTo("refund");
        assertThat(txnCaptor.getValue().getAmount().toPlainString()).as("流水侧金额字面量").isEqualTo("0.01");
        assertThat(testOrder.getRefundAmount().toPlainString()).as("内存订单对象").isEqualTo("0.01");
    }

    @Test
    @DisplayName("正对照 null：仍按**全额退款**（准入不得把「未传」归一成退 0 元）")
    void refundOrder_nullAmount_stillMeansFullRefund() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(testOrder);
        when(orderMapper.update(any(), any(UpdateWrapper.class))).thenReturn(1);

        orderService.refundOrder(ORDER_ID, null, "全额退款");

        assertThat(testOrder.getRefundAmount()).isEqualByComparingTo("599.00");
        assertThat(testOrder.getRefundAt()).isNotNull();
        ArgumentCaptor<FinanceTransaction> txnCaptor = ArgumentCaptor.forClass(FinanceTransaction.class);
        verify(financeTransactionMapper).insert(txnCaptor.capture());
        assertThat(txnCaptor.getValue().getAmount().toPlainString()).isEqualTo("599.00");
    }

    // ════════════════ ③ 既有两个守卫未回退（封顶 / 状态白名单）════════════════

    @Test
    @DisplayName("正对照 封顶不动：已有退款 400 再退 300 ⇒ 累计封顶实收 599、本次流水 199")
    void refundOrder_accumulatedCapUnchanged() {
        testOrder.setRefundAmount(new BigDecimal("400.00"));
        when(orderMapper.selectById(ORDER_ID)).thenReturn(testOrder);
        when(orderMapper.update(any(), any(UpdateWrapper.class))).thenReturn(1);

        orderService.refundOrder(ORDER_ID, new BigDecimal("300.00"), "再次退款");

        assertThat(testOrder.getRefundAmount()).isEqualByComparingTo("599.00");
        ArgumentCaptor<FinanceTransaction> txnCaptor = ArgumentCaptor.forClass(FinanceTransaction.class);
        verify(financeTransactionMapper).insert(txnCaptor.capture());
        assertThat(txnCaptor.getValue().getAmount().toPlainString()).isEqualTo("199.00");
    }

    @Test
    @DisplayName("正对照 状态白名单不动：pending 订单 ⇒ 422「不允许退款」且零写入")
    void refundOrder_statusWhitelistUnchanged() {
        Order pending = Order.builder().id(ORDER_ID).tenantId(1L).orderNo("ORD-20260801-0002")
                .totalAmount(new BigDecimal("599.00")).actualAmount(new BigDecimal("599.00"))
                .status("pending").build();
        when(orderMapper.selectById(ORDER_ID)).thenReturn(pending);

        assertThatThrownBy(() -> orderService.refundOrder(ORDER_ID, new BigDecimal("0.01"), null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许退款");
        verify(orderMapper, never()).update(any(), any(UpdateWrapper.class));
        verify(financeTransactionMapper, never()).insert(any(FinanceTransaction.class));
    }
}
