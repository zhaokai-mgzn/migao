// case_ids: AR-003
package com.migao.admin.service;

import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.Order;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

/**
 * 订单毛利服务（issue #7371，P0-3 段 1）—— 取数与「未知/真 0」的分界。
 *
 * <p>纯函数已验过算式；本文件验的是**取数口径**：没有扣料行 ⇒ 面料成本是**真 0**（还没领料）；
 * 有扣料行但缺进价 ⇒ **成本未知**（毛利 null），两者不许混为一谈。</p>
 */
@DisplayName("毛利服务：无扣料=真 0 / 缺进价=未知 / 退款冲减 / 订单不存在")
class OrderMarginServiceTest {

    private OrderMapper orderMapper;
    private FinanceTransactionMapper financeTransactionMapper;
    private OrderMarginService service;

    @BeforeEach
    void setUp() {
        orderMapper = Mockito.mock(OrderMapper.class);
        financeTransactionMapper = Mockito.mock(FinanceTransactionMapper.class);
        when(financeTransactionMapper.selectList(any())).thenReturn(List.of());
        service = new OrderMarginService(orderMapper, financeTransactionMapper);
    }

    private Order order(String id, String no, String total, String status) {
        Order o = new Order();
        o.setId(id);
        o.setTenantId(1L);
        o.setOrderNo(no);
        o.setTotalAmount(new BigDecimal(total));
        o.setStatus(status);
        return o;
    }

    private static Map<String, Object> fabric(String cost, int unknown, long lines) {
        Map<String, Object> row = new HashMap<>();
        row.put("fabric_cost", cost == null ? null : new BigDecimal(cost));
        row.put("unknown_lines", unknown);
        row.put("lines", lines);
        return row;
    }

    @Test
    @DisplayName("正常：面料成本已知 ⇒ 毛利 = 收入 − 退款 − 面料，口径自述随身带")
    void knownCostProducesMargin() {
        when(orderMapper.selectById("o1")).thenReturn(order("o1", "SO-1", "1000", "completed"));
        when(orderMapper.selectFabricCost(1L, "SO-1")).thenReturn(fabric("400", 0, 3));
        FinanceTransaction refund = new FinanceTransaction();
        refund.setAmount(new BigDecimal("100"));
        when(financeTransactionMapper.selectList(any())).thenReturn(List.of(refund));

        var view = service.margin("o1");

        assertThat(view.isCostKnown()).isTrue();
        assertThat(view.getFabricCost()).isEqualByComparingTo("400");
        assertThat(view.getRefunded()).isEqualByComparingTo("100");
        assertThat(view.getGrossMargin()).isEqualByComparingTo("500");
        assertThat(view.getMarginRate()).isEqualByComparingTo("0.5556");
        assertThat(view.getFabricLines()).isEqualTo(3);
        assertThat(view.getUnknownFabricLines()).isZero();
        assertThat(view.getScope()).isEqualTo(OrderMargin.SCOPE_FABRIC_ONLY);
    }

    @Test
    @DisplayName("🔴 有扣料行但缺进价 ⇒ 成本与毛利都是 null（服务层不许把未知填 0）")
    void unknownCostIsNullNotZero() {
        when(orderMapper.selectById("o2")).thenReturn(order("o2", "SO-2", "1000", "completed"));
        when(orderMapper.selectFabricCost(1L, "SO-2")).thenReturn(fabric("400", 2, 5));

        var view = service.margin("o2");

        assertThat(view.isCostKnown()).isFalse();
        assertThat(view.getFabricCost()).isNull();
        assertThat(view.getGrossMargin()).as("不能把收入全额当毛利").isNull();
        assertThat(view.getMarginRate()).isNull();
        assertThat(view.getUnknownFabricLines()).isEqualTo(2);
    }

    @Test
    @DisplayName("没有扣料行 ⇒ 面料成本是**真 0**（还没领料），毛利 = 收入 − 退款")
    void noConsumptionIsRealZero() {
        when(orderMapper.selectById("o3")).thenReturn(order("o3", "SO-3", "800", "confirmed"));
        when(orderMapper.selectFabricCost(1L, "SO-3")).thenReturn(fabric("0", 0, 0));

        var view = service.margin("o3");

        assertThat(view.isCostKnown()).isTrue();
        assertThat(view.getFabricCost()).isEqualByComparingTo("0");
        assertThat(view.getGrossMargin()).isEqualByComparingTo("800");
        assertThat(view.getFabricLines()).isZero();
    }

    @Test
    @DisplayName("查询返回 null（极端：SQL 没回来）⇒ 按「真 0 / 无扣料」处理，不 NPE")
    void nullRowIsTreatedAsNoConsumption() {
        when(orderMapper.selectById("o4")).thenReturn(order("o4", "SO-4", "100", "pending"));
        when(orderMapper.selectFabricCost(1L, "SO-4")).thenReturn(null);

        var view = service.margin("o4");

        assertThat(view.isCostKnown()).isTrue();
        assertThat(view.getFabricCost()).isEqualByComparingTo("0");
        assertThat(view.getGrossMargin()).isEqualByComparingTo("100");
    }

    @Test
    @DisplayName("订单不存在 ⇒ 404 语义（不是空结果）")
    void missingOrderIsNotFound() {
        when(orderMapper.selectById(anyString())).thenReturn(null);
        assertThatThrownBy(() -> service.margin("nope"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("订单");
    }
}
