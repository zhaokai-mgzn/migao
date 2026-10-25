package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * 出库单建单请求（V196，issue #7750）。
 *
 * <p>只服务**布料手工出库**：成品出库由发货动作自动建单（{@code source=ship}），
 * 不接受客户端手建 —— 手建一张成品出库单等于绕过发货流程把货发走。</p>
 *
 * <p>校验在服务端（与 {@code InboundOrderCreateRequest} 同口径：Agent/程序化调用不走 Bean Validation）：
 * 明细至少 1 行；数量 &gt; 0 且**最多 1 位小数**（与 {@code product_skus.stock} 的 NUMERIC(12,1) 同粒度）；
 * SKU 必须属于本租户；库存不足由**原子扣减**拒绝（不出现负库存）。</p>
 */
@Data
public class OutboundOrderCreateRequest {

    /** 仓库引用（可空 ⇒ 用默认仓；布料出库一般就是原料仓） */
    private Long warehouseId;

    /** 出库日期（可空 ⇒ 服务端取当天） */
    private LocalDate outboundDate;

    private String remark;

    private List<Item> items;

    @Data
    public static class Item {

        /** SKU ID（必填 —— 布料库存的权威是 SKU 级，见 issue #4038） */
        private Long skuId;

        /** 出库数量（米，&gt; 0 且最多 1 位小数） */
        private BigDecimal quantity;

        private String remark;
    }
}
