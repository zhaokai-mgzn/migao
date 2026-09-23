// case_ids: PR-091, PR-092
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.AutoBatchDueScanHealthIndicator;
import com.migao.admin.config.AutoBatchDueScanScheduler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.Status;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.test.util.ReflectionTestUtils;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.RecordComponent;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Arrays;
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
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 🔴 <b>「到点自愈」的到期扫描腿（issue #5184）的单元判据。</b>
 *
 * <h2>判据映射（每条都带**能单独让它红**的形态；注入式红证见
 * {@code scripts/auto-batch-due-scan-red-proof.py}）</h2>
 * <ol>
 *   <li><b>到点自愈</b>（判据 1）：**不发布任何业务事件**、只调一次扫描腿 ⇒ 已过最晚派单日的单被派出。
 *       红证 = 去掉兜底判据（`today.isBefore(latest)` 恒为真）⇒ 本判据红。</li>
 *   <li><b>只查业务约束</b>（判据 2）：① 行为面 —— 池内等了 30 小时（超看板 24 小时上限）但**未到期**
 *       ⇒ **不派**；② 到期但**远未超窗** ⇒ 照派；③ 把等待上限改成 0.001h / 9999h ⇒ 派单结果与理由
 *       **逐值相同**；④ 结构性 —— 策略记录里**没有**任何新增的窗口类参数。
 *       红证 = 把判据换成 `PoolLine.overdue()`（池化窗口）⇒ ① 当场红。</li>
 *   <li><b>定时腿是兜底、不是第二条主触发</b>：满足成批条件③但未到期的单，扫描腿**一张都不派**
 *       （同夹具下事件腿会派）⇒ 定时腿**不**判优化条件。</li>
 *   <li><b>默认关</b>（判据 4）：开关关 ⇒ 扫描腿**零读零写**（连「有哪些租户」都不查）、零日志、零轮数。</li>
 *   <li><b>心跳可见</b>（判据 5）：读数是 {@code /actuator/health} 上的 details（轮数 / 最近成功时刻 /
 *       失败时刻 / 扫了几个租户 / 派了几张 / 最近错误），恒 UP（同 {@code MigrationHealthIndicator}）。
 *       红证 = 去掉 details 里的时间戳 ⇒ 本判据红。</li>
 *   <li><b>载体</b>：{@code @Scheduled} 只在**独立**的薄壳上（事件链三类仍无计时器，与 #5182 判据 2 并存）；
 *       触发原因 {@code due_scan} **不是**事件四类之一（来源可区分）。</li>
 *   <li><b>幂等 / 逐租户隔离 / fail-soft</b>（判据 3）：再次扫描不重复派（沿用 #5145 的闸）；
 *       一个租户炸了不影响其余租户；池读发生在**该租户**上下文里且退出还原（#3957 的坑）。</li>
 * </ol>
 *
 * <p>真库读数（无事件 + 已到期 ⇒ 真库派出；并发触发不重复派/不重复扣）见
 * {@code AutoBatchDueScanRealDbTest}。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("#5184 到期扫描腿：无事件也派 / 只查业务约束 / 默认关 / 幂等 / 心跳可见")
class AutoBatchDueScanServiceTest {

    private static final Long TENANT = 5184L;
    private static final Long OTHER_TENANT = 5185L;
    private static final String MATERIAL_PRODUCT = "prod-5184";
    private static final String MATERIAL_SKU = "SKU-A";

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
    @Mock
    private StockBatchConsumptionService stockBatchConsumptionService;

    private ProcessingOrderService service;
    private AutoBatchDueScanService scanner;

    /** 三级降级里 {@code generate} 被调到的**逐次入参快照**（判定「调了什么」的证据）。 */
    private final List<Call> calls = new ArrayList<>();
    /** 池读发生时的租户上下文快照（证明「池读在**该租户**上下文里」）。 */
    private final List<Long> tenantSeenInPoolRead = new ArrayList<>();
    /** 扫描腿逐租户拿到的读数（判定理由文案的证据面）。 */
    private final List<ProcessingOrderService.AutoBatchOutcome> scanOutcomes = new ArrayList<>();

    private record Call(List<String> orderIds, Boolean pooled, String rule, String operator) {
    }

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        calls.clear();
        tenantSeenInPoolRead.clear();
        scanOutcomes.clear();
        service = spy(new ProcessingOrderService(processingOrderMapper, orderMapper, orderItemMapper,
                processingItemMapper, orderService, objectMapper, productionService,
                productionOperationQueryService, productionOperationQtyClient));
        ReflectionTestUtils.setField(service, "stockBatchConsumptionService", stockBatchConsumptionService);
        scanner = new AutoBatchDueScanService(service, orderMapper);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ─────────────────────────────────────────── 判据 4：默认关

    @Test
    @DisplayName("🔴 判据4 默认关：自动成批未启用 ⇒ 扫描腿**零读零写**（连租户都不查 / 零日志 / 零轮数）")
    void defaultOffMeansZeroAction() {
        assertThat(service.autoBatchPolicy().enabled())
                .as("🔴 缺省 = 关（红证：把 AUTO_BATCH_DEFAULT_ENABLED 改成 true ⇒ 本断言红）")
                .isFalse();

        List<String> messages = captureLogs(() -> {
            AutoBatchDueScanService.DueScanOutcome outcome = scanner.scanDuePooledOrders();
            assertThat(outcome.enabled()).as("没有扫 ⇒ enabled=false").isFalse();
            assertThat(outcome.scannedTenants()).isZero();
            assertThat(outcome.dispatchedOrderNos()).isEmpty();
            assertThat(outcome.failures()).isEmpty();
        });

        verifyNoInteractions(orderMapper, orderItemMapper, processingOrderMapper);
        assertThat(scanner.getRounds()).as("零动作 ⇒ 连轮数都不记（记录期基线零污染）").isZero();
        assertThat(messages).as("缺省关 ⇒ 与今天逐值相同：一条日志都不打").isEmpty();
    }

    // ─────────────────────────────────────────── 判据 1：到点自愈

    @Test
    @DisplayName("🔴 判据1 到点自愈：**不产生任何业务事件**，已过最晚派单日的单在扫描时被派出 + 痕迹 auto:due_scan")
    void dueOrderIsDispatchedWithNoBusinessEvent() {
        enableProductionPolicy();
        captureScanOutcomes();
        // 到货日 = 今天 ⇒ 最晚派单日 = 今天 − 7 天 ⇒ **已过**（夹具里没有任何事件：没有确认支付、
        // 没有入库、没有改单取消 —— 定时腿是唯一输入）
        stubScanTenants();
        stubPool(List.of(order("o-due", "ORD-DUE", 1, LocalDate.now())));
        stubGenerateOk();

        AutoBatchDueScanService.DueScanOutcome outcome = scanner.scanDuePooledOrders();

        assertThat(outcome.enabled()).isTrue();
        assertThat(outcome.scannedTenants()).isEqualTo(1);
        assertThat(outcome.dispatchedOrderNos()).as("🔴 到点自愈：无事件也派出去").containsExactly("JG-1");
        assertThat(outcome.failures()).isEmpty();
        assertThat(calls).hasSize(1);
        assertThat(calls.get(0).orderIds()).containsExactly("o-due");
        assertThat(calls.get(0).pooled()).as("兜底派 = 池级一次（同批次候选池优先）").isTrue();
        assertThat(calls.get(0).operator())
                .as("🔴 来源可区分：generated_by = auto:<触发原因>:<规则>，触发原因 = due_scan")
                .isEqualTo(ProcessingOrderService.AUTO_BATCH_OPERATOR_PREFIX
                        + ProcessingOrderService.AUTO_BATCH_TRIGGER_DUE_SCAN + ":fifo");
        assertThat(scanOutcomes).hasSize(1);
        assertThat(scanOutcomes.get(0).reasons()).anySatisfy(reason -> assertThat(reason)
                .contains("business_due").contains("ORD-DUE"));
    }

    @Test
    @DisplayName("🔴 定时腿是**兜底**不是主触发：满足成批条件③但未到期 ⇒ 扫描腿一张都不派（同夹具事件腿会派）")
    void scanOnlyChecksBusinessDueNotBatchConditions() {
        enableProductionPolicy();
        // 需求 30 米 ≥ 最小批量 30 米 ⇒ 成批条件③**满足**；但到货日 = 今天 + 30 ⇒ 最晚派单日 = 今天 + 23
        // ⇒ **未到期**（兜底不成立）
        stubScanTenants();
        stubPool(List.of(order("o-batch", "ORD-BATCH", 1, LocalDate.now().plusDays(30))), "30");
        stubGenerateOk();

        AutoBatchDueScanService.DueScanOutcome scanned = scanner.scanDuePooledOrders();

        assertThat(scanned.dispatchedOrderNos()).as("🔴 定时腿不判优化条件（只做业务兜底）").isEmpty();
        assertThat(calls).as("一次 generate 都没调").isEmpty();

        // 对照：同一份池走**事件腿**（新单入池）⇒ 条件③命中 ⇒ 当场成批（主触发没变，仍是事件）
        ProcessingOrderService.AutoBatchOutcome eventOutcome = service.autoBatchDispatch(
                TENANT, PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED, service.autoBatchPolicy());
        assertThat(eventOutcome.dispatchedOrderNos()).as("事件腿照旧按条件③成批").hasSize(1);
        assertThat(eventOutcome.reasons()).anySatisfy(reason -> assertThat(reason)
                .contains("condition=min_batch"));
        assertThat(eventOutcome.reasons()).as("事件腿也没走兜底（这张单没到期）")
                .noneSatisfy(reason -> assertThat(reason).contains("business_due"));
    }

    // ─────────────────────────────────────────── 判据 2：只查业务约束（无窗口参数）

    @Test
    @DisplayName("🔴 判据2 红证：池内等了 30 小时（超看板 24 小时上限）但**未到期** ⇒ 扫描腿不派")
    void overdueButNotDueIsNotDispatched() {
        enableProductionPolicy();
        // waitHours = 30 > maxWaitHours(24) ⇒ 池看板会告警（overdue=true）；但到货日在 30 天后
        // ⇒ 最晚派单日 = 今天 + 23 ⇒ 未到期 ⇒ 一张都不许派
        stubScanTenants();
        stubPool(List.of(order("o-wait", "ORD-WAIT", 30, LocalDate.now().plusDays(30))));
        // 🔴 桩必须在场：否则「没派」与「试了但失败/抛异常」在读数上**不可区分** ⇒ 断言会退化成空断言
        //（红证实测：拿掉这个桩，把池化窗口当死线的变异就喂不红本条判据）
        stubGenerateOk();

        AutoBatchDueScanService.DueScanOutcome outcome = scanner.scanDuePooledOrders();

        assertThat(outcome.dispatchedOrderNos())
                .as("🔴 池化窗口是**优化参数**、不是派单死线：把它当死线正是用户逐字否掉的形态")
                .isEmpty();
        assertThat(calls).as("窗口到点不得触发任何派单").isEmpty();
    }

    @Test
    @DisplayName("🔴 判据2 只查业务约束：进池才 1 小时（远未到窗口上限）但已过最晚派单日 ⇒ 照派")
    void dueButWithinWindowIsDispatched() {
        enableProductionPolicy();
        captureScanOutcomes();
        stubScanTenants();
        stubPool(List.of(order("o-due", "ORD-DUE", 1, LocalDate.now())));
        stubGenerateOk();

        AutoBatchDueScanService.DueScanOutcome outcome = scanner.scanDuePooledOrders();

        assertThat(outcome.dispatchedOrderNos()).as("🔴 判据只看「今天 ≥ 最晚派单日」").hasSize(1);
        assertThat(scanOutcomes.get(0).reasons()).anySatisfy(reason -> assertThat(reason)
                .as("理由里出现的是**业务到期**，不是「窗口超时」").contains("business_due"));
    }

    @Test
    @DisplayName("🔴 判据2 无窗口参数：把等待上限调成 0.001h / 9999h ⇒ 派单结果与理由**逐值相同**")
    void dispatchSetIsInvariantToWaitWindow() {
        enableProductionPolicy();
        stubPool(List.of(order("o-due", "ORD-DUE", 1, LocalDate.now())));
        stubGenerateOk();

        ProcessingOrderService.AutoBatchOutcome tiny = service.autoBatchDispatchDue(TENANT,
                ProcessingOrderService.AUTO_BATCH_TRIGGER_DUE_SCAN, policy(0.001));
        List<Call> tinyCalls = List.copyOf(calls);
        calls.clear();
        ProcessingOrderService.AutoBatchOutcome huge = service.autoBatchDispatchDue(TENANT,
                ProcessingOrderService.AUTO_BATCH_TRIGGER_DUE_SCAN, policy(9999));

        assertThat(tiny.dispatchedOrderNos()).hasSize(1);
        assertThat(huge.dispatchedOrderNos()).as("🔴 派不派与等待上限**无关**（判据里没有这个入参）")
                .hasSize(1);
        assertThat(huge.reasons()).as("理由文案也逐值相同").isEqualTo(tiny.reasons());
        assertThat(calls).hasSize(1);
        assertThat(calls.get(0).orderIds()).isEqualTo(tinyCalls.get(0).orderIds());
    }

    @Test
    @DisplayName("🔴 判据2 结构性：策略里**没有**任何「窗口 / 等待时长上限」类新增参数（只有既有的看板告警上限）")
    void noWaitWindowParameterWasIntroduced() {
        assertThat(Arrays.stream(ProcessingOrderService.AutoBatchPolicy.class.getRecordComponents())
                .map(RecordComponent::getName).toList())
                .as("🔴 本单不得引入池化窗口参数：新增任何窗口/超时入参都会让本断言红"
                        + "（既有 maxWaitHours 是看板告警口径，不参与派单判定）")
                .containsExactly("enabled", "fillRatioPercent", "convergeMeters", "minBatchMeters",
                        "standardCycleDays", "assignmentRule", "maxWaitHours");
    }

    // ─────────────────────────────────────────── 判据 5：心跳可见

    @Test
    @DisplayName("🔴 判据5 心跳可见：轮数 / 最近成功时刻 / 扫到的租户 / 派出的张数 落在 /actuator/health 上")
    void heartbeatIsVisibleOnTheActuatorHealthSurface() {
        enableProductionPolicy();
        AutoBatchDueScanHealthIndicator indicator = new AutoBatchDueScanHealthIndicator(scanner);

        Health before = indicator.health();
        assertThat(before.getStatus()).as("恒 UP：不熔断（同 MigrationHealthIndicator 的理由）")
                .isEqualTo(Status.UP);
        assertThat(before.getDetails()).containsEntry("enabled", true).containsEntry("rounds", 0L);
        assertThat(before.getDetails().get("last_success_at"))
                .as("还没跑过 ⇒ 心跳为 null（「没跑」必须长得像「没跑」）").isNull();

        stubScanTenants();
        stubPool(List.of(order("o-due", "ORD-DUE", 1, LocalDate.now())));
        stubGenerateOk();
        scanner.scanDuePooledOrders();

        Health after = indicator.health();
        assertThat(after.getStatus()).isEqualTo(Status.UP);
        assertThat(after.getDetails()).containsEntry("rounds", 1L)
                .containsEntry("last_scanned_tenants", 1)
                .containsEntry("last_dispatched", 1)
                .containsEntry("last_error", null);
        assertThat(String.valueOf(after.getDetails().get("last_success_at")))
                .as("🔴 心跳 = 一个**能看出停摆**的时刻（红证：去掉这个时间戳 ⇒ 本断言红）")
                .startsWith(LocalDate.now().toString());
        assertThat(after.getDetails().get("last_failure_at")).isNull();
    }

    // ─────────────────────────────────────────── 载体：@Scheduled 只在独立薄壳上

    @Test
    @DisplayName("🔴 载体：@Scheduled 只在**独立**的定时腿薄壳上（事件链三类仍无计时器）+ 触发原因不是事件四类")
    void carrierIsASeparateScheduledLeg() throws Exception {
        Method tick = AutoBatchDueScanScheduler.class.getMethod("scanDuePooledOrders");
        Scheduled scheduled = tick.getAnnotation(Scheduled.class);
        assertThat(scheduled)
                .as("载体 = 仓内既有范式（@EnableScheduling + @Scheduled 薄壳，同 BriefingScheduler）")
                .isNotNull();
        assertThat(scheduled.cron()).as("周期可配、缺省值只有这一处")
                .contains("due-scan-cron").contains(AutoBatchDueScanScheduler.DUE_SCAN_DEFAULT_CRON);
        assertThat(AutoBatchDueScanScheduler.DUE_SCAN_DEFAULT_CRON)
                .as("约定窗口 = 一个扫描周期（5 分钟）+ 单轮耗时").isEqualTo("0 */5 * * * *");

        // #5182 判据 2 的互补面：定时腿是**另一个**载体，事件链本身仍然一点计时器都没有
        for (Class<?> type : List.of(AutoBatchDispatchListener.class, PoolChangeNotifier.class,
                ProcessingOrderService.class)) {
            for (Method method : type.getDeclaredMethods()) {
                assertThat(method.isAnnotationPresent(Scheduled.class))
                        .as("🔴 定时腿是兜底不是主触发：事件链 %s.%s 上不得出现 @Scheduled",
                                type.getSimpleName(), method.getName())
                        .isFalse();
            }
        }
        for (Field field : AutoBatchDispatchListener.class.getDeclaredFields()) {
            assertThat(field.getType().getSimpleName())
                    .as("事件链不依赖定时腿（反向依赖会把兜底变成主触发）").doesNotContain("DueScan");
        }
        assertThat(List.of(PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED,
                        PoolChangeNotifier.TRIGGER_INBOUND_POSTED,
                        PoolChangeNotifier.TRIGGER_ORDER_UPDATED,
                        PoolChangeNotifier.TRIGGER_ORDER_CANCELLED))
                .as("定时腿的触发原因是**第五个**取值 ⇒ generated_by 上来源可区分")
                .doesNotContain(ProcessingOrderService.AUTO_BATCH_TRIGGER_DUE_SCAN);
    }

    // ─────────────────────────────────────────── 判据 3 + 逐租户隔离 + fail-soft

    @Test
    @DisplayName("🔴 判据3 幂等：派过的单已有活跃加工单 ⇒ 下一轮扫描不再派（不重复扣）")
    void secondScanDoesNotDispatchAgain() {
        enableProductionPolicy();
        stubScanTenants();
        stubPool(List.of(order("o-due", "ORD-DUE", 1, LocalDate.now())));
        stubGenerateOk();
        assertThat(scanner.scanDuePooledOrders().dispatchedOrderNos()).hasSize(1);

        calls.clear();
        when(processingOrderMapper.selectActiveOrderIds(eq(TENANT), anyCollection()))
                .thenReturn(List.of("o-due"));
        AutoBatchDueScanService.DueScanOutcome second = scanner.scanDuePooledOrders();

        assertThat(second.dispatchedOrderNos()).as("🔴 重复扫描不重复派").isEmpty();
        assertThat(calls).as("🔴 一次 generate 都没调（不重复扣 —— 沿用 #5145 的闸）").isEmpty();
        assertThat(scanner.getRounds()).as("但轮数照记（心跳要能看出「跑过」）").isEqualTo(2);
    }

    @Test
    @DisplayName("🔴 判据3 逐租户隔离：一个租户炸了不影响其余租户；池读在**该租户**上下文里且退出还原（#3957）")
    void tenantFailureDoesNotStopOthersAndContextIsRestored() {
        enableProductionPolicy();
        when(orderMapper.selectConfirmedTenantIds()).thenReturn(List.of(OTHER_TENANT, TENANT));
        when(orderMapper.selectList(any())).thenAnswer(inv -> {
            tenantSeenInPoolRead.add(TenantContext.getTenantId());
            return List.of(order("o-due", "ORD-DUE", 1, LocalDate.now()));
        });
        when(processingOrderMapper.selectActiveOrderIds(any(), anyCollection())).thenReturn(List.of());
        when(orderItemMapper.selectList(any())).thenReturn(List.of(item("30")));
        stubGenerateOk();
        doThrow(new IllegalStateException("夹具：这个租户的池炸了"))
                .when(service).autoBatchDispatchDue(OTHER_TENANT);

        // 模拟「调度线程上一个任务留下的上下文」⇒ 扫完必须还原，不能漏给下一个任务
        TenantContext.setTenantId(999L);
        List<String> messages = captureLogs(() -> {
            AutoBatchDueScanService.DueScanOutcome outcome = scanner.scanDuePooledOrders();

            assertThat(outcome.scannedTenants()).isEqualTo(2);
            assertThat(outcome.dispatchedOrderNos()).as("坏租户不影响好租户").hasSize(1);
            assertThat(outcome.failures()).anySatisfy(failure -> assertThat(failure)
                    .contains("tenant=" + OTHER_TENANT));
        });

        assertThat(tenantSeenInPoolRead).as("池读必须发生在**该租户**的上下文里（#3957 的坑）")
                .containsExactly(TENANT);
        assertThat(TenantContext.getTenantId()).as("调度线程复用 ⇒ 退出必须还原上下文")
                .isEqualTo(999L);
        assertThat(messages).anySatisfy(message -> assertThat(message)
                .as("失败不留白：grep INCIDENT_PRODUCTION_AUTO_BATCH_DUE_SCAN_FAILED")
                .contains(AutoBatchDueScanService.INCIDENT_DUE_SCAN_FAILED));
        assertThat(scanner.getLastError()).contains("tenant=" + OTHER_TENANT);
        assertThat(new AutoBatchDueScanHealthIndicator(scanner).health().getDetails())
                .as("失败也在心跳里看得见（last_error 非空）").doesNotContainEntry("last_error", null);
    }

    // ─────────────────────────────────────────── 夹具

    /** 模拟**生产装配**：把 {@code @Value} 属性打开（单测里没有 Spring 属性源 ⇒ 字段停在缺省「关」上）。 */
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

    /** 到期扫描的策略（只改**等待上限**这一个入参 ⇒ 用于「派单结果与窗口无关」那条判据）。 */
    private ProcessingOrderService.AutoBatchPolicy policy(double maxWaitHours) {
        return new ProcessingOrderService.AutoBatchPolicy(true,
                ProcessingOrderService.AUTO_BATCH_DEFAULT_FILL_RATIO_PERCENT,
                new BigDecimal(ProcessingOrderService.AUTO_BATCH_DEFAULT_CONVERGE_METERS),
                new BigDecimal(ProcessingOrderService.AUTO_BATCH_DEFAULT_MIN_BATCH_METERS),
                ProcessingOrderService.AUTO_BATCH_DEFAULT_STANDARD_CYCLE_DAYS,
                ProcessingOrderService.AUTO_BATCH_DEFAULT_ASSIGNMENT_RULE,
                BigDecimal.valueOf(maxWaitHours));
    }

    /** 池夹具：确认支付态、无活跃加工单、每张单一行（物料 = 商品 × SKU）。 */
    private void stubPool(List<Order> orders) {
        stubPool(orders, "3");
    }

    /** 候选租户 = 只有本夹具租户（超集预筛的返回值；「有哪些租户」这条查询的夹具）。 */
    private void stubScanTenants() {
        when(orderMapper.selectConfirmedTenantIds()).thenReturn(List.of(TENANT));
    }

    private void stubPool(List<Order> orders, String meters) {
        when(orderMapper.selectList(any())).thenReturn(orders);
        when(processingOrderMapper.selectActiveOrderIds(eq(TENANT), anyCollection()))
                .thenReturn(List.of());
        when(orderItemMapper.selectList(any())).thenReturn(List.of(item(meters)));
    }

    private void stubGenerateOk() {
        AtomicInteger seq = new AtomicInteger();
        lenient().doAnswer(inv -> {
            calls.add(new Call(List.copyOf(inv.getArgument(0)), inv.getArgument(5),
                    inv.getArgument(4), inv.getArgument(3)));
            List<ProcessingOrderService.GenerateResult> out = new ArrayList<>();
            for (String id : inv.<List<String>>getArgument(0)) {
                out.add(ProcessingOrderService.GenerateResult.ok(id, "JG-" + seq.incrementAndGet()));
            }
            return out;
        }).when(service).generate(anyList(), anyList(), any(), any(), any(), any());
    }

    /** 记下扫描腿逐租户拿到的读数（理由文案的证据面）—— 不改被测行为，只旁听。 */
    private void captureScanOutcomes() {
        doAnswer(inv -> {
            ProcessingOrderService.AutoBatchOutcome outcome =
                    (ProcessingOrderService.AutoBatchOutcome) inv.callRealMethod();
            scanOutcomes.add(outcome);
            return outcome;
        }).when(service).autoBatchDispatchDue(TENANT);
    }

    private Order order(String id, String orderNo, int waitedHours, LocalDate requiredDeliveryDate) {
        return Order.builder().id(id).tenantId(TENANT).orderNo(orderNo).status("confirmed")
                .createdAt(OffsetDateTime.now().minusHours(waitedHours))
                .isUrgent(false).requiredDeliveryDate(requiredDeliveryDate).build();
    }

    private OrderItem item(String meters) {
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
        return OrderItem.builder().id("i-1").tenantId(TENANT).orderId("o-due")
                .productId(MATERIAL_PRODUCT).productName("布艺遮光帘A")
                .quantity(new BigDecimal(meters)).width(new BigDecimal("1.5"))
                .height(new BigDecimal("1.1")).processingInfo(info).build();
    }

    /** 抓 {@code AutoBatchDueScanService} 的日志（缺省关零噪声 / 失败留痕两条判据的证据）。 */
    private static List<String> captureLogs(Runnable action) {
        ch.qos.logback.classic.Logger logger = (ch.qos.logback.classic.Logger)
                org.slf4j.LoggerFactory.getLogger(AutoBatchDueScanService.class);
        ch.qos.logback.core.read.ListAppender<ch.qos.logback.classic.spi.ILoggingEvent> appender =
                new ch.qos.logback.core.read.ListAppender<>();
        appender.start();
        logger.addAppender(appender);
        try {
            action.run();
            return appender.list.stream()
                    .map(ch.qos.logback.classic.spi.ILoggingEvent::getFormattedMessage).toList();
        } finally {
            logger.detachAppender(appender);
        }
    }
}
