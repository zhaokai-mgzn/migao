// case_ids: PR-086, PR-087
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.ProductionPoolViews;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 🔴 <b>事件驱动自动成批派单 + 业务兜底（issue #5182 = 阶段 2b-3）的单元判据</b>。
 *
 * <h2>判据映射（每条都带**能单独让它红**的形态）</h2>
 * <ol>
 *   <li><b>默认关</b>（判据 1）：{@code AUTO_BATCH_DEFAULT_ENABLED=false} ⇒ {@code autoBatchDispatch}
 *       **零读零写**（连池都不查、一个 mapper 都不碰）。
 *       红证 = 把缺省改成 {@code true} ⇒ 本类的缺省用例当场红。</li>
 *   <li><b>事件驱动、不靠计时器</b>（判据 2）：① 结构性 —— 触发链上
 *       （{@code AutoBatchDispatchListener} / {@code PoolChangeNotifier} /
 *       {@code ProcessingOrderService}）**没有任何 {@code @Scheduled}**，且监听器是
 *       {@code @TransactionalEventListener(AFTER_COMMIT)}；② 行为性 —— **没有到期的单**
 *       （进池才 1 小时、到货日在 30 天后）在条件满足时**当次事件内**就成批。
 *       红证 = 把主触发改成「只在兜底扫描里」⇒ ②当场红（只有到期的单才会被派）。</li>
 *   <li><b>成批条件生效</b>（判据 3）：①②③ 各一条**只满足它**的夹具 ⇒ 成批；三条都不满足
 *       ⇒ **一次 {@code generate} 都不调**。红证 = 让条件恒真 ⇒ 第三条红。</li>
 *   <li><b>加急</b>（判据 5）：加急单**永不入池**且被**逐单立即派**（{@code pooled=false}），
 *       且它**不出现在**成批调用里。红证 = 让加急单参与池化 ⇒ 红。</li>
 *   <li><b>业务兜底</b>（判据 4 的算式面）：无到货日 ⇒ {@code 进池日 + 标准生产周期}；
 *       有到货日 ⇒ {@code 到货日 − 标准生产周期}。真库读数见 {@code AutoBatchDispatchRealDbTest}。</li>
 *   <li><b>幂等</b>（判据 7）：派过的单有了活跃加工单 ⇒ 下一次评估**看不见它** ⇒ 不重复派。</li>
 *   <li><b>失败可查</b>（判据 10）：三级降级都失败 ⇒ {@code failures} 非空，且监听器打出
 *       {@code INCIDENT_PRODUCTION_AUTO_BATCH_DISPATCH_FAILED}（grep 得到）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("#5182 自动成批：事件驱动 / 默认关 / 条件生效 / 加急 / 兜底 / 幂等 / 失败留痕")
class AutoBatchDispatchTest {

    private static final Long TENANT = 5182L;
    private static final String MATERIAL_PRODUCT = "prod-1";
    private static final String MATERIAL_SKU = "SKU-A";
    private static final String MATERIAL_KEY = MATERIAL_PRODUCT + "|" + MATERIAL_SKU;

    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ProcessingItemMapper processingItemMapper;
    @Mock
    private OrderService orderService;
    @Mock
    private ObjectMapper objectMapper;
    @Mock
    private ProductionService productionService;
    @Mock
    private ProductionOperationQueryService productionOperationQueryService;
    @Mock
    private ProductionOperationQtyClient productionOperationQtyClient;
    /** 批次台账（字段注入 ⇒ 显式装配，见 {@code realChainService()} 的同款理由）。 */
    @Mock
    private StockBatchConsumptionService stockBatchConsumptionService;

    private ProcessingOrderService service;

    /** 三级降级里 {@code generate} 被调到的**逐次入参快照**（判定「调了什么」的证据）。 */
    private final List<Call> calls = new ArrayList<>();

    private record Call(List<String> orderIds, Boolean pooled, String rule) {
    }

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        calls.clear();
        service = spy(new ProcessingOrderService(processingOrderMapper, orderMapper, orderItemMapper,
                processingItemMapper, orderService, objectMapper, productionService,
                productionOperationQueryService, productionOperationQtyClient));
        ReflectionTestUtils.setField(service, "stockBatchConsumptionService", stockBatchConsumptionService);
    }

    // ─────────────────────────────────────────── 判据 1：默认关

    @Test
    @DisplayName("🔴 判据1 默认关：不启用 ⇒ autoBatchDispatch **零读零写**（连池都不查）")
    void defaultOffDoesNothingAtAll() {
        assertThat(service.autoBatchPolicy().enabled())
                .as("🔴 缺省 = 关（红证：把 AUTO_BATCH_DEFAULT_ENABLED 改成 true ⇒ 本断言红）")
                .isFalse();

        ProcessingOrderService.AutoBatchOutcome outcome =
                service.autoBatchDispatch(TENANT, PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED);

        assertThat(outcome.enabled()).as("没有评估 ⇒ enabled=false（调用方据此不打日志，与今天逐值相同）")
                .isFalse();
        assertThat(outcome.dispatchedOrderNos()).isEmpty();
        assertThat(outcome.reasons()).isEmpty();
        verifyNoInteractions(orderMapper, orderItemMapper, processingOrderMapper,
                stockBatchConsumptionService);
        verify(service, never()).generate(anyList(), anyList(), any(), any(), any(), any());
    }

    // ─────────────────────────────────────────── 判据 2：事件驱动、不靠计时器

    @Test
    @DisplayName("🔴 判据2 行为：**没有到期的单**（进池 1 小时 / 到货日 30 天后）也当次事件即成批"
            + "（结构性判据在 AutoBatchDispatchListenerTest）")
    void batchingHappensOnTheEventEvenWhenNothingIsDue() {
        // 三张单都不满足兜底（进池 1~3 小时、到货日在 30 天后）；条件①③刻意满足
        // ⇒ 成批只能来自**条件判定**，不可能来自「兜底扫描」
        stubPool(List.of(order("o-1", "ORD-1", 3, false, LocalDate.now().plusDays(30)),
                order("o-2", "ORD-2", 1, false, LocalDate.now().plusDays(30))));
        stubGenerateOk();

        ProcessingOrderService.AutoBatchOutcome outcome =
                service.autoBatchDispatch(TENANT, PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED,
                        policy(80, "0.2", "3", 7));

        assertThat(outcome.enabled()).isTrue();
        assertThat(calls).as("🔴 事件到达即评估成批（不依赖任何计时器、也不是「只在兜底扫描里」）")
                .hasSize(1);
        assertThat(calls.get(0).pooled()).as("成批 = 池级一次求解").isTrue();
        assertThat(calls.get(0).orderIds()).containsExactly("o-1", "o-2");
        assertThat(outcome.reasons()).as("命中的是成批条件③（同物料需求 ≥ 最小批量）")
                .anySatisfy(reason -> assertThat(reason).contains("condition=min_batch"));
        assertThat(outcome.reasons()).as("**没有任何**兜底理由（这三张单都没到期）")
                .noneSatisfy(reason -> assertThat(reason).contains("business_due"));
    }

    // ─────────────────────────────────────────── 判据 3：成批条件

    @Test
    @DisplayName("判据3 条件①：需求 ≥ X% × 某批次入库量 ⇒ 成批")
    void fillRatioConditionTriggersBatching() {
        stubPool(List.of(order("o-fill", "ORD-FILL", 1, false, LocalDate.now().plusDays(30))));
        when(stockBatchConsumptionService.remaining(eq(TENANT), eq(MATERIAL_PRODUCT), eq(null), eq(false)))
                .thenReturn(List.of(batch("PC-FILL", "3", "3")));
        stubGenerateOk();

        ProcessingOrderService.AutoBatchOutcome outcome = service.autoBatchDispatch(TENANT, "t",
                policy(80, "0.05", "100", 7));

        assertThat(outcome.reasons()).anySatisfy(reason -> assertThat(reason).contains("condition=fill_ratio"));
        assertThat(calls).hasSize(1);
    }

    @Test
    @DisplayName("判据3 条件②：需求能把某批次余量收敛到 ≤0.2m（0 ≤ 余量 − 需求 ≤ 0.2）⇒ 成批")
    void convergeConditionTriggersBatching() {
        stubPool(List.of(order("o-conv", "ORD-CONV", 1, false, LocalDate.now().plusDays(30))));
        // 余量 3.1 − 需求 3.0 = 0.1 ≤ 0.2 ⇒ 命中；入库量 90 ⇒ 填满率 3.3% 不足以命中原①
        when(stockBatchConsumptionService.remaining(eq(TENANT), eq(MATERIAL_PRODUCT), eq(null), eq(false)))
                .thenReturn(List.of(batch("PC-CONV", "90", "3.1")));
        stubGenerateOk();

        ProcessingOrderService.AutoBatchOutcome outcome = service.autoBatchDispatch(TENANT, "t",
                policy(80, "0.2", "100", 7));

        assertThat(outcome.reasons()).anySatisfy(reason -> assertThat(reason).contains("condition=converge"));
        assertThat(calls).hasSize(1);
    }

    @Test
    @DisplayName("判据3 条件③：池内同物料需求 ≥ 最小批量 ⇒ 成批")
    void minBatchConditionTriggersBatching() {
        stubPool(List.of(order("o-min", "ORD-MIN", 1, false, LocalDate.now().plusDays(30))));
        stubGenerateOk();

        ProcessingOrderService.AutoBatchOutcome outcome = service.autoBatchDispatch(TENANT, "t",
                policy(80, "0.2", "3", 7));

        assertThat(outcome.reasons()).anySatisfy(reason -> assertThat(reason).contains("condition=min_batch"));
        assertThat(calls).hasSize(1);
    }

    @Test
    @DisplayName("🔴 判据3 三条都不满足 ⇒ **不派**（一次 generate 都不调）")
    void noConditionMetMeansNoDispatch() {
        stubPool(List.of(order("o-idle", "ORD-IDLE", 1, false, LocalDate.now().plusDays(30))));
        // 需求 3 米 / 批次 90 米：填满率 3.3% < 80%、余量 90 − 3 = 87 > 0.2、需求 3 < 最小批量 30
        when(stockBatchConsumptionService.remaining(eq(TENANT), eq(MATERIAL_PRODUCT), eq(null), eq(false)))
                .thenReturn(List.of(batch("PC-IDLE", "90", "90")));

        ProcessingOrderService.AutoBatchOutcome outcome = service.autoBatchDispatch(TENANT, "t",
                policy(80, "0.2", "30", 7));

        assertThat(outcome.reasons()).as("三条都不满足 ⇒ 没有命中规则").isEmpty();
        assertThat(calls).as("🔴 不成批（红证：让条件恒真 ⇒ 本断言红）").isEmpty();
        verify(service, never()).generate(anyList(), anyList(), any(), any(), any(), any());
    }

    // ─────────────────────────────────────────── 判据 5：加急

    @Test
    @DisplayName("🔴 判据5 加急单**永不入池**且被自动**逐单立即派**（pooled=false），不进成批调用")
    void urgentOrderIsNeverPooledAndIsDispatchedImmediately() {
        stubPool(List.of(order("o-urgent", "ORD-URGENT", 1, true, LocalDate.now().plusDays(30)),
                order("o-normal", "ORD-NORMAL", 1, false, LocalDate.now().plusDays(30))));
        stubGenerateOk();

        ProcessingOrderService.AutoBatchOutcome outcome = service.autoBatchDispatch(TENANT, "t",
                policy(80, "0.2", "3", 7));

        Call urgentCall = calls.stream().filter(c -> c.orderIds().equals(List.of("o-urgent")))
                .findFirst().orElseThrow();
        assertThat(urgentCall.pooled())
                .as("🔴 加急 = 复用 #5177 的手动插队路径（同一端点 + pooled=false）").isFalse();
        assertThat(outcome.reasons()).anySatisfy(reason -> assertThat(reason)
                .contains("urgent_never_pooled").contains("ORD-URGENT"));
        // 加急单**不进**成批那一批（用户裁定「加急的直接派、不加急的池优先」）
        assertThat(calls).filteredOn(c -> Boolean.TRUE.equals(c.pooled()))
                .allSatisfy(c -> assertThat(c.orderIds()).doesNotContain("o-urgent"));
    }

    // ─────────────────────────────────────────── 判据 4 的算式面 + 判据 7

    @Test
    @DisplayName("判据4算式：有到货日 ⇒ 到货日 − 周期；无到货日 ⇒ 进池日 + 周期（无依据 ⇒ null，不猜）")
    void latestDispatchDateIsDerivedFromDeliveryDateOrStandardCycle() {
        LocalDate today = LocalDate.now();
        ProductionPoolViews.PoolLine withDate = line(today.plusDays(10), OffsetDateTime.now());
        assertThat(ProcessingOrderService.latestDispatchDate(withDate, 7)).isEqualTo(today.plusDays(3));

        ProductionPoolViews.PoolLine withoutDate = line(null, OffsetDateTime.now().minusDays(30));
        assertThat(ProcessingOrderService.latestDispatchDate(withoutDate, 7))
                .as("无客户死线 ⇒ 标准生产周期本身就是「最多能攒多久」的约束")
                .isEqualTo(today.minusDays(23));

        assertThat(ProcessingOrderService.latestDispatchDate(line(null, null), 7))
                .as("两个依据都没有 ⇒ null（无从判定，不编一个日子）").isNull();
        assertThat(ProcessingOrderService.latestDispatchDate(withDate, 0))
                .as("周期非正 ⇒ 无兜底可言").isNull();
    }

    @Test
    @DisplayName("🔴 判据4 兜底必派：条件都不满足、但**最晚派单日已到** ⇒ 仍派（这是「不压单」的唯一死线）")
    void businessDueForcesDispatchEvenWhenNoConditionIsMet() {
        // 需求 3 米 / 批次 90 米（凑不满）；到货日 = 今天 ⇒ 最晚派单日 = 今天 − 7 = 已过 ⇒ 必派
        stubPool(List.of(order("o-due", "ORD-DUE", 1, false, LocalDate.now())));
        when(stockBatchConsumptionService.remaining(eq(TENANT), eq(MATERIAL_PRODUCT), eq(null), eq(false)))
                .thenReturn(List.of(batch("PC-DUE", "90", "90")));
        stubGenerateOk();

        ProcessingOrderService.AutoBatchOutcome outcome = service.autoBatchDispatch(TENANT, "t",
                policy(80, "0.2", "30", 7));

        assertThat(outcome.reasons()).anySatisfy(reason -> assertThat(reason)
                .contains("business_due").contains("ORD-DUE"));
        assertThat(calls).as("兜底派 = 池级一次（同批次候选池优先）").hasSize(1);
        assertThat(calls.get(0).orderIds()).containsExactly("o-due");
    }

    @Test
    @DisplayName("🔴 判据7 幂等：派过的单有了活跃加工单 ⇒ 下一次评估看不见它 ⇒ 不重复派、不重复扣")
    void secondTriggerAfterDispatchDoesNothing() {
        // 第一次：一张单，条件③命中
        stubPool(List.of(order("o-1", "ORD-1", 1, false, LocalDate.now().plusDays(30))));
        stubGenerateOk();
        ProcessingOrderService.AutoBatchOutcome first = service.autoBatchDispatch(TENANT, "t",
                policy(80, "0.2", "3", 7));
        assertThat(first.dispatchedOrderNos()).hasSize(1);

        // 第二次：同一张单**已有活跃加工单** ⇒ pool() 按同一口径把它排除（与
        // uk_processing_orders_active 逐字相同）⇒ 池空 ⇒ 不派
        calls.clear();
        when(processingOrderMapper.selectActiveOrderIds(eq(TENANT), anyCollection()))
                .thenReturn(List.of("o-1"));
        ProcessingOrderService.AutoBatchOutcome second = service.autoBatchDispatch(TENANT, "t",
                policy(80, "0.2", "3", 7));

        assertThat(second.dispatchedOrderNos()).as("🔴 重复触发不重复派").isEmpty();
        assertThat(calls).as("🔴 一次 generate 都没调（不重复扣——沿用 #5145 的闸）").isEmpty();
    }

    @Test
    @DisplayName("🔴 判据10 失败可查：三级降级都失败 ⇒ failures 非空 + 监听器打 INCIDENT 标记（有痕迹）")
    void failuresAreRecordedAndLeaveAnIncidentTrail() {
        enableProductionPolicy();
        stubPool(List.of(order("o-bad", "ORD-BAD", 1, false, LocalDate.now())));
        // 三级尝试全部失败（真实形态：状态不对 / 已有加工单 / 无候选批次）
        doAnswer(inv -> {
            note(inv.getArgument(0), inv.getArgument(5), inv.getArgument(4));
            List<ProcessingOrderService.GenerateResult> out = new ArrayList<>();
            for (String id : inv.<List<String>>getArgument(0)) {
                out.add(ProcessingOrderService.GenerateResult.fail(id, "FAKE", "夹具：派不出去", null));
            }
            return out;
        }).when(service).generate(anyList(), anyList(), any(), any(), any(), any());

        ch.qos.logback.classic.Logger logger = (ch.qos.logback.classic.Logger)
                org.slf4j.LoggerFactory.getLogger(AutoBatchDispatchListener.class);
        ch.qos.logback.core.read.ListAppender<ch.qos.logback.classic.spi.ILoggingEvent> appender =
                new ch.qos.logback.core.read.ListAppender<>();
        appender.start();
        logger.addAppender(appender);
        try {
            new AutoBatchDispatchListener(service).onPoolChanged(
                    new PoolChangeNotifier.PoolChanged(TENANT, "t"));

            assertThat(appender.list).anySatisfy(event -> assertThat(event.getFormattedMessage())
                    .as("🔴 失败必须留痕可查（grep INCIDENT_PRODUCTION_AUTO_BATCH_DISPATCH_FAILED）")
                    .contains(AutoBatchDispatchListener.INCIDENT_AUTO_BATCH_FAILED)
                    .contains("o-bad"));
        } finally {
            logger.detachAppender(appender);
        }
        assertThat(calls).as("三次尝试都试过了（①②③ 各级一次）").hasSize(3);
        assertThat(calls.get(1).pooled()).isFalse();
        assertThat(calls.get(2).rule()).as("③ = 不带规则（#5145 之前的缺省形态：不碰批次账）").isNull();
    }

    // ─────────────────────────────────────────── 夹具

    /**
     * 模拟**生产装配**：把 {@code @Value} 的三个属性打开（单测里没有 Spring 属性源
     * ⇒ 字段停在代码缺省「关」上，这正是判据 1 要的形态）。
     */
    private void enableProductionPolicy() {
        ReflectionTestUtils.setField(service, "autoBatchEnabled", true);
        ReflectionTestUtils.setField(service, "autoBatchFillRatioPercent",
                ProcessingOrderService.AUTO_BATCH_DEFAULT_FILL_RATIO_PERCENT);
        ReflectionTestUtils.setField(service, "autoBatchConvergeMeters",
                ProcessingOrderService.AUTO_BATCH_DEFAULT_CONVERGE_METERS);
        ReflectionTestUtils.setField(service, "autoBatchMinBatchMeters",
                ProcessingOrderService.AUTO_BATCH_DEFAULT_MIN_BATCH_METERS);
        ReflectionTestUtils.setField(service, "autoBatchStandardCycleDays",
                ProcessingOrderService.AUTO_BATCH_DEFAULT_STANDARD_CYCLE_DAYS);
        ReflectionTestUtils.setField(service, "autoBatchAssignmentRule",
                ProcessingOrderService.AUTO_BATCH_DEFAULT_ASSIGNMENT_RULE);
    }

    private ProcessingOrderService.AutoBatchPolicy policy(int fillRatio, String converge,
                                                          String minBatch, int cycleDays) {
        return ProcessingOrderService.AutoBatchPolicy.enabledPolicy()
                .with(fillRatio, converge, minBatch, cycleDays);
    }

    private void note(List<String> orderIds, Object pooled, Object rule) {
        calls.add(new Call(List.copyOf(orderIds), (Boolean) pooled, (String) rule));
    }

    /** 池夹具：确认支付态、无活跃加工单、每张单一行（物料 = 商品 × SKU）。 */
    private void stubPool(List<Order> orders) {
        when(orderMapper.selectList(any())).thenReturn(orders);
        when(processingOrderMapper.selectActiveOrderIds(eq(TENANT), anyCollection())).thenReturn(List.of());
        when(orderItemMapper.selectList(any())).thenReturn(List.of(item()));
    }

    private void stubGenerateOk() {
        AtomicInteger seq = new AtomicInteger();
        doAnswer(inv -> {
            note(inv.getArgument(0), inv.getArgument(5), inv.getArgument(4));
            List<ProcessingOrderService.GenerateResult> out = new ArrayList<>();
            for (String id : inv.<List<String>>getArgument(0)) {
                out.add(ProcessingOrderService.GenerateResult.ok(id, "JG-" + seq.incrementAndGet()));
            }
            return out;
        }).when(service).generate(anyList(), anyList(), any(), any(), any(), any());
    }

    private Order order(String id, String orderNo, int waitedHours, boolean urgent,
                        LocalDate requiredDeliveryDate) {
        return Order.builder().id(id).tenantId(TENANT).orderNo(orderNo).status("confirmed")
                .createdAt(OffsetDateTime.now().minusHours(waitedHours))
                .isUrgent(urgent).requiredDeliveryDate(requiredDeliveryDate).build();
    }

    private OrderItem item() {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", "米白");
        info.put("sellingMethod", "散剪");
        info.put("doorWidth", "2.8米");
        info.put("sku", MATERIAL_SKU);
        info.put("cuttingMode", "定高买宽");
        // 加工项：buildSnapshot 靠它认出「这一行有加工部位」⇒ 没有它的行不进池（既有口径）
        List<Map<String, Object>> procs = new ArrayList<>();
        Map<String, Object> proc = new LinkedHashMap<>();
        proc.put("id", "p1");
        proc.put("name", "打孔");
        proc.put("quantity", 2);
        proc.put("unit", "米");
        procs.add(proc);
        info.put("processingItems", procs);
        return OrderItem.builder().id("i-1").tenantId(TENANT).orderId("o-1")
                .productId(MATERIAL_PRODUCT).productName("布艺遮光帘A")
                .quantity(new BigDecimal("3")).width(new BigDecimal("1.5"))
                .height(new BigDecimal("1.1")).processingInfo(info).build();
    }

    private BatchStockViews.BatchRemaining batch(String batchNo, String inbound, String remaining) {
        return new BatchStockViews.BatchRemaining(1L, batchNo, MATERIAL_PRODUCT, 1L, MATERIAL_SKU,
                "RK-1", null, LocalDate.now(), new BigDecimal("12.5"), new BigDecimal(inbound),
                new BigDecimal(inbound).subtract(new BigDecimal(remaining)), new BigDecimal(remaining));
    }

    private ProductionPoolViews.PoolLine line(LocalDate requiredDeliveryDate, OffsetDateTime since) {
        return new ProductionPoolViews.PoolLine("o", "ORD", "i", MATERIAL_PRODUCT, "布艺遮光帘A",
                MATERIAL_SKU, new BigDecimal("3"), since, BigDecimal.ZERO, false, false,
                requiredDeliveryDate, null);
    }
}
