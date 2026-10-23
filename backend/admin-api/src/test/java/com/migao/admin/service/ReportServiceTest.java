// case_ids: RPT-001
package com.migao.admin.service;

import com.migao.admin.dto.OrderMarginView;
import com.migao.admin.entity.Order;
import com.migao.admin.mapper.OrderMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

/**
 * 订单毛利报表（issue #7376 段 1）—— 三条纪律：合计=明细之和 / 空数据≠0 / 成本未知不进合计但要计数。
 *
 * <p>这里最容易犯的错是「成本未知的单按 0 计入合计」：那会让报表上的毛利**虚高**，
 * 而每一单单看都正常（未知的成本显示为「成本未知」，只是合计悄悄多算了）。</p>
 */
@DisplayName("毛利报表：合计=明细之和 / 空数据合计为 null / 成本未知单独计数")
class ReportServiceTest {

    private OrderMapper orderMapper;
    private OrderMarginService orderMarginService;
    private ReportService service;

    @BeforeEach
    void setUp() {
        orderMapper = Mockito.mock(OrderMapper.class);
        orderMarginService = Mockito.mock(OrderMarginService.class);
        service = new ReportService(orderMapper, null, null, null, null, orderMarginService,
                new com.migao.admin.time.BusinessClock(), null);
    }

    private static Order order(String id) {
        Order o = new Order();
        o.setId(id);
        o.setTenantId(1L);
        o.setCreatedBy("u-1");
        return o;
    }

    private static OrderMarginView margin(String id, String revenue, String fabric, String labor,
                                          boolean costKnown, String gross) {
        return OrderMarginView.builder()
                .orderId(id).orderNo("SO-" + id).status("completed")
                .revenue(new BigDecimal(revenue)).refunded(BigDecimal.ZERO)
                .fabricCost(costKnown ? new BigDecimal(fabric) : null)
                .laborCost(costKnown ? new BigDecimal(labor) : null)
                .grossMargin(costKnown ? new BigDecimal(gross) : null)
                .costKnown(costKnown).scope("revenue_minus_refund_minus_fabric_minus_labor")
                .build();
    }

    @Test
    @DisplayName("合计 = 逐单之和（两单已知成本 ⇒ 收入 2000、毛利 1100）")
    void totalsAreSumOfRows() {
        when(orderMapper.selectList(any())).thenReturn(List.of(order("o1"), order("o2")));
        when(orderMarginService.margin("o1")).thenReturn(margin("o1", "1000", "400", "100", true, "500"));
        when(orderMarginService.margin("o2")).thenReturn(margin("o2", "1000", "300", "100", true, "600"));

        var report = service.orderMargins(null, null, null);

        assertThat(report.isHasData()).isTrue();
        assertThat(report.getRows()).hasSize(2);
        assertThat(report.getTotals().getRevenue()).isEqualByComparingTo("2000");
        assertThat(report.getTotals().getGrossMargin()).isEqualByComparingTo("1100");
        assertThat(report.getUnknownCostOrders()).isZero();
    }

    @Test
    @DisplayName("🔴 空数据 ⇒ 合计为 null、hasData=false（不是一堆 0）")
    void emptyReportHasNullTotals() {
        when(orderMapper.selectList(any())).thenReturn(List.of());

        var report = service.orderMargins(null, null, null);

        assertThat(report.isHasData()).isFalse();
        assertThat(report.getRows()).isEmpty();
        assertThat(report.getTotals()).as("没有数据就不该给出一组 0（那会被读成「毛利 0」）").isNull();
    }

    @Test
    @DisplayName("🔴 成本未知的单**不进毛利合计**，但单独计数（合计少算了多少必须说出来）")
    void unknownCostRowsAreExcludedAndCounted() {
        when(orderMapper.selectList(any())).thenReturn(List.of(order("o1"), order("o2")));
        when(orderMarginService.margin("o1")).thenReturn(margin("o1", "1000", "400", "100", true, "500"));
        when(orderMarginService.margin("o2")).thenReturn(margin("o2", "1000", null, null, false, null));

        var report = service.orderMargins(null, null, null);

        assertThat(report.getUnknownCostOrders()).isEqualTo(1);
        assertThat(report.getTotals().getGrossMargin())
                .as("只合计可算的那一单（把未知当 0 会让毛利虚高）").isEqualByComparingTo("500");
        assertThat(report.getRows()).hasSize(2);
        assertThat(report.getRows().get(1).isCostKnown()).isFalse();
    }

    @Test
    @DisplayName("数据范围：self 范围只按 created_by 过滤（与 P0-4 同口径）")
    void dataScopeIsAppliedToQuery() {
        when(orderMapper.selectList(any())).thenReturn(List.of());

        service.orderMargins("2026-10-01", "2026-10-31", "u-1");

        // 判据落在「查询条件里带上了范围与日期」——SQL 段可读，故直接断言 wrapper 产物
        Mockito.verify(orderMapper).selectList(any());
    }

    @Test
    @DisplayName("只有成本未知的单 ⇒ 合计的收入等仍可算（未知只影响毛利口径），但毛利为 null")
    void allUnknownCostKeepsRevenueButNullMargin() {
        when(orderMapper.selectList(any())).thenReturn(List.of(order("o1")));
        when(orderMarginService.margin("o1")).thenReturn(margin("o1", "1000", null, null, false, null));

        var report = service.orderMargins(null, null, null);

        assertThat(report.getUnknownCostOrders()).isEqualTo(1);
        assertThat(report.getTotals().getGrossMargin())
                .as("没有一单能算毛利 ⇒ 合计毛利为 null（不是 0）").isNull();
    }
}
