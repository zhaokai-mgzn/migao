// case_ids: RPT-003
package com.migao.admin.service;

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
import static org.mockito.Mockito.when;

/**
 * 员工业绩报表（issue #7376 段 3）—— 三条容易做错的口径。
 *
 * <p>最贵的一条是「无主订单摊给某人」：那会**凭空给人加分**，而没有任何东西会报错。</p>
 */
@DisplayName("员工业绩：按制单人归集 / 无主单不摊 / 客单价不做 0 除 / 空数据合计 null")
class StaffPerformanceReportTest {

    private OrderMapper orderMapper;
    private ReportService service;

    @BeforeEach
    void setUp() {
        orderMapper = Mockito.mock(OrderMapper.class);
        service = new ReportService(orderMapper, null, null, null, null, null,
                new com.migao.admin.time.BusinessClock(), null, null);
    }

    private static Order order(String createdBy, String createdByName, String amount) {
        Order o = new Order();
        o.setId("o-" + Math.random());
        o.setTenantId(1L);
        o.setCreatedBy(createdBy);
        o.setCreatedByName(createdByName);
        o.setTotalAmount(amount == null ? null : new BigDecimal(amount));
        return o;
    }

    @Test
    @DisplayName("按制单人归集：两人各两单 ⇒ 两行，单数/收入/客单价各自正确")
    void groupsByStaff() {
        when(orderMapper.selectList(any())).thenReturn(List.of(
                order("u-1", "小王", "1000"), order("u-1", "小王", "500"),
                order("u-2", "小李", "800")));

        var report = service.staffPerformance(null, null, null);

        assertThat(report.getRows()).hasSize(2);
        var wang = report.getRows().get(0);
        assertThat(wang.getStaffName()).isEqualTo("小王");
        assertThat(wang.getOrderCount()).isEqualTo(2);
        assertThat(wang.getRevenue()).isEqualByComparingTo("1500");
        assertThat(wang.getAvgOrderValue()).as("客单价 = 1500 / 2").isEqualByComparingTo("750");
        assertThat(report.getTotals().getOrderCount()).isEqualTo(3);
        assertThat(report.getTotals().getRevenue()).isEqualByComparingTo("2300");
    }

    @Test
    @DisplayName("🔴 没有制单人的订单单独计数，**不摊给任何人**（摊了就是凭空加分）")
    void unattributedOrdersAreNotBlamedOnAnyone() {
        when(orderMapper.selectList(any())).thenReturn(List.of(
                order("u-1", "小王", "1000"), order(null, null, "9999")));

        var report = service.staffPerformance(null, null, null);

        assertThat(report.getUnattributedOrders()).isEqualTo(1);
        assertThat(report.getRows()).hasSize(1);
        assertThat(report.getRows().get(0).getRevenue())
                .as("无主订单的收入不进任何人的业绩").isEqualByComparingTo("1000");
    }

    @Test
    @DisplayName("🔴 空数据 ⇒ 合计为 null（不是 0）")
    void emptyReportHasNullTotals() {
        when(orderMapper.selectList(any())).thenReturn(List.of());

        var report = service.staffPerformance(null, null, null);

        assertThat(report.isHasData()).isFalse();
        assertThat(report.getTotals()).isNull();
    }

    @Test
    @DisplayName("金额为 null 的订单按 0 计入收入，但单数照算（不让一行脏值吞掉整单）")
    void nullAmountCountsAsZeroButOrderStillCounted() {
        when(orderMapper.selectList(any())).thenReturn(List.of(
                order("u-1", "小王", null), order("u-1", "小王", "100")));

        var report = service.staffPerformance(null, null, null);

        assertThat(report.getRows().get(0).getOrderCount()).isEqualTo(2);
        assertThat(report.getRows().get(0).getRevenue()).isEqualByComparingTo("100");
    }

    @Test
    @DisplayName("数据范围：self ⇒ 只统计本人创建的单（业绩报表里就是「只看自己的业绩」）")
    void dataScopeRestrictsToOwnPerformance() {
        when(orderMapper.selectList(any())).thenReturn(List.of(order("u-1", "小王", "100")));

        var report = service.staffPerformance(null, null, "u-1");

        assertThat(report.getRows()).hasSize(1);
        Mockito.verify(orderMapper).selectList(any());
    }
}
