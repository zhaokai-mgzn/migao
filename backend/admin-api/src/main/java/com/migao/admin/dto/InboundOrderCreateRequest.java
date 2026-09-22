package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * 入库单建单/改单请求（V111，issue #5034；V117 / issue #5148 追加 source + importRunId）。
 *
 * <p>服务端校验（不靠注解 —— Agent/程序化调用不经过 Bean Validation，同 OrderService 口径）：
 * 供应商可空；明细至少 1 行；数量必须 ≥1 米且**最多 1 位小数**（V115/#5063 起，超 1 位小数
 * 由服务端显式拒绝、**不静默取整**）；单价可空但给了就必须 &gt; 0；SKU 必须属于本租户且属于所填商品。</p>
 *
 * <p>幂等（V117 / issue #5148）：带 {@link #importRunId} 时按
 * {@code (tenantId, importRunId)} 去重 —— 同一份导入重跑**返回同一张单**，不会建出第二张
 * （两张都过账 = 库存加两次）。不带则与改前行为逐字一致。</p>
 */
@Data
public class InboundOrderCreateRequest {

    /** 供应商（可空） */
    private String supplier;

    /** 供应商送货单号（可空） */
    private String supplierDocNo;

    /** 仓库/仓位（可空） */
    private String warehouse;

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

        /** 入库数量（米）：必填，≥1 且最多 1 位小数（V115/#5063）；超过 1 位小数由服务端显式拒绝 */
        private BigDecimal quantity;

        /** 入库单价（可空 = 未记单价 ⇒ 只加数量不算成本）；给了必须 > 0 */
        private BigDecimal unitCost;

        /** 供应商缸号（可空，外部事实） */
        private String dyeLot;

        /** 每卷米数（可空，仅记录/打印卷标） */
        private BigDecimal rollLengthM;

        private String remark;
    }
}
