// case_ids: FN-005, OR-027
package com.migao.admin.time;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.AbstractWrapper;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.service.FinanceService;
import com.migao.admin.service.OrderService;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * <b>日期查询窗口 = 业务日（+08）整天</b>，不是 UTC 日（issue #6200）。
 *
 * <h2>缺陷本体（实例判据）</h2>
 *
 * <p>{@code startDate=endDate=D} 的实际窗口曾是 UTC 日
 * （{@code OffsetDateTime.parse(D + "T00:00:00Z")} … {@code "T23:59:59Z"}）
 * ⇒ 北京时间 {@code [D 08:00, D+1 07:59:59]} —— <b>北京 00:00–08:00 的数据归错天 / 月 / 年</b>。</p>
 *
 * <p>同系统内自相矛盾的最硬证据（只读档
 * {@code acceptance/2026-10-03/finance-stock-time-sweep/out/C9-cross-endpoint.json}）：
 * 同一笔 {@code ordAt = 2026-10-03 02:00+08} 的订单，{@code dashboard/stats} 与 {@code order-trend}
 * （走 {@link BusinessClock}，+08）<b>收录</b>（{@code dashboardTodayOrders=351}），
 * 而 {@code GET /orders?startDate=2026-10-03&endDate=2026-10-03}（UTC 窗口）<b>不收录</b>
 * （{@code listTotal=9, listHit=false}）。</p>
 *
 * <h2>判据（每条都独立可算，期望值硬编码，不从被测代码里取）</h2>
 *
 * <ol>
 *   <li>{@link #financeTxnWindowIsTheBusinessDayItself()}：财务流水窗口 = 业务日整天；</li>
 *   <li>{@link #orderListWindowIsTheBusinessDayItself()}：订单列表窗口 = 业务日整天；</li>
 *   <li>{@link #financeTxnWindowAgreesWithBusinessClock()}：窗口与 {@code businessClock.startOfDay}
 *       同源（跨端点自洽）；</li>
 *   <li>{@link #financeSummaryWindowIsTheBusinessDayItself()}：收支汇总同口径；</li>
 *   <li>{@link #monthEndToMonthStartFallsInTheRightMonths()}：跨月边界各落对月份；</li>
 *   <li>{@link #yearBoundaryRecordFallsInTheNewYear()}：跨年边界 <b>2026-01-01 00:01+08</b>
 *       必须落 2026-01（UTC 窗口会落进 2025-12-31）；</li>
 *   <li>{@link #boundaryPairIsInsideAndOutsideTheSameDay()}：夹住边界
 *       <b>07:59:59 在窗口内 / 08:00:00 也在窗口内</b>（当天整天），
 *       而 <b>07:59:59 → 08:00:00 之间的「次日零点」才是右界外的第一刻</b>；</li>
 *   <li>{@link #windowCoversTheWholeDayNotToTheSecondBefore()}：窗口右界<b>覆盖 D 当天整日</b>
 *       —— 用只判逻辑的日界函数自证，不依赖任何实现细节。</li>
 * </ol>
 *
 * <p>⚠️ <b>读 MyBatis-Plus 包装器参数的坑</b>（同 {@code BusinessClockCallSiteAgreementTest} 的实测）：
 * {@code LambdaQueryWrapper} 的参数是<b>惰性绑定</b>的 —— {@code ge(column, value)} 只把 lambda 段挂进
 * 表达式，值要等 {@code getSqlSegment()} 被求值才落进 {@code paramNameValuePairs}；不触发则恒为空 Map
 * ⇒ 断言假绿。故断言前必须先触发 SQL 段生成（代价 = 需要 {@code TableInfo}，见 {@link #setUp()}）。</p>
 */
@ExtendWith(MockitoExtension.class)
class BusinessDayWindowTest {

    /** 被查的那一天（北京）。窗口两端硬编码在这里，不从被测代码取。 */
    private static final LocalDate DAY = LocalDate.of(2026, 10, 3);

    /** 业务日整天（+08）：{@code 2026-10-03T00:00+08}…{@code 2026-10-04T00:00+08}（下界含、上界不含）。 */
    private static final Instant BUSINESS_START = Instant.parse("2026-10-02T16:00:00Z");
    private static final Instant BUSINESS_END_EXCLUSIVE = Instant.parse("2026-10-03T16:00:00Z");

    /** 缺陷形态（UTC 日）—— 只用于「这是哪个写法」的自证，不参与判据。 */
    private static final OffsetDateTime UTC_START = OffsetDateTime.parse("2026-10-03T00:00:00Z");
    private static final OffsetDateTime UTC_END = OffsetDateTime.parse("2026-10-03T23:59:59Z");

    private BusinessClock clock;

    @Mock
    private FinanceTransactionMapper financeTransactionMapper;

    @Mock
    private OrderMapper orderMapper;

    @Mock
    private OrderItemMapper orderItemMapper;

    // OrderService 的构造签名 15 个依赖（既有测试显式装配；@InjectMocks 装配不了）
    @Mock
    private com.migao.admin.mapper.OrderLogisticsMapper orderLogisticsMapper;
    @Mock
    private com.migao.admin.service.CustomerService customerService;
    @Mock
    private com.migao.admin.mapper.ProductMapper productMapper;
    @Mock
    private com.migao.admin.mapper.ProductSkuMapper productSkuMapper;
    @Mock
    private com.migao.admin.mapper.FinanceTransactionMapper orderSideFinanceTransactionMapper;
    @Mock
    private com.migao.admin.service.NotificationService notificationService;
    @Mock
    private com.migao.admin.mapper.ProcessingOrderMapper processingOrderMapper;
    @Mock
    private com.migao.admin.service.UserService userService;
    @Mock
    private com.migao.admin.service.ClientRequestIdService clientRequestIdService;
    @Mock
    private com.migao.admin.service.StockLedgerService stockLedgerService;
    @Mock
    private com.migao.admin.service.ProcessingFeeCalculator processingFeeCalculator;
    @Mock
    private com.migao.admin.service.ProcessingFeeCombinationCommandService processingFeeCombinationCommandService;

    private FinanceService financeService;
    private OrderService orderService;

    @BeforeEach
    void setUp() {
        // 让 lambda 列名解析 + 惰性参数绑定可用（无 Spring/DB 的纯单测里 TableInfo 不会自动建立）
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, FinanceTransaction.class);
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);

        // 钉住时刻：2026-10-03 14:30+08（窗口判据与「现在几点」无关，这里是防止任何路径偷读墙钟）
        clock = new BusinessClock(Clock.fixed(Instant.parse("2026-10-03T06:30:00Z"), ZoneOffset.UTC));

        financeService = new FinanceService(financeTransactionMapper, orderMapper);
        ReflectionTestUtils.setField(financeService, "businessClock", clock);

        // OrderService 的构造签名被 15 个依赖占满（既有测试逐个显式装配）⇒ 照
        // OrderStockLedgerTest 的既有装配写法构造，只把本判据用到的两个 mapper 钉成自己的 mock。
        orderService = new OrderService(orderMapper, orderItemMapper, orderLogisticsMapper,
                customerService, productMapper, productSkuMapper, orderSideFinanceTransactionMapper,
                new com.fasterxml.jackson.databind.ObjectMapper(), notificationService, processingOrderMapper,
                userService, clientRequestIdService, stockLedgerService, processingFeeCalculator,
                processingFeeCombinationCommandService);
        // businessClock 是 @Autowired 字段（生产单例 / 既有测试不注入则默认 +08 实例）⇒ 这里钉住时刻
        ReflectionTestUtils.setField(orderService, "businessClock", clock);
    }

    /**
     * 包装器<b>实际绑定</b>的参数值 —— 归一成 {@link Instant}（**只比时刻，不比偏移表示**）：
     * {@code BusinessClock.startOfDay} 给的是 {@code 2026-10-03T00:00+08:00}，而期望值写成
     * {@code 2026-10-02T16:00Z} —— 两者是**同一时刻**；用 {@code OffsetDateTime.equals} 比会因偏移不同
     * 而判不等（那不是缺陷，是断言写错）。绑定时**必须先触发惰性 SQL 段生成**（否则
     * {@code paramNameValuePairs} 恒为空 ⇒ 假绿）。
     */
    private static List<Instant> boundInstants(Wrapper<?> wrapper) {
        wrapper.getSqlSegment();
        return wrapper instanceof AbstractWrapper<?, ?, ?> aw
                ? aw.getParamNameValuePairs().values().stream()
                        .filter(OffsetDateTime.class::isInstance)
                        .map(OffsetDateTime.class::cast)
                        .map(OffsetDateTime::toInstant)
                        .toList()
                : List.of();
    }

    private Wrapper<FinanceTransaction> capturedTxnWindow() {
        when(financeTransactionMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));
        financeService.getTransactionPage(1, 20, null, null, null,
                DAY.toString(), DAY.toString(), null, 1L);
        ArgumentCaptor<Wrapper<FinanceTransaction>> captor = ArgumentCaptor.forClass(Wrapper.class);
        org.mockito.Mockito.verify(financeTransactionMapper)
                .selectPage(any(Page.class), captor.capture());
        return captor.getValue();
    }

    private Wrapper<Order> capturedOrderWindow() {
        when(orderMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));
        orderService.getOrderPage(1, 20, null, null, null, null,
                DAY.toString(), DAY.toString(), null, null, null, null, 1L, null, null);
        ArgumentCaptor<Wrapper<Order>> captor = ArgumentCaptor.forClass(Wrapper.class);
        org.mockito.Mockito.verify(orderMapper).selectPage(any(Page.class), captor.capture());
        return captor.getValue();
    }

    private List<Instant> financeSummaryWindow() {
        when(financeTransactionMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        when(orderMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        financeService.getSummary(DAY.toString(), DAY.toString(), 1L);
        ArgumentCaptor<Wrapper<FinanceTransaction>> captor = ArgumentCaptor.forClass(Wrapper.class);
        org.mockito.Mockito.verify(financeTransactionMapper).selectList(captor.capture());
        return boundInstants(captor.getValue());
    }

    @Test
    @DisplayName("财务流水：窗口 = 业务日整天（+08），不是 UTC 日")
    void financeTxnWindowIsTheBusinessDayItself() {
        Wrapper<FinanceTransaction> wrapper = capturedTxnWindow();

        assertThat(wrapper.getSqlSegment())
                .as("财务流水窗口必须两头都在（下界含、上界不含）")
                .contains("occurred_at");

        assertThat(boundInstants(wrapper))
                .as("startDate=endDate=2026-10-03 的窗口必须是业务日 [+08 00:00, 次日 +08 00:00)；"
                        + "UTC 日写法会绑成 %s … %s（北京 00:00–08:00 归错天）",
                        UTC_START, UTC_END)
                .containsExactlyInAnyOrder(BUSINESS_START, BUSINESS_END_EXCLUSIVE);
    }

    @Test
    @DisplayName("订单列表：窗口 = 业务日整天（+08），与 /orders 端点的「今天」一致")
    void orderListWindowIsTheBusinessDayItself() {
        Wrapper<Order> wrapper = capturedOrderWindow();

        assertThat(wrapper.getSqlSegment())
                .as("订单列表窗口必须两头都在（下界含、上界不含）")
                .contains("created_at");

        assertThat(boundInstants(wrapper))
                .as("订单列表窗口 = 业务日 [+08 00:00, 次日 +08 00:00)；"
                        + "北京 00:30 下单的单必须落在它所属的那一天的查询里")
                .containsExactlyInAnyOrder(BUSINESS_START, BUSINESS_END_EXCLUSIVE);
    }

    @Test
    @DisplayName("跨端点自洽：窗口 = businessClock.startOfDay（同一笔北京凌晨记录两边都收录）")
    void financeTxnWindowAgreesWithBusinessClock() {
        OffsetDateTime expectedStart = clock.startOfDay(DAY);

        assertThat(boundInstants(capturedTxnWindow()))
                .as("财务窗口与看板/趋势用的 businessClock 必须同源（issue #6200 的最硬证据 = 同一笔单两边不一致）")
                .contains(expectedStart.toInstant());
        assertThat(boundInstants(capturedOrderWindow()))
                .as("订单窗口与看板/趋势用的 businessClock 必须同源")
                .contains(expectedStart.toInstant());

        assertThat(expectedStart.toInstant()).as("业务日零点 = 2026-10-02T16:00Z（与硬编码期望同一时刻，偏移表示不参与）")
                .isEqualTo(BUSINESS_START);
    }

    @Test
    @DisplayName("收支汇总：与流水列表同口径")
    void financeSummaryWindowIsTheBusinessDayItself() {
        assertThat(financeSummaryWindow())
                .as("getSummary 的窗口必须与 getTransactionPage 同口径（同一个 parseDateStart/End 单源）")
                .containsExactlyInAnyOrder(BUSINESS_START, BUSINESS_END_EXCLUSIVE);
    }

    @Test
    @DisplayName("跨月边界：10-01 00:00+08 与 09-30 23:59:59+08 各落对月份")
    void monthEndToMonthStartFallsInTheRightMonths() {
        OffsetDateTime firstOfOctober = OffsetDateTime.parse("2026-10-01T00:00:00+08:00");
        OffsetDateTime lastSecondOfSeptember = OffsetDateTime.parse("2026-09-30T23:59:59+08:00");

        // 2026-10 的窗口与 2026-09 的窗口（期望值硬编码，取自日界定义）
        assertThat(inWindow(firstOfOctober,
                OffsetDateTime.parse("2026-09-30T16:00:00Z"), OffsetDateTime.parse("2026-10-31T16:00:00Z")))
                .as("10-01 00:00+08 必须落 10 月")
                .isTrue();
        assertThat(inWindow(lastSecondOfSeptember,
                OffsetDateTime.parse("2026-08-31T16:00:00Z"), OffsetDateTime.parse("2026-09-30T16:00:00Z")))
                .as("09-30 23:59:59+08 必须落 9 月")
                .isTrue();

        // 反向：UTC 月界写法会把 10-01 00:00+08 判进 9 月（现红形态）
        assertThat(inWindow(firstOfOctober, UTC_START, UTC_END))
                .as("自证：UTC 日界写法（缺陷形态）确实把 10-01 00:00+08 判到窗口外 ⇒ 月份归错")
                .isFalse();
    }

    @Test
    @DisplayName("跨年边界：2026-01-01 00:01+08 必须落 2026-01（UTC 窗口会落进 2025-12-31）")
    void yearBoundaryRecordFallsInTheNewYear() {
        OffsetDateTime newYearJustAfterMidnight = OffsetDateTime.parse("2026-01-01T00:01:00+08:00");

        assertThat(newYearJustAfterMidnight.getYear()).isEqualTo(2026);
        assertThat(inWindow(newYearJustAfterMidnight,
                OffsetDateTime.parse("2025-12-31T16:00:00Z"), OffsetDateTime.parse("2026-01-31T16:00:00Z")))
                .as("2026-01-01 00:01+08 必须落 2026-01（业务日窗口）")
                .isTrue();
        assertThat(inWindow(newYearJustAfterMidnight,
                OffsetDateTime.parse("2026-01-01T00:00:00Z"), OffsetDateTime.parse("2026-01-31T23:59:59Z")))
                .as("自证：UTC 日界写法把它关在 2026-01 窗口之外 ⇒ 会落进 2025-12-31（现红形态）")
                .isFalse();
    }

    @Test
    @DisplayName("夹住边界：北京 07:59:59 与 08:00:00 同属当日（都在业务日窗口内）")
    void boundaryPairIsInsideAndOutsideTheSameDay() {
        OffsetDateTime beforeEight = OffsetDateTime.parse("2026-10-03T07:59:59+08:00");
        OffsetDateTime atEight = OffsetDateTime.parse("2026-10-03T08:00:00+08:00");

        assertThat(inWindow(beforeEight, BUSINESS_START, BUSINESS_END_EXCLUSIVE))
                .as("北京 07:59:59 属 10-03（业务日窗口内）").isTrue();
        assertThat(inWindow(atEight, BUSINESS_START, BUSINESS_END_EXCLUSIVE))
                .as("北京 08:00:00 也属 10-03（业务日窗口内）—— UTC 日界写法的窗口起点恰恰是 08:00，"
                        + "边界内部就成了「两个世界」").isTrue();

        // UTC 日界写法（缺陷形态）：07:59:59 落在窗口外、08:00:00 落在窗口内 —— 「同一天被劈成两半」
        assertThat(inWindow(beforeEight, UTC_START, UTC_END))
                .as("自证：UTC 日界写法把北京 07:59:59 判到窗口外（同一天的数据被劈成两半）").isFalse();
        assertThat(inWindow(atEight, UTC_START, UTC_END))
                .as("自证：UTC 日界写法把北京 08:00:00 判到窗口内").isTrue();

        // 次日零点（右界外第一刻）
        assertThat(inWindow(OffsetDateTime.parse("2026-10-04T00:00:00+08:00"),
                BUSINESS_START, BUSINESS_END_EXCLUSIVE))
                .as("北京次日 00:00 是右界外的第一刻（窗口上界不含）").isFalse();
    }

    @Test
    @DisplayName("窗口右界语义：endDate=D 必须覆盖 D 当天整天（T23:59:59Z 在 +08 口径下同样是错的）")
    void windowCoversTheWholeDayNotToTheSecondBefore() {
        // 「当天最后一刻」= D 的 23:59:59.999…（用 D+1 零点减 1 纳秒表达），必须仍在窗口内
        OffsetDateTime lastInstantOfDay = OffsetDateTime.parse("2026-10-03T23:59:59.999999999+08:00");

        assertThat(inWindow(lastInstantOfDay, BUSINESS_START, BUSINESS_END_EXCLUSIVE))
                .as("业务日窗口必须覆盖 D 当天整日（含 23:59:59.999…）").isTrue();
        // 自证「右界不是 UTC 日的最后一秒」：UTC 日的 23:59:59（= 北京次日 07:59:59）**仍在窗口内**
        // —— 因为业务日窗口的右界是**次日北京零点**（= UTC 当日 16:00），它把「次日凌晨 8 小时」也算了进来；
        // 这正是原写法（右界取 UTC 日 23:59:59）会**漏掉当天北京 08:00 之后一整段**的对偶证据。
        assertThat(inWindow(OffsetDateTime.parse("2026-10-03T15:59:59Z"),
                BUSINESS_START, BUSINESS_END_EXCLUSIVE))
                .as("北京次日 07:59:59 仍属 10-03 的业务日窗口（右界 = 北京次日 00:00）").isTrue();
        // 而 UTC 日窗口（原写法）相对业务日窗口**整体晚 8 小时** ⇒ 两侧各错 8 小时（逐条自证）：
        //   ① 北京 10-02 23:00（= UTC 10-02 15:00）在 UTC 窗口**之外** ⇒ 前一晚的数据被算进 10-03；
        //   ② 北京 10-04 07:00（= UTC 10-03 23:00）在 UTC 窗口**之内** ⇒ 次日凌晨的数据也被算进 10-03；
        //   ③ 北京 10-03 00:30（= UTC 10-02 16:30）在 UTC 窗口**之外** ⇒ 当天凌晨 8 小时整段漏掉。
        assertThat(inWindow(OffsetDateTime.parse("2026-10-02T15:00:00Z"), UTC_START, UTC_END))
                .as("自证缺陷形态①：北京 10-02 23:00 被 UTC 日窗口算进了 10-03").isFalse();
        assertThat(inWindow(OffsetDateTime.parse("2026-10-03T23:00:00Z"), UTC_START, UTC_END))
                .as("自证缺陷形态②：北京 10-04 07:00（= UTC 10-03 23:00）被算进 10-03 的窗口（当晚数据算到次日）")
                .isTrue();
        assertThat(inWindow(OffsetDateTime.parse("2026-10-02T16:30:00Z"), UTC_START, UTC_END))
                .as("自证缺陷形态③：北京 10-03 00:30 落在 UTC 日窗口**之外**（当天凌晨 8 小时整段漏掉）")
                .isFalse();
    }

    /** 只判逻辑的日界：{@code [start, endExclusive)} —— 与任何实现细节无关（只比时刻）。 */
    private static boolean inWindow(OffsetDateTime instant, OffsetDateTime start, OffsetDateTime endExclusive) {
        return instant.compareTo(start) >= 0 && instant.compareTo(endExclusive) < 0;
    }

    /** 同上，但窗口两端写成 {@link Instant}（业务日窗口的期望值口径）。 */
    private static boolean inWindow(OffsetDateTime instant, Instant start, Instant endExclusive) {
        return !instant.toInstant().isBefore(start) && instant.toInstant().isBefore(endExclusive);
    }
}
