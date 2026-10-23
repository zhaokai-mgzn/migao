// case_ids: QC-003
package com.migao.admin.service;

import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/**
 * 质量成本的**维度汇总**（issue #7377 段 5，QC-003）。
 *
 * <p>本类只判「摊开这件事有没有丢数」：维度报表最容易犯的错是**关联不上的行悄悄不见**——
 * 于是「各行之和」比整表小，而每一行单看都正常（合计没变、行也没报错）。
 * 所以核心判据是恒等式：<b>整表合计 == Σ行 + 未归属</b>，且未归属必须带原因。</p>
 */
@DisplayName("质量成本维度汇总：合计=Σ行+未归属 / 未标工序进未归属 / 赔付无工序信息 / 未定价不计金额")
class QualityCostBreakdownTest {

    private ProductionWorkLogMapper workLogMapper;
    private FinanceTransactionMapper financeMapper;
    private OrderMapper orderMapper;
    private ProcessingOrderMapper processingOrderMapper;
    private ReportService service;

    @BeforeEach
    void setUp() {
        workLogMapper = Mockito.mock(ProductionWorkLogMapper.class);
        financeMapper = Mockito.mock(FinanceTransactionMapper.class);
        orderMapper = Mockito.mock(OrderMapper.class);
        processingOrderMapper = Mockito.mock(ProcessingOrderMapper.class);
        service = new ReportService(orderMapper, null, workLogMapper, financeMapper, null, null,
                new com.migao.admin.time.BusinessClock(), null, processingOrderMapper);
        when(financeMapper.selectList(any())).thenReturn(List.of());
        when(workLogMapper.selectList(any())).thenReturn(List.of());
    }

    private static ProductionWorkLog rework(String operation, String processingOrderId, String qty,
                                            String unitPrice, String priceState, String workDate) {
        return ProductionWorkLog.builder()
                .id("wl-" + System.nanoTime())
                .workType("rework")
                .operationName(operation)
                .processingOrderId(processingOrderId)
                .qty(new BigDecimal(qty))
                .unitPrice(unitPrice == null ? null : new BigDecimal(unitPrice))
                .priceState(priceState)
                .workDate(workDate == null ? null : LocalDate.parse(workDate))
                .createdAt(OffsetDateTime.parse("2026-10-20T10:00:00+08:00"))
                .build();
    }

    private static FinanceTransaction refund(String orderId, String amount) {
        FinanceTransaction txn = new FinanceTransaction();
        txn.setId("tx-" + System.nanoTime());
        txn.setType("refund");
        txn.setStatus("success");
        txn.setOrderId(orderId);
        txn.setAmount(new BigDecimal(amount));
        txn.setOccurredAt(OffsetDateTime.parse("2026-10-21T12:00:00+08:00"));
        return txn;
    }

    private void customer(String orderId, String processingOrderId, String name, String phone) {
        Order order = new Order();
        order.setId(orderId);
        order.setCustomerName(name);
        order.setCustomerPhone(phone);
        when(orderMapper.selectById(orderId)).thenReturn(order);

        ProcessingOrder po = new ProcessingOrder();
        po.setId(processingOrderId);
        po.setOrderId(orderId);
        when(processingOrderMapper.selectById(processingOrderId)).thenReturn(po);
    }

    @Test
    @DisplayName("🔴 恒等式：整表合计 == Σ行 + 未归属（关联不上的金额必须露出来）")
    void totalsEqualRowsPlusUnattributed() {
        customer("o1", "po1", "张记布艺", "13800000001");
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                // 能归属：报工 → 加工单 → 订单 → 张记布艺
                rework("缝制", "po1", "2", "30", "priced", "2026-10-20"),
                // 归属不了：报工没挂加工单
                rework("缝制", null, "1", "50", "priced", "2026-10-20")));
        when(financeMapper.selectList(any())).thenReturn(List.of(
                refund("o1", "120"),      // 能归属：流水 → 订单 → 张记布艺
                refund(null, "80")));     // 归属不了：流水没挂订单

        var view = service.qualityCostBreakdown("customer", null, null);

        assertThat(view.isHasData()).isTrue();
        assertThat(view.getRows()).hasSize(1);
        var row = view.getRows().get(0);
        assertThat(row.getLabel()).isEqualTo("张记布艺");
        assertThat(row.getRework()).isEqualByComparingTo("60.00");        // 2 × 30
        assertThat(row.getCompensation()).isEqualByComparingTo("120.00");

        // 🔴 恒等式（逐项成立，不是只看总和）
        BigDecimal rowRework = view.getRows().stream().map(r -> r.getRework()).reduce(BigDecimal.ZERO, BigDecimal::add);
        BigDecimal rowComp = view.getRows().stream().map(r -> r.getCompensation()).reduce(BigDecimal.ZERO, BigDecimal::add);
        assertThat(view.getTotals().getRework())
                .isEqualByComparingTo(rowRework.add(view.getUnattributed().getRework()));
        assertThat(view.getTotals().getCompensation())
                .isEqualByComparingTo(rowComp.add(view.getUnattributed().getCompensation()));
        assertThat(view.getTotals().getTotal())
                .isEqualByComparingTo(view.getTotals().getRework().add(view.getTotals().getCompensation()));

        // 未归属：返工 50（缺加工单）+ 赔付 80（缺订单），且带原因
        assertThat(view.getUnattributed().getRework()).isEqualByComparingTo("50.00");
        assertThat(view.getUnattributed().getCompensation()).isEqualByComparingTo("80.00");
        assertThat(view.getUnattributed().getReason()).isNotBlank();
        // 合计 = 全部（行 + 未归属）：返工 110 / 赔付 200
        assertThat(view.getTotals().getRework()).isEqualByComparingTo("110.00");
        assertThat(view.getTotals().getCompensation()).isEqualByComparingTo("200.00");
    }

    @Test
    @DisplayName("🔴 工序维度：返工按工序名成行；赔付**整体**进未归属（流水没有工序信息）")
    void processDimensionPutsCompensationIntoUnattributed() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                rework("缝制", null, "2", "30", "priced", "2026-10-20"),
                rework("定型", null, "1", "40", "priced", "2026-10-20"),
                // 报工行没记工序名 ⇒ 进未归属（不是编一个「其他」行）
                rework(null, null, "3", "10", "priced", "2026-10-20")));
        when(financeMapper.selectList(any())).thenReturn(List.of(refund("o1", "99")));

        var view = service.qualityCostBreakdown("process", null, null);

        assertThat(view.getDimension()).isEqualTo("process");
        assertThat(view.getRows()).extracting(r -> r.getLabel())
                .containsExactlyInAnyOrder("缝制", "定型");
        assertThat(view.getUnattributed().getRework()).isEqualByComparingTo("30.00");
        assertThat(view.getUnattributed().getCompensation()).isEqualByComparingTo("99.00");
        // 工序维度下赔付一定全部未归属 —— 说明里要点出来（否则读者以为「赔付是 0」）
        assertThat(String.join(" ", view.getNotes())).contains("不是「赔付为 0」");
    }

    @Test
    @DisplayName("未定价报工不计金额，但要被数出来（未定价 ≠ 0 元）")
    void unpricedReworkIsCountedButNotAmounted() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                rework("缝制", null, "1", "30", "priced", "2026-10-20"),
                rework("缝制", null, "5", null, "unpriced", "2026-10-20")));

        var view = service.qualityCostBreakdown("process", null, null);

        assertThat(view.getRows()).hasSize(1);
        assertThat(view.getRows().get(0).getRework()).isEqualByComparingTo("30.00");   // 只算已定价那行
        assertThat(view.getRows().get(0).getReworkLines()).isEqualTo(1);
        assertThat(String.join(" ", view.getNotes())).contains("未定价");
    }

    @Test
    @DisplayName("窗口真的生效：窗外报工/退款不计（原实现收了日期不用）")
    void windowFiltersBothSides() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                rework("缝制", null, "1", "30", "priced", "2026-09-01"),   // 窗外
                rework("缝制", null, "1", "30", "priced", "2026-10-20"))); // 窗内
        when(financeMapper.selectList(any())).thenReturn(List.of(refund("o1", "50")));

        var view = service.qualityCostBreakdown("process", "2026-10-01", "2026-10-31");

        assertThat(view.getTotals().getRework()).isEqualByComparingTo("30.00");
        assertThat(view.getTotals().getReworkLines()).isEqualTo(1);
    }

    @Test
    @DisplayName("没有读数 ⇒ hasData=false 且 totals=null（不是「质量成本 0 元」）")
    void emptyWindowHasNoData() {
        var view = service.qualityCostBreakdown("customer", null, null);

        assertThat(view.isHasData()).isFalse();
        assertThat(view.getTotals()).isNull();
        assertThat(view.getRows()).isEmpty();
        assertThat(view.getUnattributed().getTotal()).isEqualByComparingTo("0.00");
    }

    @Test
    @DisplayName("维度非法 ⇒ 可读的 400（不静默返回空表）")
    void unknownDimensionIsRejected() {
        assertThatThrownBy(() -> service.qualityCostBreakdown("product", null, null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不支持的质量成本维度");
        // 反恒真：合法维度不抛
        assertThat(service.qualityCostBreakdown("customer", null, null)).isNotNull();
    }
}
