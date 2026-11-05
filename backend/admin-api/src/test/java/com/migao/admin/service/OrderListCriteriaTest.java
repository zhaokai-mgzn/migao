// case_ids: MC-245
package com.migao.admin.service;

import com.migao.admin.time.BusinessClock;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link OrderListCriteria} 的判据（issue #8681，P2-1e 收尾批）。
 *
 * <p><b>四条用例是从 {@code OrderServiceTest} 整体搬来的，断言一个字没改</b>（只换接收者：
 * {@code OrderService.applyStatusFilter} → {@code OrderListCriteria.applyStatusFilter}、
 * {@code OrderService.ListDateWindow}/{@code resolveListWindow} → 新载体同名成员）。
 * 搬家而不是重写：列表时间窗与状态筛选的唯一实现点已从门面搬到本类（门面 547 → 454 行，
 * {@code < 500} 判据达成），判据跟着实现点走。</p>
 *
 * <p><b>红证（会怎么红，逐条可复现）</b>：
 * ① 把 {@code resolveListWindow} 的兜底分支删掉（只保留显式区间）⇒ 前两条窗口断言必红；
 * ② 把 {@code DEFAULT_LOOKBACK_MONTHS} 从 36 改成 12 ⇒ 前两条的窗口断言必红；
 * ③ 让 {@code applyStatusFilter} 退回「只收单值」⇒ {@code statusFilterSupportsMultiValue} 必红
 * （多值那一段的 {@code status IN} 与两个参数值都不成立）。</p>
 */
@DisplayName("OrderListCriteria：订单列表的时间窗兜底 + 状态多值筛选（issue #8681 收尾批）")
class OrderListCriteriaTest {

    // ── issue #5792：状态筛选支持**逗号分隔多值**（前端「待发货」= confirmed + producing）──

    @Test
    @DisplayName("🔴 `applyStatusFilter`：单值用 =、多值用 IN（改前只收单值 ⇒ 列表比计数少）")
    void statusFilterSupportsMultiValue() throws Exception {
        // 单值：仍走等值（不因兼容多值而放宽成 IN —— 语义与既有行为一致）
        com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<com.migao.admin.entity.Order> one =
                new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<>();
        OrderListCriteria.applyStatusFilter(one, "confirmed");
        assertThat(one.getSqlSegment()).contains("status =").doesNotContain("IN");

        // 多值：IN 两个状态（这就是「待发货」的正确口径）
        com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<com.migao.admin.entity.Order> many =
                new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<>();
        OrderListCriteria.applyStatusFilter(many, "confirmed,producing");
        String seg = many.getSqlSegment();
        assertThat(seg).contains("status IN");
        assertThat(many.getParamNameValuePairs().values()).contains("confirmed", "producing");

        // 空/空白：不动 wrapper（不误加条件把列表清空）
        com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<com.migao.admin.entity.Order> none =
                new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<>();
        OrderListCriteria.applyStatusFilter(none, "  ");
        assertThat(none.getSqlSegment()).isEmpty();
    }

    // ── issue #7404：订单列表「不允许查全部」的时间窗兜底 ──────────────────────
    // 用户裁定：「需要做个兜底，不允许查全部」「最多回溯 近3年」。
    // 红证（会怎么红）：把 `OrderListCriteria.resolveListWindow` 的兜底分支删掉（只保留显式区间）⇒
    // `noDatesYieldsThreeYearWindow` / `endOnlyAnchorsAtEndDate` / `getOrderPageAppliesTheWindow` 必红；
    // 把 `DEFAULT_LOOKBACK_MONTHS` 从 36 改成 12 ⇒ 前两条的窗口断言必红。

    @Test
    @DisplayName("#7404 不给日期 ⇒ 窗口 = 最近 36 个月（而不是没有任何时间谓词）")
    void noDatesYieldsThreeYearWindow() {
        BusinessClock clock = new BusinessClock();
        OrderListCriteria.ListDateWindow window = OrderListCriteria.resolveListWindow(null, null, clock);

        assertThat(window.start()).isEqualTo(clock.startOfDay(clock.today().minusMonths(36)));
        assertThat(window.end()).isEqualTo(clock.startOfDay(clock.today().plusDays(1)));
    }

    @Test
    @DisplayName("#7404 只给截止日 ⇒ 起点 = 截止日往前 36 个月（以截止日为准，不是以今天）")
    void endOnlyAnchorsAtEndDate() {
        BusinessClock clock = new BusinessClock();
        OrderListCriteria.ListDateWindow window = OrderListCriteria.resolveListWindow(null, "2024-03-31", clock);

        assertThat(window.start()).isEqualTo(clock.startOfDay(java.time.LocalDate.parse("2021-03-31")));
        assertThat(window.end()).isEqualTo(clock.startOfDay(java.time.LocalDate.parse("2024-04-01")));
    }

    @Test
    @DisplayName("#7404 显式区间原样透传（查更早的单不被静默截断到 3 年）")
    void explicitRangePassesThrough() {
        BusinessClock clock = new BusinessClock();
        OrderListCriteria.ListDateWindow window = OrderListCriteria.resolveListWindow("2019-01-01", "2019-12-31", clock);

        assertThat(window.start()).isEqualTo(clock.startOfDay(java.time.LocalDate.parse("2019-01-01")));
        assertThat(window.end()).isEqualTo(clock.startOfDay(java.time.LocalDate.parse("2020-01-01")));
    }
}
