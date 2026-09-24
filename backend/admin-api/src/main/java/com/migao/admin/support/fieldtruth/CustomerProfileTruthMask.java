package com.migao.admin.support.fieldtruth;

import com.migao.admin.entity.CustomerProfile;

/**
 * 「无真值」字段的<b>暴露面遮蔽</b>：读面一律置 {@code null}（= 未知），
 * 不得让 DB 列默认值（{@code 0} / {@code 0.00} / {@code 30}）或建档种子常量以「真值形态」流出去。
 *
 * <p>口径<b>照抄既有正确形态</b>（{@code product_skus.avg_cost} 的 {@code COMMENT ON COLUMN}）：
 * 「{@code NULL = 未知（存量库存无成本真值来源，一律不回填、不猜 0）}」/
 * 「不得用 {@code 0} 冒充「成本为零」」—— 客户画像上的 RFM 分、消费额、复购率同理：
 * 没有计算逻辑就不该以数值形态出现（页面与 Agent 同受约束）。
 *
 * <p>🔴 <b>本清单必须与 {@link CustomerProfileFieldTruth} 的 {@code NO_TRUTH} 集合一一对应</b>：
 * 少一行 ⇒ 商家/Agent 把 DB 默认 {@code 0} 当成「消费 0 元」（判据变红）；多一行 ⇒ 把真值抹成 null
 * （同样变红）。判据在
 * {@code CustomerProfileFieldTruthGateTest}（源码文本解析本文件的 {@code setXxx(null)} 行）与
 * {@code CustomerProfileTruthExposureTest}（行为断言）。
 *
 * <p>⚠️ <b>有意不反射遍历声明</b>：那样两份产物会合并成一份，判据就退化成自证 ——
 * 「声明改了、遮蔽没跟上」这一类漂移将永远不会红。显式逐行写出是<b>判据可咬</b>的前提。
 *
 * <p>⚠️ 遮蔽<b>只发生在读面</b>：建档路径（{@code createFromSession} / {@code createFromOrder}）
 * 仍照旧写种子值，写入语义一字未改（列默认值与存量回填属 A1 的口径设计）。
 */
public final class CustomerProfileTruthMask {

    private CustomerProfileTruthMask() {
    }

    /** 把声明为「无真值」的字段一律置 null（幂等；null 入参安全）。 */
    public static void apply(CustomerProfile p) {
        if (p == null) {
            return;
        }
        // 基础信息
        p.setWechatUnionid(null);
        p.setAvatarUrl(null);
        p.setRScore(null);
        // RFM 评分（无任何计算逻辑）
        p.setFScore(null);
        p.setMScore(null);
        p.setRfmTotalScore(null);
        // 统计数据（只有建档常量种子 / 零写入点）
        p.setTotalOrders(null);
        p.setTotalConsumption(null);
        p.setTotalRefundAmount(null);
        p.setAvgOrderValue(null);
        p.setRepurchaseRate(null);
        p.setLifecycleStage(null);
        // 时间字段（从未被写）
        p.setFirstOrderAt(null);
        p.setLastOrderAt(null);
        // 生命周期预测（从未被计算）
        p.setChurnRiskScore(null);
        p.setNextPurchasePredictionDays(null);
    }
}