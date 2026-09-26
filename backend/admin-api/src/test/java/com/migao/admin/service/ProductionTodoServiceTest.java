// case_ids: PG-018
// ⚠️ 用例关联（如实登记）：PG-018 = 生产域后端契约族（加工单/生产读面/完工→发货贯通），
// 与本文件的被测面同族（同 `ProductionStuckPointServiceTest` 的声明口径）。
// **未固化项**：本能力（生产概览待办聚合）**没有专属行为用例** ——
// `.github/cases/**` 本轮由并行包独占（写面冲突隔离），补 `PG-059` + 跑 `render_cases.py`
// 需另开一包；已登记在 PR body 的「未固化项」一節。
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.AbstractWrapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 生产待办聚合（issue #5641，PG-059）。
 *
 * <p><b>本测试是行为断言，不是桩断言</b>：{@link ProductionStuckPointService} 与
 * {@link OrderService} 都用**真实对象**（只 mock Mapper）——
 * 「卡在哪」的判据与阈值必须真的走那个服务，发货判据必须真的走发货守卫；
 * 把它们 mock 掉等于把被测口径换成桩（本仓 §17.3 登记的「局部绿 ≠ 整体绿」）。</p>
 *
 * <p><b>红证（改前实测，逐条输出见 PR body）</b>：</p>
 * <ol>
 *   <li><b>端点不存在</b>：改前 {@code DashboardController#getPendingTasks} 只产出
 *       {@code order} / {@code after_sales} 两类，**没有任何生产类型** ⇒ 删掉本服务后
 *       {@link #stuckTodosReuseTheStuckPointReport} 等全部必红；</li>
 *   <li><b>自写第二份卡点判据</b>（本单最要防的一种）：把 {@code stuckTodo} 的
 *       {@code stalled_hours} / 阈值改成自己算（如写死 4h 常量）⇒
 *       {@link #thresholdComesFromTheStuckServiceNotASecondConstant} 必红
 *       （阈值 2.0 的服务下同一份数据「3 小时」仍被判不卡）；</li>
 *   <li><b>把「做了一半」当告警</b>：注入「{@code in_progress} 也算卡点」⇒
 *       {@link #halfDoneIsProgressNotAnAlarm} 必红（催料催到正在干的活上）；</li>
 *   <li><b>第一屏与第二屏两处计数</b>：把 {@code stats.todo_total} 改成再查一次库
 *       （而不是取同一份 list 的长度）⇒ {@link #countsComeFromTheSameSingleSource} 必红；</li>
 *   <li><b>空态渲染假数据</b>：给空态塞占位条目/占位数 ⇒ {@link #emptyStateIsHonest} 必红。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductionTodoService 生产待办聚合（issue #5641）")
class ProductionTodoServiceTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-1";
    private static final String ORDER_NO = "SO20260926001";
    private static final String PO_ID = "po-1";
    private static final String SET_ID = "set-1";
    private static final String SET_NO = "CSO260926-001-001";
    private static final String ITEM_ID = "oi-1";

    /** 挂钟固定：判据是「等了多久 > 阈值」，测试必须能确定复现（不依赖真实时间）。 */
    private static final OffsetDateTime NOW = OffsetDateTime.parse("2026-09-26T18:00:00+08:00");

    /** S3 兜底阈值（卡点服务的设计默认值）。 */
    private static final double THRESHOLD = 4.0;

    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private ProcessingOrderSetMapper orderSetMapper;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;

    /** 真实对象（只 mock Mapper）——发货判据必须走它，不许在待办服务里重写一份。 */
    @InjectMocks
    private OrderService orderService;

    private ProductionStuckPointService stuckPointService;
    private ProductionTodoService service;

    /**
     * Lambda wrapper 的列名是**惰性解析**的（`getSqlSegment()` / `getParamNameValuePairs()` 都要
     * {@code TableInfo} 缓存）—— 不预热就报「can not find lambda cache for this entity」
     * （形态同 {@code ProductionControllerTest#primeMybatisPlusLambdaCache}）。
     * 预热只是让**断言**能读 wrapper，不改被测代码的任何行为。
     */
    @org.junit.jupiter.api.BeforeAll
    static void primeMybatisPlusLambdaCache() {
        com.baomidou.mybatisplus.core.MybatisConfiguration configuration =
                new com.baomidou.mybatisplus.core.MybatisConfiguration();
        org.apache.ibatis.builder.MapperBuilderAssistant assistant =
                new org.apache.ibatis.builder.MapperBuilderAssistant(configuration, "");
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(assistant, Order.class);
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(assistant, OrderItem.class);
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(assistant, ProcessingOrder.class);
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(assistant, ProcessingOrderSet.class);
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(
                assistant, ProcessingPositionOperation.class);
    }

    @org.junit.jupiter.api.BeforeEach
    void setUp() {
        service = newService(THRESHOLD);
    }

    // ============================================================ ① 卡在哪：与既有判据同源

    @Test
    @DisplayName("🔴「卡在哪」直接消费既有判据：同刻同数据下，待办与 /stuck-points 结论逐值一致")
    void stuckTodosReuseTheStuckPointReport() {
        setUpStuckScenario(6.0, THRESHOLD);

        Map<String, Object> report = stuckPointService.report(null, TENANT, NOW);
        Map<String, Object> overview = service.overview(TENANT, NOW);

        // 前置自断言：判据服务本身确实产出了 1 条卡点（否则下面的「一致」是空断言）
        assertThat(nonNullList(report.get("stuck"))).hasSize(1);
        Map<String, Object> row = firstRow(report.get("stuck"));
        Map<String, Object> todo = todosOf(overview).get(0);

        assertThat(row.get("stalled_hours")).isEqualTo(6.0);
        assertThat(todo.get("type")).isEqualTo(ProductionTodoService.TYPE_STUCK);
        assertThat(todo.get("criterion")).isEqualTo(ProductionTodoService.CRITERION_STUCK);
        // 等待时长逐值等于判据服务算出的那个数（本类不重算）
        assertThat(evidenceOf(todo).get("stalled_hours")).isEqualTo(row.get("stalled_hours"));
        assertThat(evidenceOf(todo).get("predecessor_done_at")).isEqualTo(
                firstRowMap(row.get("predecessor")).get("done_at"));
        // 阈值与来源**透传**（不另设阈值、不吞掉来源）
        assertThat(statsOf(overview).get("stuck_threshold_hours")).isEqualTo(report.get("threshold_hours"));
        assertThat(statsOf(overview).get("threshold_source")).isEqualTo(report.get("threshold_source"));
        assertThat(evidenceOf(todo).get("threshold_source")).isEqualTo(report.get("threshold_source"));
        // 三态进度原样透传
        assertThat(statsOf(overview).get("operations")).isEqualTo(report.get("states"));
        // 文案照存活性校验结论逐字写：「上道做完后等了 N 小时没人领」
        assertThat(String.valueOf(todo.get("title")))
                .contains("上道做完后等了 6.0 小时没人领")
                .contains(ORDER_NO);
        // 可点即办：落到该订单（挂到对象上，不是死链）
        assertThat(todo.get("link")).isEqualTo("/pages/production/index/index?orderId=" + ORDER_ID);
    }

    @Test
    @DisplayName("🔴 阈值来自卡点服务（唯一一份）：同一份「等了 3 小时」在阈值 4 下不卡、阈值 2 下卡")
    void thresholdComesFromTheStuckServiceNotASecondConstant() {
        setUpStuckScenario(3.0, THRESHOLD);
        assertThat(todosOf(service.overview(TENANT, NOW))).isEmpty();

        // 同一份数据、只把「判据服务的阈值」调低 ⇒ 立刻成为待办（证明阈值不是本类写死的常量）
        ProductionTodoService lowerThreshold = newService(2.0);
        Map<String, Object> overview = lowerThreshold.overview(TENANT, NOW);
        assertThat(todosOf(overview)).hasSize(1);
        assertThat(statsOf(overview).get("stuck_threshold_hours")).isEqualTo(2.0);
    }

    @Test
    @DisplayName("🔴「做了一半」只作进度、不作告警：in_progress 不进待办，三态计数照给")
    void halfDoneIsProgressNotAnAlarm() {
        // 上道早就完成（等了 6 小时），这道报了 6/11 米 —— 有人扫过，不是「没人领」
        when(orderSetMapper.selectList(any())).thenReturn(List.of(set()));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-prev", 1, "精裁-布", "11", "11", NOW.minusHours(6)),
                op("op-half", 2, "三边", "11", "6", null)));
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(processingOrder()));

        Map<String, Object> overview = service.overview(TENANT, NOW);

        assertThat(todosOf(overview)).isEmpty();
        assertThat(statesOf(overview))
                .containsEntry(ProductionStuckPointService.STATE_IN_PROGRESS, 1)
                .containsEntry(ProductionStuckPointService.STATE_COMPLETED, 1);
    }

    @Test
    @DisplayName("卡点行挂不到订单时**不报**（说不清的就不说）：不给点不进去的假入口")
    void stuckRowWithoutResolvableOrderIsSkipped() {
        setUpStuckScenario(6.0, THRESHOLD);
        // 加工单 → 订单 关联不上（如加工单已软删）
        when(processingOrderMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> overview = service.overview(TENANT, NOW);

        assertThat(todosOf(overview)).isEmpty();
        // 但进度照给（判据本身成立，只是挂不到对象）
        assertThat(statesOf(overview)).containsEntry(ProductionStuckPointService.STATE_NOT_STARTED, 1);
    }

    // ============================================================ ② 待排产

    @Test
    @DisplayName("待排产：订单已确认 + 含加工项 + 活跃工序实例数为 0 ⇒ 一条待办（判据可追溯）")
    void toScheduleWhenConfirmedOrderHasNoInstances() {
        setUpOrderScenario(order("confirmed"), /* completedProcessingOrders */ 0L, /* instances */ 0);

        Map<String, Object> overview = service.overview(TENANT, NOW);
        Map<String, Object> todo = todosOf(overview).get(0);

        assertThat(todosOf(overview)).hasSize(1);
        assertThat(todo.get("type")).isEqualTo(ProductionTodoService.TYPE_TO_SCHEDULE);
        assertThat(todo.get("criterion")).isEqualTo(ProductionTodoService.CRITERION_TO_SCHEDULE);
        assertThat(evidenceOf(todo))
                .containsEntry("operation_instance_count", 0)
                .containsEntry("has_processing_items", true);
        assertThat(todo.get("link")).isEqualTo("/pages/production/index/index?orderId=" + ORDER_ID);
    }

    @Test
    @DisplayName("已有工序实例 ⇒ 不是待排产（不重复催已排产的单）")
    void noToScheduleWhenInstancesExist() {
        setUpOrderScenario(order("confirmed"), 0L, /* instances */ 3);
        assertThat(todosOf(service.overview(TENANT, NOW))).isEmpty();
    }

    @Test
    @DisplayName("无加工项 ⇒ 不是待排产（instantiate 会 fail-closed ⇒ 那是假待办）")
    void noToScheduleWithoutProcessingItems() {
        when(orderMapper.selectList(any())).thenReturn(List.of(order("confirmed")));
        when(orderItemMapper.selectList(any())).thenReturn(List.of(OrderItem.builder()
                .id("oi-plain").orderId(ORDER_ID).tenantId(TENANT).deleted(0)
                .processingInfo(Map.of()).build()));

        Map<String, Object> overview = service.overview(TENANT, NOW);

        assertThat(todosOf(overview)).isEmpty();
        assertThat(statsOf(overview).get("todo_total")).isEqualTo(0);
    }

    // ============================================================ ③ 待发货

    @Test
    @DisplayName("待发货：含加工项 + 加工单已完成 + 订单未发货 ⇒ 一条待办（判据 = 发货守卫）")
    void toShipWhenProcessingCompleted() {
        setUpOrderScenario(order("producing"), /* completedProcessingOrders */ 1L, /* instances */ 4);

        Map<String, Object> overview = service.overview(TENANT, NOW);
        Map<String, Object> todo = todosOf(overview).get(0);

        assertThat(todosOf(overview)).hasSize(1);
        assertThat(todo.get("type")).isEqualTo(ProductionTodoService.TYPE_TO_SHIP);
        assertThat(todo.get("criterion")).isEqualTo(ProductionTodoService.CRITERION_TO_SHIP);
        assertThat(evidenceOf(todo)).containsEntry("processing_completed", true);
        assertThat(todo.get("link")).isEqualTo("/pages/production/index/index?orderId=" + ORDER_ID);
    }

    @Test
    @DisplayName("加工单未完成 ⇒ 不是待发货（含加工项订单发不了货，卡点在加工单而不在这里）")
    void noToShipWhenProcessingUnfinished() {
        setUpOrderScenario(order("producing"), /* completedProcessingOrders */ 0L, /* instances */ 4);
        assertThat(todosOf(service.overview(TENANT, NOW))).isEmpty();
    }

    // ============================================================ ④ 空态 / 计数同源 / 判据凭据

    @Test
    @DisplayName("🔴 空态如实：没有任何待办 ⇒ todo_total=0、列表为空、三态全 0（不渲染占位数）")
    void emptyStateIsHonest() {
        Map<String, Object> overview = service.overview(TENANT, NOW);

        assertThat(overview.get("todo_total")).isEqualTo(0);
        assertThat(todosOf(overview)).isEmpty();
        assertThat(statsOf(overview).get("todo_total")).isEqualTo(0);
        assertThat(statesOf(overview))
                .containsEntry(ProductionStuckPointService.STATE_NOT_STARTED, 0)
                .containsEntry(ProductionStuckPointService.STATE_IN_PROGRESS, 0)
                .containsEntry(ProductionStuckPointService.STATE_COMPLETED, 0);
        assertThat(byTypeOf(overview)).allSatisfy((type, count) -> assertThat(count).isZero());
    }

    @Test
    @DisplayName("🔴 第一屏条数与第二屏计数同源：N == stats.todo_total == Σ by_type == 渲染条数")
    void countsComeFromTheSameSingleSource() {
        setUpStuckScenario(6.0, THRESHOLD);
        // 再加一张「待发货」的单（与卡点同刻同数据）
        when(orderMapper.selectList(any())).thenAnswer(invocation -> {
            Set<Object> values = paramsOf(invocation.getArgument(0));
            if (values.contains("producing")) {
                return List.of(order("producing"));
            }
            if (values.contains("confirmed")) {
                return List.of();
            }
            return List.of(order("producing"));
        });
        when(orderItemMapper.selectList(any())).thenReturn(List.of(processingItem()));
        when(processingOrderMapper.countCompletedByOrderId(ORDER_ID, TENANT)).thenReturn(1L);

        Map<String, Object> overview = service.overview(TENANT, NOW);

        int firstScreen = todosOf(overview).size();
        int secondScreen = (int) statsOf(overview).get("todo_total");
        int sumByType = byTypeOf(overview).values().stream().mapToInt(Integer::intValue).sum();
        assertThat(overview.get("todo_total")).isEqualTo(firstScreen);
        // 同刻同数据下：卡在哪 1 条（等 6h > 阈值 4h）+ 待发货 1 条（加工单已完成）= 2 条
        assertThat(firstScreen).isEqualTo(2).isEqualTo(secondScreen).isEqualTo(sumByType);
        // 没有重复条目（同一订单不会在两类里各出现一次）
        assertThat(todosOf(overview).stream().map(todo -> todo.get("id")).distinct().count())
                .isEqualTo(firstScreen);
    }

    @Test
    @DisplayName("🔴 每条待办都带确定性判据 id + 判据数据（无一条来自 LLM 的凭据）")
    void everyTodoCarriesADeterministicCriterion() {
        setUpOrderScenario(order("producing"), 1L, 4);

        for (Map<String, Object> todo : todosOf(service.overview(TENANT, NOW))) {
            assertThat(ProductionTodoService.CRITERIA).contains(String.valueOf(todo.get("criterion")));
            assertThat(String.valueOf(todo.get("title"))).isNotBlank();
            assertThat(String.valueOf(todo.get("reason"))).isNotBlank();
            assertThat(evidenceOf(todo)).isNotEmpty();
            assertThat(String.valueOf(todo.get("link"))).startsWith("/pages/production/index/index?orderId=");
        }
    }

    // ============================================================ ⑤ 跨租户

    @Test
    @DisplayName("跨租户 fail-closed：**每一条**查询都带 tenant_id 条件，且候选单查询真的下发本租户值")
    void everyQueryIsTenantScoped() {
        setUpStuckScenario(6.0, THRESHOLD);
        setUpOrderScenario(order("producing"), 1L, 4);

        service.overview(TENANT, NOW);

        List<Object> wrappers = new ArrayList<>();
        wrappers.addAll(captured(orderSetMapper));
        wrappers.addAll(captured(positionOperationMapper));
        wrappers.addAll(captured(processingOrderMapper));
        wrappers.addAll(captured(orderMapper));
        wrappers.addAll(captured(orderItemMapper));

        assertThat(wrappers).isNotEmpty();
        assertThat(wrappers).allSatisfy(wrapper ->
                assertThat(sqlOf(wrapper)).as("查询条件：%s", sqlOf(wrapper)).contains("tenant_id"));

        // 值级判据（形态同 CraftCalcConfigMapperTest / ProductionControllerTest 的既有先例）：
        // 候选订单查询必须把**本租户值**下发给 wrapper（少了下发 ⇒ 要么串租户、要么全表扫）
        @SuppressWarnings("unchecked")
        org.mockito.ArgumentCaptor<com.baomidou.mybatisplus.core.conditions.Wrapper<Order>> captor =
                org.mockito.ArgumentCaptor.forClass(com.baomidou.mybatisplus.core.conditions.Wrapper.class);
        org.mockito.Mockito.verify(orderMapper, org.mockito.Mockito.atLeastOnce())
                .selectList(captor.capture());
        assertThat(captor.getAllValues()).anySatisfy(wrapper ->
                assertThat(paramsOf(wrapper)).as("查询参数：%s", paramsOf(wrapper)).contains(TENANT));
    }

    // ============================================================ 夹具

    private ProductionTodoService newService(double thresholdHours) {
        stuckPointService = new ProductionStuckPointService(
                new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper,
                        orderMapper, orderItemMapper, null),
                positionOperationMapper, orderSetMapper, thresholdHours);
        return new ProductionTodoService(stuckPointService, orderService, orderMapper,
                processingOrderMapper, positionOperationMapper);
    }

    /** 卡点场景：前道已完成（{@code stalledHours} 小时前）+ 这道没开工。 */
    private void setUpStuckScenario(double stalledHours, double thresholdHours) {
        service = newService(thresholdHours);
        when(orderSetMapper.selectList(any())).thenReturn(List.of(set()));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-prev", 1, "精裁-布", "11", "11", NOW.minusMinutes((long) (stalledHours * 60))),
                op("op-next", 2, "三边", "11", "0", null)));
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(processingOrder()));
        when(orderMapper.selectList(any())).thenReturn(List.of(order("shipped")));
    }

    /** 订单场景：一张候选单（含加工项）+ 指定数量的活跃工序实例。 */
    private void setUpOrderScenario(Order order, long completedProcessingOrders, int instances) {
        service = newService(THRESHOLD);
        when(orderMapper.selectList(any())).thenReturn(List.of(order));
        when(orderItemMapper.selectList(any())).thenReturn(List.of(processingItem()));
        when(processingOrderMapper.countCompletedByOrderId(ORDER_ID, TENANT))
                .thenReturn(completedProcessingOrders);
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(processingOrder()));
        List<ProcessingPositionOperation> ops = new ArrayList<>();
        for (int i = 0; i < instances; i++) {
            ops.add(op("op-" + i, i + 1, "三边", "11", "0", null));
        }
        when(positionOperationMapper.selectList(any())).thenReturn(ops);
        assertThat(orderService.hasProcessingItems(order)).isTrue();
    }

    private static Order order(String status) {
        return Order.builder().id(ORDER_ID).tenantId(TENANT).orderNo(ORDER_NO)
                .status(status).deleted(0).build();
    }

    private static OrderItem processingItem() {
        return OrderItem.builder().id(ITEM_ID).orderId(ORDER_ID).tenantId(TENANT).deleted(0)
                .processingInfo(Map.of("processingItems", List.of(Map.of("name", "打孔"))))
                .build();
    }

    private static ProcessingOrder processingOrder() {
        return ProcessingOrder.builder().id(PO_ID).tenantId(TENANT).orderId(ORDER_ID)
                .status("completed").deleted(0).build();
    }

    private static ProcessingOrderSet set() {
        return ProcessingOrderSet.builder().id(SET_ID).tenantId(TENANT).processingOrderId(PO_ID)
                .setNo(SET_NO).setIndex(1).deleted(0).build();
    }

    private static ProcessingPositionOperation op(String id, Integer seq, String operationName,
                                                 String qty, String doneQty, OffsetDateTime doneAt) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID).setId(SET_ID).setNo(SET_NO)
                .orderItemId(ITEM_ID).positionKind("布帘").positionName("布艺遮光帘A")
                .seq(seq).operationName(operationName).unit("米")
                .qty(new BigDecimal(qty))
                .doneQty(doneQty == null ? null : new BigDecimal(doneQty))
                .doneAt(doneAt).deleted(0).build();
    }

    // ============================================================ 断言工具

    private static List<Map<String, Object>> todosOf(Map<String, Object> overview) {
        return nonNullList(overview.get("todos"));
    }

    private static Map<String, Object> statsOf(Map<String, Object> overview) {
        return mapOf(overview.get("stats"));
    }

    private static Map<String, Object> statesOf(Map<String, Object> overview) {
        return mapOf(statsOf(overview).get("operations"));
    }

    private static Map<String, Integer> byTypeOf(Map<String, Object> overview) {
        Map<String, Integer> counts = new java.util.LinkedHashMap<>();
        mapOf(statsOf(overview).get("by_type")).forEach((key, value) ->
                counts.put(key, ((Number) value).intValue()));
        return counts;
    }

    private static Map<String, Object> evidenceOf(Map<String, Object> todo) {
        return mapOf(todo.get("evidence"));
    }

    private static Map<String, Object> firstRow(Object rows) {
        return nonNullList(rows).get(0);
    }

    private static Map<String, Object> firstRowMap(Object row) {
        return mapOf(row);
    }

    private static Map<String, Object> mapOf(Object value) {
        if (value instanceof Map<?, ?> map) {
            Map<String, Object> copy = new java.util.LinkedHashMap<>();
            map.forEach((key, item) -> copy.put(String.valueOf(key), item));
            return copy;
        }
        return Map.of();
    }

    private static List<Map<String, Object>> nonNullList(Object value) {
        if (!(value instanceof List<?> list)) {
            return List.of();
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Object item : list) {
            rows.add(mapOf(item));
        }
        return rows;
    }

    /** MyBatis-Plus wrapper 的查询参数值集（`getParamNameValuePairs` 在 `AbstractWrapper` 上，按实现类读）。 */
    private static Set<Object> paramsOf(Object wrapper) {
        if (wrapper instanceof AbstractWrapper<?, ?, ?> abstractWrapper) {
            return new LinkedHashSet<>(abstractWrapper.getParamNameValuePairs().values());
        }
        return Set.of();
    }

    /** wrapper 的 SQL 条件片段（形态判据：`tenant_id` 条件必须在里面）。 */
    private static String sqlOf(Object wrapper) {
        return wrapper instanceof AbstractWrapper<?, ?, ?> abstractWrapper
                ? String.valueOf(abstractWrapper.getSqlSegment()) : "";
    }

    /**
     * 已捕获的 wrapper 清单。
     *
     * <p>用 Mockito 的 {@code mockingDetails} 取全部调用参数（不逐个测试写捕获器 ⇒ 新增查询自动进面，
     * 不会因为「忘了加捕获」而让跨租户判据变成空断言）。</p>
     */
    private static List<Object> captured(Object mock) {
        List<Object> wrappers = new ArrayList<>();
        for (var invocation : org.mockito.Mockito.mockingDetails(mock).getInvocations()) {
            for (Object argument : invocation.getArguments()) {
                if (argument instanceof AbstractWrapper<?, ?, ?> wrapper) {
                    wrappers.add(wrapper);
                }
            }
        }
        wrappers.removeIf(Objects::isNull);
        return wrappers;
    }
}
