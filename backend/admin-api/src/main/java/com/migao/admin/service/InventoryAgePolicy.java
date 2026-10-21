package com.migao.admin.service;

import java.time.LocalDate;
import java.time.temporal.ChronoUnit;

/**
 * 库存周转与滞销的**判定**（issue #7376，P1-4 段 2）—— 纯函数。
 *
 * <h3>「滞销」的定义（写死在判据里，不留口头口径）</h3>
 * <p>滞销 = 还有货 **且** 距上次出库（或入库，若从未出过库）已满 {@link #SLOW_MOVING_DAYS} 天。
 * 两个边界都是刻意的：</p>
 * <ul>
 *   <li><b>没货的批次不算滞销</b>：0 库存的批次谈「压货」没有意义，列出来只会淹没有用的行；</li>
 *   <li><b>从未出过库 ⇒ 从入库日起算</b>：否则「一直没人动」的货永远不进入滞销清单（最该被看见的反而看不见）。</li>
 * </ul>
 *
 * <p>阈值取 <b>90 天</b>（家纺面料行业的常见换季周期），写在常量里并可用参数覆盖 ——
 * 它是**业务口径**，不是魔法数字，改的时候必须同时改判据说明。</p>
 */
public final class InventoryAgePolicy {

    /** 滞销阈值（天）：默认 90；调用方可传更小值做试算。 */
    public static final int SLOW_MOVING_DAYS = 90;

    /**
     * @param onHand        当前库存量（米）
     * @param lastMovement  上次出库日期（从未出库 ⇒ 传入库日期；两者都没有 ⇒ null）
     * @param today         业务日（由 {@code BusinessClock} 给出，不是系统 UTC 日）
     * @param thresholdDays 滞销阈值（<=0 ⇒ 用默认值）
     */
    public record Decision(boolean slowMoving, long daysSinceMovement, String reason) {
    }

    private InventoryAgePolicy() {
    }

    public static Decision evaluate(java.math.BigDecimal onHand, LocalDate lastMovement,
                                   LocalDate today, int thresholdDays) {
        int threshold = thresholdDays > 0 ? thresholdDays : SLOW_MOVING_DAYS;
        if (onHand == null || onHand.signum() <= 0) {
            // 没货 ⇒ 不是滞销（但也不是「周转良好」，所以 reason 说清为什么没判）
            return new Decision(false, -1, "无库存（不参与滞销判定）");
        }
        if (lastMovement == null || today == null) {
            // 连入库日都不知 ⇒ **判据不成立**：不猜 0 天，也不假装滞销
            return new Decision(false, -1, "缺少入库/出库日期（无法判定，不猜）");
        }
        long days = ChronoUnit.DAYS.between(lastMovement, today);
        if (days < 0) {
            // 未来日期（脏数据）⇒ 不判滞销，如实标记
            return new Decision(false, days, "日期在未来（脏数据，未判定）");
        }
        return new Decision(days >= threshold, days, days >= threshold
                ? String.format("满 %d 天未出库（阈值 %d 天）", days, threshold)
                : String.format("近 %d 天内有出库", days));
    }
}
