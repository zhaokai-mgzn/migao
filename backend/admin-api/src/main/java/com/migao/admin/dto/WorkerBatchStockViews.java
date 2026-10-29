package com.migao.admin.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * 工人端**批次库存修正**的读 / 写视图（issue #8104，用户 2026-10-29 逐字
 * 「手机端还要增加一个库存修正的功能……允许工人对某个批次的布匹进行修正」）。
 *
 * <p>与商家端 {@link BatchStockViews} 的分工：那个是**商家盘点面**（按货号一次盘全部批次、
 * 带省料/对账等经营读数）；本类是**工人车间面**（按批次找、按批次改、只回这一批的四个数）。
 * 两个面**共用同一份余量口径**（{@code StockBatchConsumptionService#remainingOfBatch} =
 * 入库量 + Σdelta），本类不另算一遍。</p>
 *
 * <p>🔴 金额/米数一律 {@link BigDecimal}（V115/#5063 的 0.1 米粒度），不在传输层转 double：
 * 工人填 42.5 米，屏上就必须是 42.5，不能变成 42.499999。</p>
 *
 * <p>🔴 字段一律 **snake_case**（{@code @JsonNaming}）：工人端其它读面（发货单 / 返工记录 / 计件）
 * 全是蛇形键，端侧服务层也照蛇形消费 —— 一个面用驼峰就是「多一层会漂的映射」，
 * 而漂的那一层不会变红。</p>
 */
public final class WorkerBatchStockViews {

    private WorkerBatchStockViews() {
    }

    /**
     * 搜索命中一个批次（工人据此确认「是这一批、系统说还剩这么多」）。
     *
     * <p>{@code productName} 由服务端补（批次表只存 {@code productId}）：工人认布靠品名 + 货号，
     * 不给品名就只能看见一串 {@code prod-xxx} —— 那是内部标识上屏（§31 P3）。</p>
     */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record BatchRow(
            Long batchId,
            String batchNo,
            String productId,
            String productName,
            String skuCode,
            String dyeLot,
            String inboundNo,
            LocalDate receivedDate,
            BigDecimal remainingMeters) {
    }

    /**
     * 搜索回执 = 分页行 + **修正原因闭词表**。
     *
     * <p>原因清单跟着读面一起下发（而不是端侧再写一份）：端侧的选项文案与后端校验的
     * 合法集合若各写一份，迟早出现「屏上能选、提交被拒」的第二份口径。</p>
     */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record BatchPage(
            List<BatchRow> items,
            long total,
            long page,
            long size,
            List<Reason> reasons) {
    }

    /** 修正原因（{@code code} 机器可判、{@code label} 给人看；取值集合 = {@code WorkerBatchStockService.REASONS}）。 */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Reason(String code, String label) {
    }

    /**
     * 一次修正的回执（**盘前 / 实盘 / 差异 / 盘后四个数一起回**，读的人不必自己减）。
     *
     * <p>{@code status} 与批次盘点的三态同源（见 {@link BatchStockViews#STOCKTAKE_APPLIED} 等）：
     * {@code applied} 真的落账 · {@code unchanged} 实盘 == 系统余量（零写入）·
     * {@code replayed} 同一次提交此前已记过账（幂等回放，未重复修正）。</p>
     */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Correction(
            String runId,
            Long batchId,
            String batchNo,
            String productName,
            String skuCode,
            String status,
            BigDecimal beforeMeters,
            BigDecimal actualMeters,
            BigDecimal deltaMeters,
            BigDecimal afterMeters,
            String workerName,
            String workerNo) {
    }
}
