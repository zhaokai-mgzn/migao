// case_ids: RPT-002
package com.migao.admin.service;

import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.StockBatchConsumption;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.StockBatchConsumptionMapper;
import com.migao.admin.mapper.StockBatchMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 库存滞销报表（issue #7376 段 2）—— 「上次出库日现算、不落派生列」与「合计=明细之和」。
 *
 * <p>不落列的理由：扣料/盘点/调拨都可能改变库存，落一列「最后出库日」就得在每个写面上同步，
 * 漏一处就永久漂 —— 报表宁可每次现算。</p>
 */
@DisplayName("滞销报表：现算上次出库 / 从未出库按入库日 / 合计与未判定计数")
class InventoryReportServiceTest {

    private OrderMapper orderMapper;
    private StockBatchMapper stockBatchMapper;
    private StockBatchConsumptionMapper consumptionMapper;
    private ReportService service;

    @BeforeEach
    void setUp() {
        orderMapper = Mockito.mock(OrderMapper.class);
        stockBatchMapper = Mockito.mock(StockBatchMapper.class);
        consumptionMapper = Mockito.mock(StockBatchConsumptionMapper.class);
        service = new ReportService(orderMapper, stockBatchMapper, null, null, consumptionMapper, null,
                new com.migao.admin.time.BusinessClock());
        when(consumptionMapper.selectList(any())).thenReturn(List.of());
    }

    private static StockBatch batch(Long id, String qty, java.time.LocalDate received) {
        StockBatch b = new StockBatch();
        b.setId(id);
        b.setTenantId(1L);
        b.setBatchNo("PC-000" + id);
        b.setSkuCode("SKU-" + id);
        b.setWarehouse("WH-A");
        b.setQuantity(new BigDecimal(qty));
        b.setReceivedDate(received);
        return b;
    }

    @Test
    @DisplayName("从未出库 + 入库很久 ⇒ 判滞销（最该被看见的货不能因为「没人动过」而隐身）")
    void neverMovedUsesReceivedDate() {
        java.time.LocalDate today = new com.migao.admin.time.BusinessClock().today();
        when(stockBatchMapper.selectList(any())).thenReturn(List.of(
                batch(1L, "100", today.minusDays(200))));

        var report = service.inventoryAging(null, null);

        assertThat(report.getRows()).hasSize(1);
        assertThat(report.getRows().get(0).isSlowMoving()).isTrue();
        assertThat(report.getTotals().getSlowMovingBatches()).isEqualTo(1);
        assertThat(report.getTotals().getSlowMovingOnHand()).isEqualByComparingTo("100");
    }

    @Test
    @DisplayName("最近出过库 ⇒ 不判滞销（出库日现算，不靠派生列）")
    void recentOutboundClearsSlowMoving() {
        ZoneId zone = new com.migao.admin.time.BusinessClock().zone();
        StockBatchConsumption recent = new StockBatchConsumption();
        recent.setBatchId(1L);
        recent.setDelta(new BigDecimal("-5"));
        recent.setCreatedAt(OffsetDateTime.now(zone).minusDays(3));
        when(consumptionMapper.selectList(any())).thenReturn(List.of(recent));
        // 🔴 业务日期只经 BusinessClock（issue #5651 收口）：测试里也不许裸 `LocalDate.now()`
        // —— 那在 UTC 16:00–24:00 与 +08 业务日差一天，判据会随跑测时刻飘。
        when(stockBatchMapper.selectList(any())).thenReturn(List.of(
                batch(1L, "100", new com.migao.admin.time.BusinessClock().today().minusDays(200))));

        var report = service.inventoryAging(null, null);

        assertThat(report.getRows().get(0).isSlowMoving())
                .as("出过库就以出库日为锚，而不是入库日").isFalse();
        assertThat(report.getTotals().getSlowMovingBatches()).isZero();
        assertThat(report.getTotals().getSlowMovingOnHand())
                .as("没有滞销批次 ⇒ 合计为 null（不是 0）").isNull();
    }

    @Test
    @DisplayName("空数据 ⇒ 合计为 null、hasData=false（与毛利报表同口径）")
    void emptyReportHasNullTotals() {
        when(stockBatchMapper.selectList(any())).thenReturn(List.of());

        var report = service.inventoryAging(null, null);

        assertThat(report.isHasData()).isFalse();
        assertThat(report.getTotals()).isNull();
    }

    @Test
    @DisplayName("缺日期的批次：不猜，计入 undeterminedRows")
    void missingAnchorIsCountedNotGuessed() {
        when(stockBatchMapper.selectList(any())).thenReturn(List.of(batch(1L, "50", null)));

        var report = service.inventoryAging(null, null);

        assertThat(report.getUndeterminedRows()).isEqualTo(1);
        assertThat(report.getRows().get(0).isSlowMoving()).isFalse();
    }

    @Test
    @DisplayName("阈值随报表自述（页面要显示「满 N 天未出库算滞销」）")
    void thresholdIsSelfDescribed() {
        when(stockBatchMapper.selectList(any())).thenReturn(List.of(
                batch(1L, "10", new com.migao.admin.time.BusinessClock().today().minusDays(31))));

        assertThat(service.inventoryAging(30, null).getRows().get(0).isSlowMoving()).isTrue();
        assertThat(service.inventoryAging(null, null).getRows().get(0).isSlowMoving())
                .as("默认 90 天 ⇒ 31 天不算").isFalse();
        assertThat(service.inventoryAging(null, null).getSlowMovingDays()).isEqualTo(90);
    }
}
