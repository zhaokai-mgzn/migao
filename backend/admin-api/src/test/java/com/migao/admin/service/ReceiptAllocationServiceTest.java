// case_ids: AR-002
package com.migao.admin.service;

import com.migao.admin.dto.ReceiptAllocationRequest;
import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ReceiptAllocation;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ReceiptAllocationMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 核销服务（issue #7370，P0-2 段 3）—— 两条硬约束在**服务层**也被钉住。
 *
 * <p>纯函数已逐格验过上限算法；本文件验的是**服务层接线**：只有收入/成功流水能核销、同客户、
 * 同批重复订单直接拒、批量逐行在「含本行」的余量上判、金额超精度直接拒（issue #6221）。</p>
 */
@DisplayName("核销服务：收入流水准入 / 同客户 / 批量逐行余量 / 精度准入")
class ReceiptAllocationServiceTest {

    private ReceiptAllocationMapper allocationMapper;
    private FinanceTransactionMapper financeTransactionMapper;
    private OrderMapper orderMapper;
    private ReceiptAllocationService service;

    /** 内存里的核销表（insert 进去、selectList 读出来 ⇒ 批量逐行判定才看得见上一行）。 */
    private final List<ReceiptAllocation> stored = new ArrayList<>();

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        // 纯单测里没有 Spring 的 MyBatis 启动流程 ⇒ LambdaQueryWrapper 的列名缓存要手动建一次，
        // 否则 `getSqlSegment()` 直接抛「can not find lambda cache for this entity」。
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(
                new org.apache.ibatis.builder.MapperBuilderAssistant(
                        new com.baomidou.mybatisplus.core.MybatisConfiguration(), ""),
                com.migao.admin.entity.ReceiptAllocation.class);
        allocationMapper = Mockito.mock(ReceiptAllocationMapper.class);
        financeTransactionMapper = Mockito.mock(FinanceTransactionMapper.class);
        orderMapper = Mockito.mock(OrderMapper.class);
        stored.clear();
        when(allocationMapper.insert(any(ReceiptAllocation.class))).thenAnswer(inv -> {
            stored.add(inv.getArgument(0));
            return 1;
        });
        when(allocationMapper.selectList(any())).thenAnswer(inv ->
                stored.stream().filter(row -> matches(inv.getArgument(0), row)).toList());
        service = new ReceiptAllocationService(allocationMapper, financeTransactionMapper, orderMapper);
    }

    /**
     * 按 Wrapper 的**列名 + 参数值**区分「按流水查」还是「按订单查」。
     *
     * <p>为什么不用 `String.valueOf(wrapper)`：LambdaQueryWrapper 的 toString 是对象标识，
     * 不含列名也不含值 —— 那样写出来的桩会让所有查询都返回空列表，测试是**恒绿的空断言**
     * （本文件第一版就踩了这个：四条用例红在「已核销 = 0」）。</p>
     */
    @SuppressWarnings("unchecked")
    private static boolean matches(Object wrapper, ReceiptAllocation row) {
        var w = (com.baomidou.mybatisplus.core.conditions.AbstractWrapper<?, ?, ?>) wrapper;
        String segment = String.valueOf(w.getSqlSegment());
        java.util.List<String> ids = ((java.util.Map<String, Object>) w.getParamNameValuePairs())
                .values().stream()
                .filter(String.class::isInstance)
                .map(String.class::cast)
                .toList();
        if (segment.contains("transaction_id")) {
            return row.getTransactionId() != null && ids.contains(row.getTransactionId());
        }
        if (segment.contains("order_id")) {
            return row.getOrderId() != null && ids.contains(row.getOrderId());
        }
        return false;
    }

    private FinanceTransaction receipt(String id, String type, String status, String amount, String orderId) {
        FinanceTransaction t = new FinanceTransaction();
        t.setId(id);
        t.setTenantId(1L);
        t.setTransactionNo("SK-" + id);
        t.setType(type);
        t.setStatus(status);
        t.setAmount(new BigDecimal(amount));
        t.setOrderId(orderId);
        return t;
    }

    private Order order(String id, String no, String phone, String total, String status) {
        Order o = new Order();
        o.setId(id);
        o.setTenantId(1L);
        o.setOrderNo(no);
        o.setCustomerPhone(phone);
        o.setCustomerName("客户" + phone);
        o.setTotalAmount(new BigDecimal(total));
        o.setStatus(status);
        return o;
    }

    private static ReceiptAllocationRequest req(String orderId, String amount) {
        return ReceiptAllocationRequest.builder()
                .lines(List.of(ReceiptAllocationRequest.Line.builder()
                        .orderId(orderId).amount(new BigDecimal(amount)).build()))
                .build();
    }

    @Test
    @DisplayName("正常核销：落一行 + 视图给出「已核销 / 未核销（预收待勾对）」")
    void happyPathWritesOneLineAndReportsUnallocated() {
        FinanceTransaction t = receipt("t1", "income", "success", "1000", "o1");
        when(financeTransactionMapper.selectById("t1")).thenReturn(t);
        when(financeTransactionMapper.selectList(any())).thenReturn(List.of());
        when(orderMapper.selectById("o1")).thenReturn(order("o1", "SO-1", "13800000001", "600", "confirmed"));

        var view = service.allocate("t1", req("o1", "600"), 1L, "财务小王");

        assertThat(stored).hasSize(1);
        assertThat(stored.get(0).getAmount()).isEqualByComparingTo("600");
        assertThat(stored.get(0).getCreatedBy()).isEqualTo("财务小王");
        assertThat(view.getTransactionAmount()).isEqualByComparingTo("1000");
        assertThat(view.getAllocated()).isEqualByComparingTo("600");
        assertThat(view.getUnallocated()).as("差额 = 预收 / 待勾对").isEqualByComparingTo("400");
    }

    @Test
    @DisplayName("🔴 只有收入且成功的流水能核销（退款/失败流水一律拒）")
    void onlySuccessfulIncomeReceiptsCanBeAllocated() {
        when(financeTransactionMapper.selectById("t2")).thenReturn(receipt("t2", "refund", "success", "100", null));
        assertThatThrownBy(() -> service.allocate("t2", req("o1", "10"), 1L, "u"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("只有收入流水可以核销");

        when(financeTransactionMapper.selectById("t3")).thenReturn(receipt("t3", "income", "failed", "100", null));
        assertThatThrownBy(() -> service.allocate("t3", req("o1", "10"), 1L, "u"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("成功的收款流水");
        assertThat(stored).isEmpty();
    }

    @Test
    @DisplayName("🔴 批量逐行：第二行必须在「含第一行」的余量上判（两行合起来不许超过收款金额）")
    void batchLinesShareTheReceiptCapacity() {
        FinanceTransaction t = receipt("t4", "income", "success", "1000", "o1");
        when(financeTransactionMapper.selectById("t4")).thenReturn(t);
        when(financeTransactionMapper.selectList(any())).thenReturn(List.of());
        when(orderMapper.selectById("o1")).thenReturn(order("o1", "SO-1", "13800000001", "900", "confirmed"));
        when(orderMapper.selectById("o2")).thenReturn(order("o2", "SO-2", "13800000001", "900", "confirmed"));

        // 两行各 600：合计 1200 > 流水 1000 ⇒ 第二行必须被拒（且整批回滚 = 一行都没落）
        var bad = ReceiptAllocationRequest.builder()
                .lines(List.of(
                        ReceiptAllocationRequest.Line.builder().orderId("o1").amount(new BigDecimal("600")).build(),
                        ReceiptAllocationRequest.Line.builder().orderId("o2").amount(new BigDecimal("600")).build()))
                .build();
        assertThatThrownBy(() -> service.allocate("t4", bad, 1L, "u"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("最多还能冲");
        assertThat(stored).hasSize(1);  // 第一行写进去了，第二行拒 ⇒ @Transactional 全回滚（单测无事务 ⇒ 断言「第二行没写」）

        // 合计不超 ⇒ 两行都落
        stored.clear();
        var good = ReceiptAllocationRequest.builder()
                .lines(List.of(
                        ReceiptAllocationRequest.Line.builder().orderId("o1").amount(new BigDecimal("600")).build(),
                        ReceiptAllocationRequest.Line.builder().orderId("o2").amount(new BigDecimal("400")).build()))
                .build();
        var view = service.allocate("t4", good, 1L, "u");
        assertThat(stored).hasSize(2);
        assertThat(view.getAllocated()).isEqualByComparingTo("1000");
        assertThat(view.getUnallocated()).isEqualByComparingTo("0");
    }

    @Test
    @DisplayName("同批里同一张单出现两次 ⇒ 直接拒（否则两行合计会绕过单张单上限）")
    void duplicateOrderInOneBatchIsRejected() {
        // 流水得先存在（准入在「同批重复」之前判），否则测的就不是本条判据
        when(financeTransactionMapper.selectById("t5")).thenReturn(receipt("t5", "income", "success", "100", "o1"));
        var bad = ReceiptAllocationRequest.builder()
                .lines(List.of(
                        ReceiptAllocationRequest.Line.builder().orderId("o1").amount(new BigDecimal("10")).build(),
                        ReceiptAllocationRequest.Line.builder().orderId("o1").amount(new BigDecimal("10")).build()))
                .build();
        assertThatThrownBy(() -> service.allocate("t5", bad, 1L, "u"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("出现了多次");
        verify(allocationMapper, never()).insert(any(ReceiptAllocation.class));
    }

    @Test
    @DisplayName("超精度金额直接拒（issue #6221：钱只有两位小数的物理意义，不静默四舍五入）")
    void overPrecisionAmountIsRejected() {
        FinanceTransaction t = receipt("t6", "income", "success", "1000", "o1");
        when(financeTransactionMapper.selectById("t6")).thenReturn(t);
        when(financeTransactionMapper.selectList(any())).thenReturn(List.of());
        when(orderMapper.selectById("o1")).thenReturn(order("o1", "SO-1", "13800000001", "900", "confirmed"));

        assertThatThrownBy(() -> service.allocate("t6", req("o1", "10.005"), 1L, "u"))
                .isInstanceOf(BusinessException.class);
        assertThat(stored).isEmpty();
    }

    @Test
    @DisplayName("同客户约束：把收款冲到别人单上 ⇒ 拒（对账灾难）")
    void cannotAllocateToAnotherCustomersOrder() {
        FinanceTransaction t = receipt("t7", "income", "success", "1000", "o1");
        when(financeTransactionMapper.selectById("t7")).thenReturn(t);
        when(financeTransactionMapper.selectList(any())).thenReturn(List.of());
        when(orderMapper.selectById("o1")).thenReturn(order("o1", "SO-1", "13800000001", "900", "confirmed"));
        when(orderMapper.selectById("o9")).thenReturn(order("o9", "SO-9", "13900000009", "900", "confirmed"));

        assertThatThrownBy(() -> service.allocate("t7", req("o9", "100"), 1L, "u"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不能核销到其他客户的订单");
        assertThat(stored).isEmpty();
    }

    @Test
    @DisplayName("已取消的订单不能核销（取消单的应收已被冲销）")
    void cancelledOrderCannotBeAllocated() {
        FinanceTransaction t = receipt("t8", "income", "success", "1000", "o1");
        when(financeTransactionMapper.selectById("t8")).thenReturn(t);
        when(financeTransactionMapper.selectList(any())).thenReturn(List.of());
        when(orderMapper.selectById("o1")).thenReturn(order("o1", "SO-1", "13800000001", "900", "cancelled"));

        assertThatThrownBy(() -> service.allocate("t8", req("o1", "10"), 1L, "u"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已取消的订单不能核销");
        assertThat(stored).isEmpty();
    }

    @Test
    @DisplayName("service 侧写入金额字段的口径：setAmount 是唯一写点（金额准入台账登记的就是它）")
    void writesAmountThroughSingleSetter() {
        FinanceTransaction t = receipt("t9", "income", "success", "100", "o1");
        when(financeTransactionMapper.selectById("t9")).thenReturn(t);
        when(financeTransactionMapper.selectList(any())).thenReturn(List.of());
        when(orderMapper.selectById("o1")).thenReturn(order("o1", "SO-1", "13800000001", "100", "confirmed"));

        service.allocate("t9", req("o1", "100"), 1L, "u");

        ArgumentCaptor<ReceiptAllocation> captor = ArgumentCaptor.forClass(ReceiptAllocation.class);
        verify(allocationMapper).insert(captor.capture());
        assertThat(captor.getValue().getAmount()).isEqualByComparingTo("100");
        assertThat(captor.getValue().getAmount().scale()).isEqualTo(2);
    }
}
