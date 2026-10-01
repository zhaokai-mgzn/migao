package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 按批次库存盘点请求（V143 / issue #5865，**最小录入式** —— 不做盘点单实体）。
 *
 * <p>形态 = 「按货号列出批次与当前余量 → 填实盘米数 → 差异预览（前端算）→ 一次提交」：
 * 一次提交带**一个货号的全部实盘明细**，服务端在一个事务里把批次分录与 SKU 库存一起对齐。</p>
 *
 * <p>🔴 {@code runId} 是**幂等键**（照 {@code inbound_orders.import_run_id} 的先例，由调用方给）：
 * 同一次提交的网络重试 / 用户连点必须复用同一个 run id；换一个新的 run id 就是**新的一次盘点**
 * （会照常落账 —— 幂等只覆盖「同一次提交的重复请求」，不覆盖「两次真实盘点」）。
 * 与库存调整的口径一致：服务端**不猜**运行标识，缺它 ⇒ 400 显式拒绝。</p>
 */
@Data
public class BatchStocktakeRequest {

    /** 货号（商品 id）：批次按货号列，盘点也按货号提交（跨货号一次提交 = 两个事务面，本单不做） */
    private String productId;

    /** 盘点运行标识（幂等键，≤64 字符；同一次提交的重复请求必须复用同一个值） */
    private String runId;

    /** 实盘明细（一行 = 一个批次；同一批次在本次请求里不得出现两次） */
    private List<Line> lines;

    /** 一行的实盘米数（0.1 米粒度，沿用 {@code StockQuantity.requireOneDecimal}；负数/超精度 ⇒ 400） */
    @Data
    public static class Line {

        /** 批次主键（来自 {@code GET /api/admin/batch-stock/batches}） */
        private Long batchId;

        /** 实盘米数（米，最多 1 位小数） */
        private BigDecimal actualMeters;
    }
}
