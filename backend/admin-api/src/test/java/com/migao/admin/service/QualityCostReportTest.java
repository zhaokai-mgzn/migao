// case_ids: QC-001
package com.migao.admin.service;

import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
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
 * 质量成本报表（issue #7377 段 1）—— 取数口径与「未定价 / 未采集 / 未发生」三者的区别。
 *
 * <p>最容易犯的错：把「没有退款流水」写成赔付 0、把「未定价返工」按 0 元工时算 ——
 * 两者都会让质量成本看起来比真实更低，而账面完全正常。</p>
 */
@DisplayName("质量成本报表：返工按单价快照 / 未定价不计金额 / 无退款流水记未知")
class QualityCostReportTest {

    private OrderMapper orderMapper;
    private ProductionWorkLogMapper workLogMapper;
    private FinanceTransactionMapper financeMapper;
    private ReportService service;

    @BeforeEach
    void setUp() {
        orderMapper = Mockito.mock(OrderMapper.class);
        workLogMapper = Mockito.mock(ProductionWorkLogMapper.class);
        financeMapper = Mockito.mock(FinanceTransactionMapper.class);
        service = new ReportService(orderMapper, null, workLogMapper, financeMapper, null, null,
                new com.migao.admin.time.BusinessClock(), null, null, null);
        when(financeMapper.selectList(any())).thenReturn(List.of());
    }

    private static ProductionWorkLog rework(String qty, String unitPrice, String priceState) {
        ProductionWorkLog log = new ProductionWorkLog();
        log.setProcessingOrderId("po-1");
        log.setWorkType("rework");
        log.setQty(qty == null ? null : new BigDecimal(qty));
        log.setUnitPrice(unitPrice == null ? null : new BigDecimal(unitPrice));
        log.setPriceState(priceState);
        return log;
    }

    @Test
    @DisplayName("返工工时 = Σ(数量 × 单价快照)；有未定价行 ⇒ 该项未知、金额为 null")
    void reworkUsesUnitPriceSnapshot() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                rework("2", "30", "priced"), rework("1", "40", "priced")));

        var view = service.qualityCost(null, null);

        var rework = view.getComponents().get(0);
        assertThat(rework.getCode()).isEqualTo("rework_labor");
        assertThat(rework.getAmount()).isEqualByComparingTo("100");
        assertThat(rework.isKnown()).isTrue();
    }

    @Test
    @DisplayName("🔴 未定价的返工报工不计金额（未定价 ≠ 0 元工时），并计行数")
    void unpricedReworkIsNotZeroCost() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                rework("2", "30", "priced"), rework("5", null, "unpriced")));

        var rework = service.qualityCost(null, null).getComponents().get(0);

        assertThat(rework.isKnown()).isFalse();
        assertThat(rework.getAmount()).as("不能只算有价那一条然后当真").isNull();
        assertThat(rework.getUnknownItems()).isEqualTo(1);
    }

    @Test
    @DisplayName("🔴 报废料恒未知：不填 0（填 0 会被读成「本月没有报废损失」）")
    void scrapIsUnknownNotZero() {
        when(workLogMapper.selectList(any())).thenReturn(List.of());

        var scrap = service.qualityCost(null, null).getComponents().get(1);

        assertThat(scrap.getCode()).isEqualTo("scrap_material");
        assertThat(scrap.isKnown()).isFalse();
        assertThat(scrap.getAmount()).isNull();
    }

    @Test
    @DisplayName("没有退款流水 ⇒ 赔付未知 + 合计不完整（列出未知分项）")
    void noRefundsMeansUnknownCompensation() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(rework("1", "10", "priced")));

        var view = service.qualityCost(null, null);

        assertThat(view.getComponents().get(2).isKnown()).isFalse();
        assertThat(view.isComplete()).isFalse();
        assertThat(view.getUnknownComponents()).contains("scrap_material", "compensation");
        assertThat(view.getTotal()).as("只累加已知项 ⇒ 返工 10 元").isEqualByComparingTo("10");
    }

    @Test
    @DisplayName("有退款流水 ⇒ 赔付已知，合计包含它")
    void refundsCountIntoTotal() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(rework("1", "10", "priced")));
        FinanceTransaction refund = new FinanceTransaction();
        refund.setOrderId("o-1");
        refund.setAmount(new BigDecimal("200"));
        FinanceTransaction sameOrder = new FinanceTransaction();
        sameOrder.setOrderId("o-1");
        sameOrder.setAmount(new BigDecimal("100"));
        when(financeMapper.selectList(any())).thenReturn(List.of(refund, sameOrder));

        var view = service.qualityCost(null, null);

        assertThat(view.getComponents().get(2).getAmount()).isEqualByComparingTo("300");
        assertThat(view.getTotal()).isEqualByComparingTo("310");
    }
}
