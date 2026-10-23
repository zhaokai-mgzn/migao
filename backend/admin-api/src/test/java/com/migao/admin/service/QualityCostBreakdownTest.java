// case_ids: QC-003, QC-004, QC-005
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
    private com.migao.admin.mapper.OrderItemMapper orderItemMapper;
    private ReportService service;

    @BeforeEach
    void setUp() {
        workLogMapper = Mockito.mock(ProductionWorkLogMapper.class);
        financeMapper = Mockito.mock(FinanceTransactionMapper.class);
        orderMapper = Mockito.mock(OrderMapper.class);
        processingOrderMapper = Mockito.mock(ProcessingOrderMapper.class);
        orderItemMapper = Mockito.mock(com.migao.admin.mapper.OrderItemMapper.class);
        when(orderItemMapper.selectList(any())).thenReturn(List.of());
        service = new ReportService(orderMapper, null, workLogMapper, financeMapper, null, null,
                new com.migao.admin.time.BusinessClock(), null, processingOrderMapper, orderItemMapper);
        when(financeMapper.selectList(any())).thenReturn(List.of());
        when(workLogMapper.selectList(any())).thenReturn(List.of());
    }

    /** 报废报工（issue #7377 段 8）：与返工同一张表，只换 work_type。 */
    private static ProductionWorkLog scrap(String operation, String processingOrderId, String qty,
                                           String unitPrice, String priceState, String workDate) {
        ProductionWorkLog log = rework(operation, processingOrderId, qty, unitPrice, priceState, workDate);
        log.setWorkType("scrap");
        return log;
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
        // product 在 issue #7377 段 6 起是**合法**维度 ⇒ 这里换成真正非法的取值
        assertThatThrownBy(() -> service.qualityCostBreakdown("supplier", null, null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不支持的质量成本维度");
        // 反恒真：三个合法维度都不抛
        for (String legal : List.of("customer", "process", "product")) {
            assertThat(service.qualityCostBreakdown(legal, null, null)).isNotNull();
        }
    }

    // ── 商品维度：按订单行小计占比分摊（issue #7377 段 6，用户 2026-10-23 裁定「按比例」）──

    private static com.migao.admin.entity.OrderItem item(String orderId, String productId,
                                                         String name, String subtotal) {
        com.migao.admin.entity.OrderItem it = new com.migao.admin.entity.OrderItem();
        it.setOrderId(orderId);
        it.setProductId(productId);
        it.setProductName(name);
        it.setSubtotal(subtotal == null ? null : new BigDecimal(subtotal));
        return it;
    }

    @Test
    @DisplayName("🔴 商品维度：赔付按**订单行小计占比**摊开（60/40 的单 ⇒ 60/40）")
    void productDimensionSplitsCompensationByLineSubtotal() {
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                item("o1", "p-A", "遮光布", "600"),
                item("o1", "p-B", "纱帘", "400")));
        when(financeMapper.selectList(any())).thenReturn(List.of(refund("o1", "100")));

        var view = service.qualityCostBreakdown("product", null, null);

        assertThat(view.getDimension()).isEqualTo("product");
        assertThat(view.getRows()).hasSize(2);
        var a = view.getRows().stream().filter(r -> "遮光布".equals(r.getLabel())).findFirst().orElseThrow();
        var b = view.getRows().stream().filter(r -> "纱帘".equals(r.getLabel())).findFirst().orElseThrow();
        assertThat(a.getCompensation()).isEqualByComparingTo("60.00");
        assertThat(b.getCompensation()).isEqualByComparingTo("40.00");
        assertThat(view.getTotals().getCompensation()).isEqualByComparingTo("100.00");
        assertThat(view.getUnattributed().getCompensation()).isEqualByComparingTo("0.00");
    }

    @Test
    @DisplayName("🔴 逐分对得上：100.01 摊两行 ⇒ 50.01 / 50.00（Σ == 总额，残差补给最大行）")
    void productDimensionKeepsCentIdentity() {
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                item("o1", "p-A", "遮光布", "100"),
                item("o1", "p-B", "纱帘", "100")));
        when(financeMapper.selectList(any())).thenReturn(List.of(refund("o1", "100.01")));

        var view = service.qualityCostBreakdown("product", null, null);

        BigDecimal sum = view.getRows().stream().map(r -> r.getCompensation())
                .reduce(BigDecimal.ZERO, BigDecimal::add);
        assertThat(sum).isEqualByComparingTo("100.01");                    // 不差一分
        assertThat(view.getTotals().getCompensation()).isEqualByComparingTo(sum);
    }

    @Test
    @DisplayName("商品维度：返工也经「报工 → 加工单 → 订单 → 行」按比例摊")
    void productDimensionAttributesReworkThroughOrderLines() {
        customer("o1", "po1", "张记布艺", "13800000001");
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                item("o1", "p-A", "遮光布", "300"),
                item("o1", "p-B", "纱帘", "100")));
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                rework("缝制", "po1", "1", "80", "priced", "2026-10-20")));

        var view = service.qualityCostBreakdown("product", null, null);

        var a = view.getRows().stream().filter(r -> "遮光布".equals(r.getLabel())).findFirst().orElseThrow();
        var b = view.getRows().stream().filter(r -> "纱帘".equals(r.getLabel())).findFirst().orElseThrow();
        assertThat(a.getRework()).isEqualByComparingTo("60.00");   // 80 × 300/400
        assertThat(b.getRework()).isEqualByComparingTo("20.00");
    }

    @Test
    @DisplayName("🔴 权重缺失不编：订单没有明细行 / 报工没挂加工单 ⇒ 进未归属（恒等式仍成立）")
    void productDimensionFallsBackToUnattributed() {
        // 报工没挂加工单 ⇒ 拿不到订单
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                rework("缝制", null, "1", "50", "priced", "2026-10-20"),
                rework("缝制", "po-x", "1", "30", "priced", "2026-10-20")));
        // 退款挂了一个查不到明细的订单
        when(orderItemMapper.selectList(any())).thenReturn(List.of());
        when(financeMapper.selectList(any())).thenReturn(List.of(refund("o-ghost", "70")));

        var view = service.qualityCostBreakdown("product", null, null);

        assertThat(view.getRows()).isEmpty();
        assertThat(view.getUnattributed().getRework()).isEqualByComparingTo("80.00");
        assertThat(view.getUnattributed().getCompensation()).isEqualByComparingTo("70.00");
        // 恒等式：合计 = Σ行 + 未归属（这里 Σ行为 0）
        assertThat(view.getTotals().getRework()).isEqualByComparingTo(view.getUnattributed().getRework());
        assertThat(view.getTotals().getCompensation())
                .isEqualByComparingTo(view.getUnattributed().getCompensation());
    }

    @Test
    @DisplayName("商品维度：订单行全无金额 ⇒ 按行数等分（仍是按比例的特例，不丢不编）")
    void productDimensionSplitsEquallyWhenWeightsAreMissing() {
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                item("o1", "p-A", "遮光布", null),
                item("o1", "p-B", "纱帘", null)));
        when(financeMapper.selectList(any())).thenReturn(List.of(refund("o1", "100")));

        var view = service.qualityCostBreakdown("product", null, null);

        assertThat(view.getRows()).hasSize(2);
        assertThat(view.getRows()).allSatisfy(r -> assertThat(r.getCompensation()).isEqualByComparingTo("50.00"));
    }

    // ── 报废工时（issue #7377 段 8）：报工三态里的 scrap，与返工同构 ──

    @Test
    @DisplayName("报废工时按工序维度成行：与返工**分列**，行合计含两者")
    void scrapLaborHasItsOwnColumn() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                rework("缝制", "po1", "1", "80", "priced", "2026-10-20"),
                scrap("缝制", "po1", "2", "30", "priced", "2026-10-20")));

        var view = service.qualityCostBreakdown("process", null, null);

        var row = view.getRows().get(0);
        assertThat(row.getRework()).isEqualByComparingTo("80.00");
        assertThat(row.getScrap()).isEqualByComparingTo("60.00");
        assertThat(row.getTotal()).isEqualByComparingTo("140.00");
        assertThat(view.getTotals().getScrap()).isEqualByComparingTo("60.00");
        assertThat(view.getTotals().getTotal()).isEqualByComparingTo("140.00");
    }

    @Test
    @DisplayName("🔴 恒等式：合计 = Σ行 + 未归属（报废工时也各归各的）")
    void scrapKeepsIdentity() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                scrap("缝制", "po1", "2", "30", "priced", "2026-10-20"),     // 60 → 有工序
                scrap(null, "po1", "1", "15", "priced", "2026-10-20")));     // 15 → 没工序名 ⇒ 未归属
        when(financeMapper.selectList(any())).thenReturn(List.of());

        var view = service.qualityCostBreakdown("process", null, null);

        BigDecimal rowScrap = view.getRows().stream().map(r -> r.getScrap())
                .reduce(BigDecimal.ZERO, BigDecimal::add);
        assertThat(rowScrap).isEqualByComparingTo("60.00");
        assertThat(view.getUnattributed().getScrap()).isEqualByComparingTo("15.00");
        assertThat(view.getTotals().getScrap()).isEqualByComparingTo(rowScrap.add(view.getUnattributed().getScrap()));
    }

    @Test
    @DisplayName("未定价的报废报工不计金额，但被数进 notes（未定价 ≠ 0 元）")
    void unpricedScrapIsCounted() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                scrap("缝制", "po1", "1", null, "unpriced", "2026-10-20")));

        var view = service.qualityCostBreakdown("process", null, null);

        assertThat(view.getRows()).isEmpty();
        assertThat(view.getUnattributed().getScrap()).isEqualByComparingTo("0");
        assertThat(String.join("|", view.getNotes())).contains("未定价");
    }

    @Test
    @DisplayName("商品维度：报废工时也按订单行小计占比摊")
    void scrapLaborIsAllocatedInProductDimension() {
        // 商品维度要经「报工 → 加工单 → 订单 → 行」⇒ 加工单得能查到订单
        customer("o1", "po1", "张记布艺", "13800000001");
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                item("o1", "p-A", "遮光布", "300"),
                item("o1", "p-B", "纱帘", "100")));
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                scrap("缝制", "po1", "1", "80", "priced", "2026-10-20")));

        var view = service.qualityCostBreakdown("product", null, null);

        var a = view.getRows().stream().filter(r -> "遮光布".equals(r.getLabel())).findFirst().orElseThrow();
        var b = view.getRows().stream().filter(r -> "纱帘".equals(r.getLabel())).findFirst().orElseThrow();
        assertThat(a.getScrap()).isEqualByComparingTo("60.00");
        assertThat(b.getScrap()).isEqualByComparingTo("20.00");
        assertThat(view.getTotals().getScrap()).isEqualByComparingTo("80.00");
    }
}
