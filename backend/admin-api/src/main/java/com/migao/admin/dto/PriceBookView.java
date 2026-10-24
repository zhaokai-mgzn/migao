package com.migao.admin.dto;

import lombok.Data;

import java.util.List;
import java.util.Map;

/** 价格本读面（issue #7375 段 3）：一个 SKU 的三层价格一次给全。 */
@Data
public class PriceBookView {

    private Long skuId;

    /** 传了客户 ⇒ 协议价只回该客户的。 */
    private String customerId;

    /**
     * 协议价（客户 × SKU）：`id / customer_id / price / customer_name`。
     *
     * <p>`customer_name` 是**展示名**（issue #7623）：微信昵称 → 手机号 → 「未命名客户」，
     * 客户档案不存在时「客户已移除」。`customer_id` 只给程序用（筛选 / 排查），**不上屏**。</p>
     */
    private List<Map<String, Object>> protocol;

    /** 等级价（VIP × SKU）：`id / vip_level / price`。 */
    private List<Map<String, Object>> vipLevels;

    /** 阶梯价（SKU + 门槛）：`id / min_qty / max_qty / price`。 */
    private List<Map<String, Object>> tiers;
}
