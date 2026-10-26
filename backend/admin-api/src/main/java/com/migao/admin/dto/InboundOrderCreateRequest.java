package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * 入库单建单/改单请求（V111，issue #5034；V117 / issue #5148 追加 source + importRunId）。
 *
 * <p>服务端校验（不靠注解 —— Agent/程序化调用不经过 Bean Validation，同 OrderService 口径）：
 * 供应商可空；明细至少 1 行；数量必须**大于 0 米**（V118/#5153 起，改前是 ≥1 米 —— 0.5 米的
 * 尾料因此进不来）且**最多 1 位小数**（V115/#5063 起，超 1 位小数由服务端显式拒绝、**不静默取整**）；
 * 单价可空但给了就必须 &gt; 0；SKU 必须属于本租户且属于所填商品；旧系统批次号只在
 * {@code source=opening} 时可填。</p>
 *
 * <p>幂等（V117 / issue #5148）：带 {@link #importRunId} 时按
 * {@code (tenantId, importRunId)} 去重 —— 同一份导入重跑**返回同一张单**，不会建出第二张
 * （两张都过账 = 库存加两次）。不带则与改前行为逐字一致。</p>
 */
@Data
public class InboundOrderCreateRequest {

    /** 供应商（可空） */
    private String supplier;

    /**
     * 供应商档案 id（可选，issue #7369 段 2）。
     *
     * <p>给了 ⇒ 服务端校验「本租户在用档案」，停用/跨租户一律拒；
     * 没给但 {@link #supplier} 文本能**精确匹配**到唯一一家在用档案 ⇒ 自动补上；
     * 都不成 ⇒ 留 NULL（进「待指派」清单，绝不猜）。
     */
    private String supplierId;

    /** 供应商送货单号（可空） */
    private String supplierDocNo;

    /** 仓库/仓位（可空） */
    private String warehouse;

    /**
     * 仓库 id（可空；issue #7799）—— 选了**真实仓库**时才带。
     *
     * <p>可空的理由：旧请求（工人拍照草稿 / Excel 期初导入 / 老客户端）只有文本 {@link #warehouse}，
     * 一律按原口径处理（{@code warehouse_id} 留空，行为一字不动）。带了就必须是**本租户在用**的仓，
     * 且不能是成品仓（成品单由打包自动产生）—— 校验与落库见
     * {@code InboundOrderService#createAndPost}。</p>
     */
    private Long warehouseId;

    /** 入库日期（可空 ⇒ 服务端取当天；可回填历史单） */
    private LocalDate inboundDate;

    /** 单据来源（可空 ⇒ purchase）：purchase 采购收货 / opening 期初建账；写别的值被拒 */
    private String source;

    /**
     * 建单**运行级**幂等键（可空）：一次导入运行的稳定标识。
     *
     * <p>同一 {@code (tenantId, importRunId)} 重跑建单 ⇒ 返回**已建的那张单**（不建第二张）。
     * 期初/迁移导入必须带它 —— 否则重跑会建出两张草稿单，两张都过账就是库存加两次。</p>
     */
    private String importRunId;

    private String remark;

    private List<Item> items;

    @Data
    public static class Item {

        /** 商品 ID（必填） */
        private String productId;

        /** SKU ID（必填 —— 库存权威是 SKU 级，见 issue #4038） */
        private Long skuId;

        /**
         * 数量：{@code purchase} / {@code opening} 单的**按米录入**值（= 入库米数，&gt;0 且最多 1 位小数，
         * V115/#5063）；{@code photo} 单（工人拍照入库，issue #6812）= **卷数**（正整数）。
         *
         * <p>🔴 带了 {@link #rollCount}（或来源是 photo）时本值**不决定库存**：入库米数一律由服务端按
         * 「卷数 × 卷长」算（{@code InboundOrderService.metersOfRolls}，issue #7709）——
         * 客户端的乘法曾让「1 卷 × 70 米」记成 1 米。</p>
         */
        private BigDecimal quantity;

        /** 入库单价（可空 = 未记单价 ⇒ 只加数量不算成本）；给了必须 > 0 */
        private BigDecimal unitCost;

        /** 供应商缸号（可空，外部事实） */
        private String dyeLot;

        /**
         * 旧系统批次号（可空，外部事实；V118 / issue #5153）—— **只在期初建账
         * （{@code source=opening}）时可填**，采购收货填了会被拒。
         *
         * <p>与 {@link #dyeLot} 一样是**外部事实**，原样登记；与系统生成的
         * {@code batch_no}（{@code PC-yyyyMMdd-NNNN}）**两列两义**，永不互相赋值
         * （V111 明令不得互相冒充）。过账时透传到 {@code stock_batches.legacy_batch_no}。</p>
         */
        private String legacyBatchNo;

        /**
         * 每卷米数（卷长）：与 {@link #rollCount} 成对时**参与换算**（入库米数 = 卷数 × 本值）；
         * 只填本值不填卷数 ⇒ 仅记录 / 打印卷标（#5034）。
         * {@code photo} 单（issue #6812）**必填**。
         */
        private BigDecimal rollLengthM;

        /**
         * 卷数（可空，正整数；issue #7709）：填了它就必须填 {@link #rollLengthM}，
         * **入库米数 = 本值 × 卷长**（服务端唯一换算点，{@link #quantity} 一律不采信）。
         *
         * <p>它是「1 卷」与「1 米」的**唯一判别器** —— 没有它，服务端只能猜（改前就猜错了：
         * `RK-20261024-0001` 的「数量 1 / 卷长 70」被记成 1 米）。{@code photo} 单不必填
         * （它的数量格本来就是卷数，建单时映射进本列）。</p>
         */
        private Integer rollCount;

        private String remark;
    }
}
