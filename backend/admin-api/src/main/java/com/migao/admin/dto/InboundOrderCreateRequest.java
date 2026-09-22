package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * 入库单建单/改单请求（V111，issue #5034）。
 *
 * <p>服务端校验（不靠注解 —— Agent/程序化调用不经过 Bean Validation，同 OrderService 口径）：
 * 供应商可空；明细至少 1 行；数量必须 ≥1 的整数；单价可空但给了就必须 &gt; 0；
 * SKU 必须属于本租户且属于所填商品。</p>
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

    private String remark;

    private List<Item> items;

    @Data
    public static class Item {

        /** 商品 ID（必填） */
        private String productId;

        /** SKU ID（必填 —— 库存权威是 SKU 级，见 issue #4038） */
        private Long skuId;

        /** 入库数量（必填，≥1 的整数；小数会被显式拒绝，见服务端校验） */
        /** 入库数量（米）：最多 1 位小数（V115/#5063）；超过 1 位小数由服务端显式拒绝 */
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
