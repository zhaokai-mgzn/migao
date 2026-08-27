package com.migao.admin.service;
// case_ids: FN-001, FN-002, FN-003

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.migao.admin.dto.FinanceSummaryResponse;
import com.migao.admin.dto.FinanceTransactionCreateRequest;
import com.migao.admin.dto.FinanceTransactionListResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.ReceivableReconciliationResponse;
import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.Order;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * FinanceService 单元测试
 */
@ExtendWith(MockitoExtension.class)
class FinanceServiceTest {

    @InjectMocks
    private FinanceService financeService;

    @Mock
    private FinanceTransactionMapper financeTransactionMapper;

    @Mock
    private OrderMapper orderMapper;

    private FinanceTransaction income1;
    private FinanceTransaction income2;
    private FinanceTransaction refund1;

    @BeforeEach
    void setUp() {
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, FinanceTransaction.class);
        TableInfoHelper.initTableInfo(assistant, Order.class);

        income1 = FinanceTransaction.builder()
                .id("t1").tenantId(1L).transactionNo("FIN-1").type("income")
                .amount(new BigDecimal("100.00")).paymentMethod("wechat").status("success")
                .occurredAt(OffsetDateTime.parse("2025-01-01T10:00:00Z")).build();
        income2 = FinanceTransaction.builder()
                .id("t2").tenantId(1L).transactionNo("FIN-2").type("income")
                .amount(new BigDecimal("50.00")).paymentMethod("alipay").status("success")
                .occurredAt(OffsetDateTime.parse("2025-01-02T10:00:00Z")).build();
        refund1 = FinanceTransaction.builder()
                .id("t3").tenantId(1L).transactionNo("FIN-3").type("refund")
                .amount(new BigDecimal("30.00")).paymentMethod("wechat").status("success")
                .occurredAt(OffsetDateTime.parse("2025-01-01T11:00:00Z")).build();
    }

    @Test
    @DisplayName("收支汇总 - 聚合收入/退款/净额/按支付方式/按日/待收款")
    void getSummary_aggregatesCorrectly() {
        // given: 流水（income1 + income2 - refund1）+ 待收款订单
        when(financeTransactionMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(income1, income2, refund1));
        Order o1 = Order.builder()
                .id("o1").tenantId(1L).orderNo("NO1")
                .totalAmount(new BigDecimal("200.00")).actualAmount(new BigDecimal("150.00"))
                .status("confirmed").build();
        when(orderMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(o1));

        // when
        FinanceSummaryResponse summary = financeService.getSummary("2025-01-01", "2025-01-31", 1L);

        // then
        assertThat(summary.getTotalIncome()).isEqualByComparingTo("150.00");
        assertThat(summary.getTotalRefund()).isEqualByComparingTo("30.00");
        assertThat(summary.getNetIncome()).isEqualByComparingTo("120.00");
        assertThat(summary.getIncomeCount()).isEqualTo(2L);
        assertThat(summary.getRefundCount()).isEqualTo(1L);
        assertThat(summary.getPendingReceivable()).isEqualByComparingTo("50.00");
        assertThat(summary.getByPaymentMethod()).hasSize(2);
        assertThat(summary.getDailyTrend()).hasSize(2);
    }

    @Test
    @DisplayName("收支汇总 - 无流水时返回零值")
    void getSummary_emptyReturnsZero() {
        when(financeTransactionMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        when(orderMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

        FinanceSummaryResponse summary = financeService.getSummary(null, null, 1L);

        assertThat(summary.getTotalIncome()).isEqualByComparingTo("0.00");
        assertThat(summary.getNetIncome()).isEqualByComparingTo("0.00");
        assertThat(summary.getByPaymentMethod()).isEmpty();
        assertThat(summary.getDailyTrend()).isEmpty();
    }

    @Test
    @DisplayName("登记流水 - 类型无效被拒绝")
    void createTransaction_invalidType() {
        FinanceTransactionCreateRequest req = new FinanceTransactionCreateRequest();
        req.setType("invalid");
        req.setAmount(new BigDecimal("10.00"));

        assertThatThrownBy(() -> financeService.createTransaction(req, 1L, "admin"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("收支类型无效");
    }

    @Test
    @DisplayName("登记流水 - 金额非正被拒绝")
    void createTransaction_invalidAmount() {
        FinanceTransactionCreateRequest req = new FinanceTransactionCreateRequest();
        req.setType("income");
        req.setAmount(new BigDecimal("0.00"));

        assertThatThrownBy(() -> financeService.createTransaction(req, 1L, "admin"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("金额必须大于 0");
    }

    @Test
    @DisplayName("登记流水 - 成功生成流水号并入库")
    void createTransaction_success() {
        FinanceTransactionCreateRequest req = new FinanceTransactionCreateRequest();
        req.setType("income");
        req.setAmount(new BigDecimal("88.00"));
        req.setPaymentMethod("cash");
        req.setRemark("线下收款");

        when(financeTransactionMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(financeTransactionMapper.insert(any(FinanceTransaction.class))).thenReturn(1);

        FinanceTransactionListResponse result = financeService.createTransaction(req, 1L, "admin");

        assertThat(result.getTransactionNo()).startsWith("FIN-");
        assertThat(result.getType()).isEqualTo("income");
        assertThat(result.getAmount()).isEqualByComparingTo("88.00");
        assertThat(result.getPaymentMethod()).isEqualTo("cash");
        verify(financeTransactionMapper).insert(any(FinanceTransaction.class));
    }

    @Test
    @DisplayName("应收对账 - 差额含已退款（应收-实收+已退）")
    void getReconciliation_computesDifference() {
        Order o1 = Order.builder()
                .id("o1").tenantId(1L).orderNo("NO1")
                .customerName("张三").customerPhone("13800138000")
                .totalAmount(new BigDecimal("200.00")).actualAmount(new BigDecimal("180.00"))
                .status("confirmed").createdAt(OffsetDateTime.parse("2025-01-01T10:00:00Z"))
                .build();
        Page<Order> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(o1));
        mockPage.setTotal(1);
        when(orderMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class))).thenReturn(mockPage);

        FinanceTransaction refund = FinanceTransaction.builder()
                .id("r1").tenantId(1L).orderId("o1").type("refund")
                .amount(new BigDecimal("20.00")).status("success").build();
        when(financeTransactionMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(refund));

        PageResponse<ReceivableReconciliationResponse> result = financeService.getReconciliation(1, 20, null, null, null, 1L);

        ReceivableReconciliationResponse item = result.getItems().get(0);
        assertThat(item.getReceivableAmount()).isEqualByComparingTo("200.00");
        assertThat(item.getReceivedAmount()).isEqualByComparingTo("180.00");
        assertThat(item.getRefundAmount()).isEqualByComparingTo("20.00");
        // 差额 = 应收 - 实收 + 已退 = 200 - 180 + 20 = 40（净应收口径）
        assertThat(item.getDifference()).isEqualByComparingTo("40.00");
    }

    @Test
    @DisplayName("应收对账 - 全额收款后退款的订单差额不再显示 0")
    void getReconciliation_refundedOrderDifferenceNotZero() {
        // given: 应收=实收=200（全额收款），已退 20 → 差额应显示 20（含已退款金额）
        Order o1 = Order.builder()
                .id("o1").tenantId(1L).orderNo("NO2")
                .customerName("李四").customerPhone("13900139000")
                .totalAmount(new BigDecimal("200.00")).actualAmount(new BigDecimal("200.00"))
                .status("completed").createdAt(OffsetDateTime.parse("2025-01-02T10:00:00Z"))
                .build();
        Page<Order> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(o1));
        mockPage.setTotal(1);
        when(orderMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class))).thenReturn(mockPage);

        FinanceTransaction refund = FinanceTransaction.builder()
                .id("r2").tenantId(1L).orderId("o1").type("refund")
                .amount(new BigDecimal("20.00")).status("success").build();
        when(financeTransactionMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(refund));

        PageResponse<ReceivableReconciliationResponse> result = financeService.getReconciliation(1, 20, null, null, null, 1L);

        ReceivableReconciliationResponse item = result.getItems().get(0);
        assertThat(item.getDifference()).isEqualByComparingTo("20.00");
    }

    @Test
    @DisplayName("应收对账 - 无退款订单差额 = 应收-实收")
    void getReconciliation_noRefundDifference() {
        // given: 无退款流水
        Order o1 = Order.builder()
                .id("o1").tenantId(1L).orderNo("NO3")
                .customerName("王五").customerPhone("13700137000")
                .totalAmount(new BigDecimal("200.00")).actualAmount(new BigDecimal("150.00"))
                .status("confirmed").createdAt(OffsetDateTime.parse("2025-01-03T10:00:00Z"))
                .build();
        Page<Order> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(o1));
        mockPage.setTotal(1);
        when(orderMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class))).thenReturn(mockPage);
        when(financeTransactionMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

        PageResponse<ReceivableReconciliationResponse> result = financeService.getReconciliation(1, 20, null, null, null, 1L);

        assertThat(result.getItems().get(0).getDifference()).isEqualByComparingTo("50.00");
    }
}
