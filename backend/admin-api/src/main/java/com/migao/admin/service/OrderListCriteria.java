package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.Order;
import com.migao.admin.time.BusinessClock;
import org.springframework.util.StringUtils;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.stream.Collectors;

/**
 * 订单列表的<b>查询条件</b>（issue #8681，P2-1e 收尾批）：下单时间窗的兜底解析 + 状态多值筛选。
 *
 * <h2>为什么单开一个类</h2>
 * <p>这两个成员在此之前住在 {@link OrderService} 门面里，属「静态契约面」。门面收尾批要跌到
 * &lt; 500 行，而<b>并进 {@link OrderQueryService}（当批现取 755 行）会越过 800 行的登记阈值</b>
 * （{@code tests/unit_ci_workflows/loc_ratchet_exemptions.json} 只许缩短，不拿它当出口）
 * ⇒ 单开本类。语义上也自洽：它们只服务于<b>列表查询</b>，唯一的生产消费方是
 * {@link OrderQueryService#getOrderPage} 与 {@link OrderQueryService#getMyOrderPage}。</p>
 *
 * <h2>搬运而不是重写</h2>
 * <p>两个方法体<b>逐字节</b>原样搬来（分支 / 边界 / 空值 / 半开区间口径一字未改）。外形只动了三处，
 * 逐条可对照：① 类名换了；② {@code applyStatusFilter} 的参数类型从全限定名归一到 import
 * （{@code com.baomidou...LambdaQueryWrapper<com.migao.admin.entity.Order>} →
 * {@code LambdaQueryWrapper<Order>}，同样两处 {@code Order::getStatus} 归一到 import）；
 * ③ {@code java.util.List} / {@code java.util.stream.Collectors} 归一到 import。
 * 判据（{@code OrderServiceTest} 的 3 条时间窗 + 1 条多值筛选断言）<b>一个字没改</b>，只换接收者。</p>
 */
final class OrderListCriteria {

    private OrderListCriteria() {
    }

    /**
     * 订单列表的**默认回溯窗口**（issue #7404：用户裁定「不允许查全部」／「最多回溯近 3 年」）。
     *
     * <p>只在不给下单时间范围时生效（见 {@code getOrderPage}）—— 显式区间原样透传，不被截断。
     * 取 3 年而不是 12 个月：常见诉求是「翻去年的单 / 客户查三年前的记录」，
     * 而 3 年窗口下单租户的订单量仍是万级（月订单几千），关键词 {@code LIKE '%kw%'} 逐行匹配在毫秒级。</p>
     */
    static final int DEFAULT_LOOKBACK_MONTHS = 36;

    /** 订单列表的生效时间窗：半开区间 {@code [start, end)}，两条边界**恒非空**（兜底在 {@link #resolveListWindow}）。 */
    record ListDateWindow(OffsetDateTime start, OffsetDateTime end) {
    }

    /**
     * 解析订单列表的**生效**下单时间窗（issue #7404）。
     *
     * <p>口径（顺序即安全顺序）：</p>
     * <ol>
     *   <li>显式给了 {@code startDate}/{@code endDate} ⇒ **原样**使用（要查更早的历史单，自己选日期即可）；</li>
     *   <li>没给起点 ⇒ 起点 = 「终止日（没给就是今天）− {@value #DEFAULT_LOOKBACK_MONTHS} 个月」；</li>
     *   <li>没给终点 ⇒ 终点 = 「今天 + 1 天」（与显式区间同口径的半开区间）。</li>
     * </ol>
     *
     * <p>⇒ 「忘选 / 清空日期」不再退化成**无时间谓词**的查询。为什么必须兜底：关键词是
     * {@code LIKE '%kw%'}（name / phone / order_no 三列 OR），B-tree 用不上 ⇒ 无时间谓词时是
     * 「本租户全部订单逐行匹配」，且分页每次 {@code COUNT(*)} 都要再来一遍。</p>
     *
     * <p>为什么是「补齐」而不是 400 拒绝：AI 侧 {@code logistics_track} 工具用
     * {@code GET /api/admin/orders?keyword=<单号>}（**不带日期**）解析订单号 —— 拒绝会让物流追踪当场坏掉。</p>
     */
    static ListDateWindow resolveListWindow(String startDate, String endDate, BusinessClock clock) {
        boolean hasStart = StringUtils.hasText(startDate);
        boolean hasEnd = StringUtils.hasText(endDate);
        LocalDate today = clock.today();
        LocalDate startDay = hasStart
                ? LocalDate.parse(startDate)
                : (hasEnd ? LocalDate.parse(endDate) : today).minusMonths(DEFAULT_LOOKBACK_MONTHS);
        LocalDate endDayExclusive = hasEnd ? LocalDate.parse(endDate).plusDays(1) : today.plusDays(1);
        return new ListDateWindow(clock.startOfDay(startDay), clock.startOfDay(endDayExclusive));
    }

    /**
     * 订单状态筛选：支持**逗号分隔多值**（issue #5792）。
     *
     * <p>为什么需要：前端「待发货」在业务上是 **`confirmed` + `producing`** 两个状态之和
     * （`frontend/admin-web/src/types/index.ts` 的映射注释已这么写），而后端此前只收单值
     * ⇒ 列表比计数少（看板卡说 N 条、点进去只看到其中一部分）。
     * 现按 `in` 处理 ⇒ 与计数的口径取齐（本仓同族缺陷的修法见 issue #5792 的口径整改）。</p>
     */
    static void applyStatusFilter(LambdaQueryWrapper<Order> wrapper, String status) {
        if (!StringUtils.hasText(status)) {
            return;
        }
        List<String> statuses = java.util.Arrays.stream(status.split(","))
                .map(String::trim)
                .filter(x -> !x.isEmpty())
                .distinct()
                .collect(Collectors.toList());
        if (statuses.size() == 1) {
            wrapper.eq(Order::getStatus, statuses.get(0));
        } else {
            wrapper.in(Order::getStatus, statuses);
        }
    }
}
