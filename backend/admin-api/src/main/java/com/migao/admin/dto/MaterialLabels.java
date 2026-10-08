package com.migao.admin.dto;

import org.springframework.util.StringUtils;

/**
 * 物料**展示名**的唯一组装处：{@code 商品名 × 颜色/门幅}。
 *
 * <h2>为什么必须有这一个地方（issue #6523 / #6535）</h2>
 * 「物料」的**机器键**是 {@code productId|skuCode}（{@code productId} 是 UUID）——
 * 它是 React {@code key} / {@code data-testid} / 分组与对账口径，**必须保持原样**；
 * 而**给人看的名字**曾直接拿机器键顶上 ⇒ 商家在「物料」列看到的是
 * {@code a61daac33e1a49974577d3ca81c4500b|SD07演示-2.8-8141273}。
 *
 * <p>两个读面（智能派单 {@code ProductionPoolViews.PoolGroup}、省料看板
 * {@code SavingMetricViews.SavedGroup}）都要这个人话名字。**若各写一份**，两处的
 * 缺值口径、分隔符、回退文案迟早漂成两套语义 —— 而这类漂移在页面上很难看出来
 * ⇒ 组装口径**只有这一份**（本类），两个读面都调它。</p>
 *
 * <p>⚠️ 已定的边界（不许放宽）：**前端不得自己拼**（那是第二份会漂的口径），
 * 也**不得**退回机器键（内部标识上屏）。</p>
 */
public final class MaterialLabels {

    /** 商品名缺失时的回退（**不猜、也不回退成机器键**）。 */
    public static final String UNNAMED_PRODUCT = "未命名商品";

    private MaterialLabels() {
    }

    /**
     * 组装展示名：{@code 商品名 × skuCode}（本系统里 {@code skuCode} 就是「颜色 × 门幅」的组合）。
     *
     * <p>缺值口径：商品名空 ⇒ {@value #UNNAMED_PRODUCT}（不是空串、不是机器键）；{@code skuCode} 空
     * ⇒ 只回商品名（**不补分隔符**，否则会渲染出一个悬空的 {@code ×}）。</p>
     */
    public static String materialLabel(String productName, String skuCode) {
        String name = StringUtils.hasText(productName) ? productName : UNNAMED_PRODUCT;
        return StringUtils.hasText(skuCode) ? name + " × " + skuCode : name;
    }
}
