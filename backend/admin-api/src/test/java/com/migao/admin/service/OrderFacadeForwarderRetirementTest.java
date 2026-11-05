// case_ids: MC-203, MC-205, MC-211, MC-233, MC-238
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 门面转发**退休**判据（issue #8681；第一批 + 第二批 + 第四批 + 第五批）：调用方迁到四个新服务之后，被删掉的转发方法
 * 不许以任何形式回来，而且**调用方不许再绕门面**。
 *
 * <p><b>第一批</b>（PR #8682）：{@code existsForCurrentTenant} / {@code resolveOrderId} /
 * {@code isProcessingReadyForShip} / {@code resolveShipperName}；<b>第二批</b>：
 * {@code getMyOrderPage}（Agent 控制器 C 端「我的订单」端点改直连 {@link OrderQueryService}）；
 * <b>第四批</b>：{@code getOrderPage} / {@code getOrderById}（订单控制器的列表与两处详情、
 * 建单服务的回读全部直连实现点）；<b>第五批</b>：{@code createOrder}（订单控制器直连
 * {@link OrderCreationService}，第三参仍是门面实例）+ 统计与跟进读取族（{@code getOrderStatistics} /
 * {@code getFollowStatusStats} / {@code getFollowStatus} 直连 {@link OrderStatsService}）；
 * <b>第六批</b>：生命周期族 {@code updateOrderStatus} / {@code confirmPayment} / {@code cancelOrder} /
 * {@code refundOrder} / {@code shipWithLogistics}（两个重载）/ {@code revertProducingToConfirmed}
 * 直连 {@link OrderLifecycleService}（订单 / 生产控制器与加工单服务；门面共 7 个声明退休）；
 * <b>第七批</b>：实体实现 {@code deleteOrder} / {@code addRemark} / {@code bindOrdersToUser} /
 * {@code updateFollowStatus} / {@code getFollowStatus} / {@code updateUrgency} /
 * {@code updatePendingOrderContent} 直连 {@link OrderEntityWriteService}（订单控制器 + 小程序手机号绑定服务；
 * 门面共 7 个声明退休，且不再留这族的私有死委托）；
 * <b>第八批</b>：Agent BFF 收口 —— {@code createOrderForAgent} 直连 {@link OrderCreationService}、
 * {@code updateOrderForAgent} 直连 {@link OrderAgentFacade}（实现体整体搬过去）、{@code restoreStockForReturn}
 * 由 {@code AfterSalesTicketService} 直连 {@link OrderStockService}；同批再清 1 个失去调用点的私有死委托
 * （{@code resolveOrderIdToUuid}）。至此门面<b>不再声明任何转发</b>。</p>
 *
 * <p><b>为什么需要它（这条判据补的是哪一半）</b>：删掉门面转发之后，原来「门面必须把这一族转出去」的
 * 接线判据就**没有对象**了 ⇒ 若只是把它们删掉，这个方向就变成**无人看管**：任何人把转发加回来、
 * 或让某个调用方重新走门面，都不会有东西变红。本类就是补上这一半。</p>
 *
 * <p><b>它判三件事（都在载体集合上判，不在某个单点上判）</b>：</p>
 * <ol>
 *   <li><b>退休面</b>：门面里不再有这 11 个方法的声明；{@code src/main} 里**没有任何**调用是经门面变量
 *       （{@code orderService.<方法>(}）走的；</li>
 *   <li><b>接线面</b>：实现点仍声明它们（防止「两边都没了」的恒绿），且**具名的消费方**逐字调用实现点
 *       —— 消费方或调用形态被改回去 ⇒ 当场红并具名；</li>
 *   <li><b>驱动面</b>：{@code src/test} 全树不许再经门面驱动这批查询入口（第四批新加的一格 ——
 *       {@code OrderServiceTest} 那一格只覆盖一个文件）。</li>
 * </ol>
 *
 * <p><b>红证方向（判别力自证内建，见末例）</b>：把任一转发方法塞回门面源 ⇒「退休面」判假；
 * 把任一消费方的调用改回门面变量 ⇒「接线面」判假。两个谓词都在内存语料上各注入一次，
 * 保证它们不是恒真/恒假。</p>
 *
 * <p><b>复算</b>：{@code cd backend/admin-api && ./mvnw -Dtest=OrderFacadeForwarderRetirementTest test}。</p>
 */
@DisplayName("#8681 P2-1e 门面转发退休：转发不许回来、调用方不许再绕门面")
class OrderFacadeForwarderRetirementTest {

    private static final Path MAIN = Path.of("src", "main", "java", "com", "migao", "admin");
    private static final Path ORDER_SERVICE = MAIN.resolve("service").resolve("OrderService.java");
    private static final Path QUERY_SERVICE = MAIN.resolve("service").resolve("OrderQueryService.java");
    private static final Path LIFECYCLE_SERVICE = MAIN.resolve("service").resolve("OrderLifecycleService.java");
    private static final Path CREATION_SERVICE = MAIN.resolve("service").resolve("OrderCreationService.java");
    private static final Path STATS_SERVICE = MAIN.resolve("service").resolve("OrderStatsService.java");
    /** 第七批（issue #8681，P2-1e 第七批）：订单**实体写面**的唯一实现点。 */
    private static final Path WRITE_SERVICE = MAIN.resolve("service").resolve("OrderEntityWriteService.java");
    /** 第八批（issue #8681，P2-1e 第八批）：Agent BFF 编排（{@code updateOrderForAgent}）的唯一实现点。 */
    private static final Path AGENT_FACADE = MAIN.resolve("service").resolve("OrderAgentFacade.java");
    /** 第八批：库存与销量族的唯一实现点（{@code restoreStockForReturn} 的实现一直在这一侧）。 */
    private static final Path STOCK_SERVICE = MAIN.resolve("service").resolve("OrderStockService.java");

    /**
     * 本批退休的转发：方法名 → 声明签名（逐字）+ 实现点所在文件 + 消费方清单（目录 + 文件 + 必须出现的调用串）。
     *
     * <p>消费方清单是**具名白名单**而不是「扫到就算」：新增调用方时它会提醒你把这里补上（漏登记 = 红），
     * 这也是「一处行为改动背后有多个登记面」里本单该管的那一格。一个方法可以有**多个**消费方
     * （第四批的 {@code getOrderById} 就是控制器两处 + 建单服务回读一处）。</p>
     */
    private static final Map<String, Retired> RETIRED = new LinkedHashMap<>();

    static {
        RETIRED.put("existsForCurrentTenant", new Retired(
                "public boolean existsForCurrentTenant(String id)",
                QUERY_SERVICE,
                List.of(new Consumer("security", "TenantResourceOwnership.java",
                        "orderQueryService.existsForCurrentTenant("))));
        RETIRED.put("resolveOrderId", new Retired(
                "public AgentOrderResolveResponse resolveOrderId(String keyword, Long tenantId)",
                QUERY_SERVICE,
                List.of(new Consumer("controller/agent", "AgentOrderController.java",
                        "orderQueryService.resolveOrderId("))));
        RETIRED.put("isProcessingReadyForShip", new Retired(
                "public boolean isProcessingReadyForShip(Order order)",
                LIFECYCLE_SERVICE,
                List.of(new Consumer("service", "ProductionTodoService.java",
                        "orderLifecycleService.isProcessingReadyForShip("))));
        RETIRED.put("resolveShipperName", new Retired(
                "public String resolveShipperName(String provided)",
                LIFECYCLE_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                        "orderLifecycleService.resolveShipperName("))));
        // 第二批（issue #8681，P2-1e 第二批）：C 端「我的订单」端点改直连实现点。
        // 声明锚点取「返回类型 + 方法名 + 左括号」而不是整行：门面里这个签名是**跨行**的，
        // 整行锚点会被换行/缩进漂移误伤；而调用形态（`orderService.getMyOrderPage(`）不含返回类型 ⇒
        // 不会被调用串误判成声明。
        RETIRED.put("getMyOrderPage", new Retired(
                "PageResponse<OrderListResponse> getMyOrderPage(",
                QUERY_SERVICE,
                List.of(new Consumer("controller/agent", "AgentOrderController.java",
                        "orderQueryService.getMyOrderPage("))));
        // 第四批（issue #8681，P2-1e 第四批）：查询族收口 —— 列表与两处详情全部直连实现点。
        RETIRED.put("getOrderPage", new Retired(
                "PageResponse<OrderListResponse> getOrderPage(",
                QUERY_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                        "orderQueryService.getOrderPage("))));
        // 两个重载共用一个声明锚点（「返回类型 + 方法名 + 左括号」）：门面里只要有**任一**重载回来就会命中。
        RETIRED.put("getOrderById", new Retired(
                "OrderDetailResponse getOrderById(",
                QUERY_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                                "orderQueryService.getOrderById("),
                        new Consumer("service", "OrderCreationService.java",
                                "orderQueryService.getOrderById("))));
        // 第五批（issue #8681，P2-1e 第五批）：建单族 —— 订单控制器直连实现点，第三参仍是门面实例
        // （建单与改单共用的明细装配 / 取价 / 库存前置留在门面，见 OrderService 类注释）。
        // 声明锚点同样是「返回类型 + 方法名 + 左括号」：不会与调用串 `orderCreationService.createOrder(` 混淆，
        // 也不会误命中门面里仍保留的 `createOrderForAgent(`（方法名不同）。
        RETIRED.put("createOrder", new Retired(
                "OrderDetailResponse createOrder(",
                CREATION_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                        "orderCreationService.createOrder("))));
        // 第五批（同批第二档）：统计与跟进**读取**族 —— 三个入口都只读 OrderMapper、且并进
        // {@link OrderQueryService}（当批现取 755 行）会越过 800 行阈值 ⇒ 单开 OrderStatsService。
        // 同族的**写面** updateFollowStatus 仍留门面（下一批「实体实现搬家」），故**不在**本清单里。
        RETIRED.put("getOrderStatistics", new Retired(
                "OrderStatisticsResponse getOrderStatistics(",
                STATS_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                        "orderStatsService.getOrderStatistics("))));
        RETIRED.put("getFollowStatusStats", new Retired(
                "FollowStatusStatsResponse getFollowStatusStats(",
                STATS_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                        "orderStatsService.getFollowStatusStats("))));
        // 第七批（issue #8681，P2-1e 第七批）：读写**同址**收口 —— 写面 updateFollowStatus 搬进
        // {@link OrderEntityWriteService} 时，读面 getFollowStatus 也同批从 {@link OrderStatsService} 并回
        // （第五批登记的返工点就此销账）。本条的实现点载体因此从 STATS_SERVICE 改为 WRITE_SERVICE。
        RETIRED.put("getFollowStatus", new Retired(
                "FollowStatusResponse getFollowStatus(",
                WRITE_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                        "orderEntityWriteService.getFollowStatus("))));
        // 第六批（issue #8681，P2-1e 第六批）：生命周期族收口 —— 订单 / 生产控制器与加工单服务直连
        // {@link OrderLifecycleService}（加工单服务是**冻结面**、一行都不许涨 ⇒ 它经门面的包内访问器取
        // **同一份**实现点，调用形态仍是直连实现点、不经任何退休前的转发）。声明锚点取「返回类型（或 void）+ 方法名 + 左括号」：
        // 实现点的 {@code updateOrderStatus} / {@code cancelOrder} 比门面多一个门面实参，
        // 整行锚点在两侧不是同一串；而调用形态（`orderLifecycleService.xxx(`）不含返回类型 ⇒ 不会被误判成声明。
        RETIRED.put("updateOrderStatus", new Retired(
                "void updateOrderStatus(",
                LIFECYCLE_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                                "orderLifecycleService.updateOrderStatus("),
                        new Consumer("service", "ProcessingOrderService.java",
                                "lifecycleService().updateOrderStatus("))));
        RETIRED.put("confirmPayment", new Retired(
                "void confirmPayment(",
                LIFECYCLE_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                        "orderLifecycleService.confirmPayment("))));
        RETIRED.put("cancelOrder", new Retired(
                "void cancelOrder(",
                LIFECYCLE_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                        "orderLifecycleService.cancelOrder("))));
        RETIRED.put("refundOrder", new Retired(
                "void refundOrder(",
                LIFECYCLE_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                        "orderLifecycleService.refundOrder("))));
        // 两个重载共用一个声明锚点：门面里只要**任一**重载回来就会命中。
        RETIRED.put("shipWithLogistics", new Retired(
                "OrderShipmentOutcome shipWithLogistics(",
                LIFECYCLE_SERVICE,
                List.of(new Consumer("controller", "ProductionController.java",
                        "orderLifecycleService.shipWithLogistics("))));
        RETIRED.put("revertProducingToConfirmed", new Retired(
                "void revertProducingToConfirmed(",
                LIFECYCLE_SERVICE,
                List.of(new Consumer("service", "ProcessingOrderService.java",
                        "lifecycleService().revertProducingToConfirmed("))));
        // 第七批（issue #8681，P2-1e 第七批）：**实体实现**搬家 —— 这批不是转发，是门面里最后一批
        // 「真正干活」的订单实体写法。实现体逐字节搬进 {@link OrderEntityWriteService} 之后，门面
        // 一处声明都不许留（连私有死委托都不留），消费方一律直连实现点。
        // 内容编辑的第三参仍是**门面实例**：建单与改单共用的明细装配 / 取价 / 总额 / 库存前置的唯一实现点
        // 留 {@code OrderService}（与第五批 createOrder 同一条口径，不重搭第二份）。
        RETIRED.put("deleteOrder", new Retired(
                "void deleteOrder(",
                WRITE_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                        "orderEntityWriteService.deleteOrder("))));
        RETIRED.put("addRemark", new Retired(
                "void addRemark(",
                WRITE_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                        "orderEntityWriteService.addRemark("))));
        RETIRED.put("bindOrdersToUser", new Retired(
                "int bindOrdersToUser(",
                WRITE_SERVICE,
                List.of(new Consumer("service", "MiniPhoneBindService.java",
                        "orderEntityWriteService.bindOrdersToUser("))));
        RETIRED.put("updateFollowStatus", new Retired(
                "void updateFollowStatus(",
                WRITE_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                        "orderEntityWriteService.updateFollowStatus("))));
        RETIRED.put("updateUrgency", new Retired(
                "void updateUrgency(",
                WRITE_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                        "orderEntityWriteService.updateUrgency("))));
        RETIRED.put("updatePendingOrderContent", new Retired(
                "OrderDetailResponse updatePendingOrderContent(",
                WRITE_SERVICE,
                List.of(new Consumer("controller", "OrderController.java",
                        "orderEntityWriteService.updatePendingOrderContent("))));
        // 第八批（issue #8681，P2-1e 第八批）：Agent BFF 收口 —— 两个转发一起退休，形态各不相同：
        // ① createOrderForAgent 的实现体本来就在 OrderCreationService（本批只删门面转发，调用方直连实现点，
        //    与第五批 createOrder 同一条口径）；② updateOrderForAgent 是**门面里最后一块真正干活**的编排，
        //    实现体整体搬进 OrderAgentFacade（事务注解逐字跟随）；③ restoreStockForReturn 的实现早已在
        //    OrderStockService，门面那一个方法只转发 ⇒ 只欠调用方迁移。三者的消费方都是具名的。
        RETIRED.put("createOrderForAgent", new Retired(
                "OrderDetailResponse createOrderForAgent(",
                CREATION_SERVICE,
                List.of(new Consumer("controller/agent", "AgentOrderController.java",
                        "orderCreationService.createOrderForAgent("))));
        RETIRED.put("updateOrderForAgent", new Retired(
                "Object updateOrderForAgent(",
                AGENT_FACADE,
                List.of(new Consumer("controller/agent", "AgentOrderController.java",
                        "orderAgentFacade.updateOrderForAgent("))));
        // 声明锚点取「void + 方法名 + 左括号」：实现点（OrderStockService）是包内可见、门面那一侧是 public，
        // 两侧的整行不是同一串；调用形态 `orderStockService.xxx(` 不含返回类型 ⇒ 不会被误判成声明。
        RETIRED.put("restoreStockForReturn", new Retired(
                "void restoreStockForReturn(",
                STOCK_SERVICE,
                List.of(new Consumer("service", "AfterSalesTicketService.java",
                        "orderStockService.restoreStockForReturn("))));
    }

    /**
     * 生命周期族搬走后**失去调用方**的私有死委托（issue #8681，P2-1e 顺带清理）：
     * 它们只转发、且门面里已无任何调用点 ⇒ 留着就是「看起来还在用」的假接线。
     */
    private static final List<String> DEAD_PRIVATE_FORWARDERS = List.of(
            "private void validateStockSufficient(Order order)",
            "private BigDecimal effectiveActualAmount(Order order)",
            "private void recordFinanceTransaction(Order order, String type, String remark)",
            "private void recordFinanceTransaction(Order order, BigDecimal amount, String type, String remark)",
            "private void deductStockAndIncreaseSales(String orderId)",
            "private void restoreStockAndDecreaseSales(String orderId)",
            // 第八批（issue #8681，P2-1e）：updateOrderForAgent 搬到 OrderAgentFacade 后，门面里这个私有解析委托
            // 失去唯一调用点（解析口径单点在 OrderQueryService，新实现点直连它）⇒ 一并退休，不许长回来。
            "private String resolveOrderIdToUuid(String raw, Long tenantId)");

    /**
     * 迁走**驱动方**的门面入口（{@code src/test} 全树口径）。
     *
     * <p>第四批收了三个查询入口（{@code getOrderPage} / {@code getOrderById} 是当批，{@code getMyOrderPage} 是第二批）；
     * <b>第五批加 {@code createOrder}</b>（驱动点散在 6 个测试文件：两个控制器测试 + 集成测试 + Agent BFF 测试 +
     * 无 SKU 标识判据 + 小数数量判据，全部改为直驱实现点）。生命周期族**不在此列** —— 它们仍有接线 / 快照判据
     * <b>故意</b>经门面驱动，要等下一批把那几族一并收口时才提上来（否则本判据会误伤那些「专门看门面有没有转出去」的判据）。</p>
     */
    private static final List<String> TEST_DRIVER_RETIRED = List.of(
            "getOrderPage", "getMyOrderPage", "getOrderById", "createOrder",
            "getOrderStatistics", "getFollowStatusStats", "getFollowStatus",
            // 第六批（issue #8681，P2-1e 第六批）：生命周期族。三个接线 / 快照判据已改**直测实现点**
            // （{@code ReflectionTestUtils.invokeMethod(orderService, "lifecycleService")} 那一份），
            // 其余驱动点一并迁走 ⇒ 门面同名入口在 src/test 全树零驱动。
            "updateOrderStatus", "confirmPayment", "cancelOrder", "refundOrder",
            "shipWithLogistics", "revertProducingToConfirmed",
            // 第七批（issue #8681，P2-1e 第七批）：实体写面。驱动点从门面迁到实现点
            // （{@code ReflectionTestUtils.invokeMethod(orderService, "entityWriteService")} 那一份），
            // 断言逐字未改。
            "deleteOrder", "addRemark", "bindOrdersToUser", "updateFollowStatus",
            "updateUrgency", "updatePendingOrderContent",
            // 第八批（issue #8681，P2-1e 第八批）：Agent BFF 两个入口 + 售后回补。
            // 驱动对象 = 实现点自己（OrderCreationService / OrderAgentFacade / OrderStockService），
            // 建单与改单的第三参仍是门面实例 —— 所以「直驱实现点」的调用串里会**带** orderService，但不含
            // `orderService.<方法名>(` 这个形态，两种写法（直接调用 / verify）都不会命中。
            "createOrderForAgent", "updateOrderForAgent", "restoreStockForReturn");

    private record Consumer(String dir, String file, String call) {
    }

    private record Retired(String declaration, Path implFile, List<Consumer> consumers) {
    }

    // ──────────────────────────────────────────── 判据 0：扫描面非空（fail-closed）

    @Test
    @DisplayName("扫描面自证：门面 / 三个实现点 / 全部具名消费方文件都必须真实存在（缺一个 ⇒ 红，不是跳过）")
    void scanSurfaceExists() {
        for (Path path : List.of(ORDER_SERVICE, QUERY_SERVICE, LIFECYCLE_SERVICE, CREATION_SERVICE, STATS_SERVICE,
                WRITE_SERVICE, AGENT_FACADE, STOCK_SERVICE)) {
            assertThat(Files.exists(path)).as("判据的载体必须真实存在（路径漂移不得静默跳过）: %s", path).isTrue();
        }
        for (Retired retired : RETIRED.values()) {
            assertThat(Files.exists(retired.implFile()))
                    .as("实现点载体必须真实存在: %s", retired.implFile()).isTrue();
            for (Consumer consumer : retired.consumers()) {
                Path path = MAIN.resolve(consumer.dir()).resolve(consumer.file());
                assertThat(Files.exists(path)).as("具名消费方必须真实存在: %s", path).isTrue();
            }
        }
        assertThat(RETIRED).as("退休清单被清空 ⇒ 本判据退化成空断言").hasSize(26);
        assertThat(DEAD_PRIVATE_FORWARDERS).as("死委托清单被清空 ⇒ 本判据退化成空断言").hasSize(7);
        assertThat(TEST_DRIVER_RETIRED).as("驱动面清单被清空 ⇒ 本判据退化成空断言").hasSize(22);
    }

    // ──────────────────────────────────────────── 判据 1：退休面（门面 + 全 main）

    @Test
    @DisplayName("门面里不许再有这 26 个转发方法的声明（加回来 ⇒ 具名红）")
    void facadeNoLongerDeclaresTheRetiredForwarders() throws IOException {
        String facade = Files.readString(ORDER_SERVICE, StandardCharsets.UTF_8);

        List<String> back = RETIRED.entrySet().stream()
                .filter(e -> declaresMethod(facade, e.getValue().declaration()))
                .map(Map.Entry::getKey)
                .sorted()
                .toList();

        assertThat(back).as("这些转发方法又长回门面里了（调用方应直接依赖实现点）: %s", back).isEmpty();
    }

    @Test
    @DisplayName("私有死委托不许长回来（它们已无调用点，留着 = 假接线）")
    void deadPrivateForwardersStayRetired() throws IOException {
        String facade = Files.readString(ORDER_SERVICE, StandardCharsets.UTF_8);

        List<String> back = DEAD_PRIVATE_FORWARDERS.stream()
                .filter(decl -> facade.contains(decl))
                .toList();

        assertThat(back).as("这些私有死委托又出现了（门面里没有调用方，只转发）: %s", back).isEmpty();
    }

    @Test
    @DisplayName("全 main 源码里零处「经门面变量调用这 26 个方法」（谁改回门面 ⇒ 具名红）")
    void nobodyCallsTheRetiredMethodsThroughTheFacade() throws IOException {
        Map<String, List<String>> hits = new LinkedHashMap<>();
        for (Map.Entry<String, Retired> entry : RETIRED.entrySet()) {
            String needle = "orderService." + entry.getKey() + "(";
            hits.put(needle, filesContaining(needle));
        }

        List<String> violations = hits.entrySet().stream()
                .filter(e -> !e.getValue().isEmpty())
                .map(e -> e.getKey() + " @ " + e.getValue())
                .toList();

        assertThat(violations).as("这些调用又绕回门面了（应直接调用实现点）: %s", violations).isEmpty();
    }

    // ──────────────────────────────────────────── 判据 2：接线面（实现点 + 具名消费方）

    @Test
    @DisplayName("实现点仍声明这 26 个方法（两边都没了 ⇒ 本判据会恒绿，所以先钉住这一侧）")
    void implementationSitesStillDeclareThem() {
        List<String> missing = new ArrayList<>();
        for (Map.Entry<String, Retired> entry : RETIRED.entrySet()) {
            Path impl = entry.getValue().implFile();
            if (!declaresMethod(readQuietly(impl), entry.getValue().declaration())) {
                missing.add(entry.getKey() + " @ " + impl.getFileName());
            }
        }

        assertThat(missing).as("实测点不见了 ⇒ 退休面判定会空跑（两边都没了这个方法）: %s", missing).isEmpty();
    }

    @Test
    @DisplayName("全部具名消费方逐字调用实现点（绕门面 / 改调用形态 ⇒ 具名红）")
    void namedConsumersCallTheImplementationSites() {
        List<String> violations = new ArrayList<>();
        for (Map.Entry<String, Retired> entry : RETIRED.entrySet()) {
            for (Consumer consumer : entry.getValue().consumers()) {
                Path path = MAIN.resolve(consumer.dir()).resolve(consumer.file());
                if (!readQuietly(path).contains(consumer.call())) {
                    violations.add(consumer.file() + " 里找不到 `" + consumer.call() + "`");
                }
            }
        }

        assertThat(violations).as("这些消费方没有直连实现点（被改回门面 / 方法被改名）: %s", violations).isEmpty();
    }

    // ──────────────────────────────────────────── 判据 4：驱动对象迁到实现点（第二批）

    /**
     * 第二批把 {@code OrderServiceTest} 的**驱动对象**迁到实现点的那批入口（issue #8681，P2-1e 第二批）。
     *
     * <p>只列**本批迁走**的：删单 / 备注 / 手机号回填 / 跟进 / 内容改单仍驱动门面 —— 它们是门面里的
     * **实体实现**（不是转发），删它们要先搬实现，属下一批 ⇒ 不在本清单里，也不算违规。</p>
     */
    private static final List<String> DRIVER_MIGRATED = List.of(
            "getOrderPage", "getMyOrderPage", "getOrderById", "createOrder", "updateOrderStatus",
            "cancelOrder", "refundOrder", "confirmPayment", "shipWithLogistics", "revertProducingToConfirmed",
            // 第七批：OrderServiceTest 里这批入口的 15 个驱动点（删单 5 / 备注 4 / 手机号回填 3 / 跟进 2 / 内容改单 1）
            "deleteOrder", "addRemark", "bindOrdersToUser", "updateFollowStatus", "updatePendingOrderContent");

    @Test
    @DisplayName("OrderServiceTest 的驱动对象是实现点（改回门面 ⇒ 具名红：本批的解锁不许静默失效）")
    void orderServiceTestDrivesImplementationSites() throws IOException {
        Path testFile = Path.of("src", "test", "java", "com", "migao", "admin", "service", "OrderServiceTest.java");
        assertThat(Files.exists(testFile))
                .as("判据载体必须真实存在（路径漂移不得静默跳过）: %s", testFile).isTrue();
        assertThat(DRIVER_MIGRATED).as("清单被清空 ⇒ 本判据退化成空断言").hasSize(15);

        String source = stripComments(Files.readString(testFile, StandardCharsets.UTF_8));
        List<String> back = DRIVER_MIGRATED.stream()
                .filter(m -> source.contains("orderService." + m + "("))
                .sorted()
                .toList();

        assertThat(back)
                .as("这些驱动调用又回到门面了（本批已改为直驱实现点；改回去 ⇒ 门面入口重新被 152 条钉住、删不掉）: %s", back)
                .isEmpty();

        // 判别力自证：同一谓词在「门面驱动」的内存语料上必须判真（否则上面那条是恒真的空断言）
        String facadeDriven = "orderService.getOrderById(\"o-1\");";
        String implementationDriven = "orderQueryService.getOrderById(\"o-1\");";
        assertThat(DRIVER_MIGRATED.stream().anyMatch(m -> facadeDriven.contains("orderService." + m + "(")))
                .as("门面驱动的形态必须被判真").isTrue();
        assertThat(DRIVER_MIGRATED.stream().anyMatch(m -> implementationDriven.contains("orderService." + m + "(")))
                .as("直驱实现点的形态必须被判假").isFalse();
    }

    // ──────────────────────────────────────────── 判据 5：驱动面搬到全 test 树（第四批）

    /**
     * 第四批的驱动面判据：**不只** {@code OrderServiceTest}（那是第二批的射程），而是 {@code src/test}
     * 全树 —— 查询入口的驱动方散在 8 个测试文件里（控制器 / 集成 / 时间窗 / 租户隔离 / 精度 / 分页闸门 /
     * 打印状态 / 查询服务自身），只钉一个文件等于只钉住 1/8。
     *
     * <p>形态判据含两种「经门面」的写法：{@code orderService.<m>(} 与 {@code verify(orderService).<m>(}
     * —— 后者是**验证**一个门面交互，同样是「让门面入口继续被钉住」的原因（改回门面才会这么写）。</p>
     */
    @Test
    @DisplayName("src/test 全树零处「经门面驱动这批已退休入口」（改回门面 ⇒ 具名红）")
    void testTreeDoesNotDriveTheRetiredQueryEntriesThroughTheFacade() throws IOException {
        Path root = Path.of("src", "test", "java");
        assertThat(Files.isDirectory(root))
                .as("扫描根必须存在（路径漂移不得静默跳过）: %s", root).isTrue();
        Path self = Path.of("src", "test", "java", "com", "migao", "admin", "service",
                "OrderFacadeForwarderRetirementTest.java");

        List<String> offenders = new ArrayList<>();
        int scanned = 0;
        try (Stream<Path> stream = Files.walk(root)) {
            for (Path path : stream.filter(p -> p.toString().endsWith(".java")).toList()) {
                if (path.equals(self)) {
                    // 本文件含「门面驱动的内存语料」（判别力自证），不是真驱动方 ⇒ 唯一豁免且写在判据里
                    continue;
                }
                scanned++;
                String source = stripComments(Files.readString(path, StandardCharsets.UTF_8));
                for (String method : TEST_DRIVER_RETIRED) {
                    if (source.contains("orderService." + method + "(")
                            || source.contains("orderService)." + method + "(")) {
                        offenders.add(method + " @ " + root.relativize(path).toString().replace('\\', '/'));
                    }
                }
            }
        }

        assertThat(scanned)
                .as("扫描面必须够大（只扫到零星文件 ⇒ 判据空跑）: %s", scanned).isGreaterThan(500);
        assertThat(offenders)
                .as("这些测试又在经门面驱动已退休的查询入口（应直驱实现点）: %s", offenders).isEmpty();
    }

    // ──────────────────────────────────────────── 判据 3：判别力自证（内存注入）

    @Test
    @DisplayName("🔴 判别力自证：内存里把转发塞回门面 / 把消费方改回门面 ⇒ 两个谓词各自判假")
    void guardHasDiscriminatingPower() {
        String facade = "public class OrderService {\n    public String resolveShipperName(String provided) { }\n}";
        assertThat(declaresMethod(facade, RETIRED.get("resolveShipperName").declaration()))
                .as("把转发塞回门面源 ⇒ 「已退休」必须判假（否则判据是恒真的空断言）").isTrue();
        assertThat(declaresMethod("public class OrderService {\n}", RETIRED.get("resolveShipperName").declaration()))
                .as("真语料形态（没有该方法）⇒ 必须判假").isFalse();

        // 第二批新增的那条是**跨行签名** ⇒ 锚点必须也能命中跨行形态（否则「加回来」不会被判红）
        String multilineFacade = "public class OrderService {\n"
                + "    public PageResponse<OrderListResponse> getMyOrderPage(long page, long size, String status,\n"
                + "                                                          Long tenantId, String userId, String userPhone) { }\n}";
        assertThat(declaresMethod(multilineFacade, RETIRED.get("getMyOrderPage").declaration()))
                .as("跨行声明的形态也必须判真（第二批的锚点是「返回类型 + 方法名 + 左括号」）").isTrue();

        // 第四批的两条同样是跨行签名锚点：两个重载里**任一**回来都必须被判真
        String scopedOverload = "public class OrderService {\n"
                + "    public OrderDetailResponse getOrderById(String id, String dataScopeOwnerId) { }\n}";
        assertThat(declaresMethod(scopedOverload, RETIRED.get("getOrderById").declaration()))
                .as("带范围的重载回来也必须被判真（锚点不区分重载）").isTrue();
        String pageForward = "public class OrderService {\n"
                + "    public PageResponse<OrderListResponse> getOrderPage(long page, long size) { }\n}";
        assertThat(declaresMethod(pageForward, RETIRED.get("getOrderPage").declaration()))
                .as("列表转发回来也必须被判真").isTrue();

        // 第五批：建单转发回来必须判真；门面里仍保留的 createOrderForAgent **不算**回来（方法名不同）
        String createForward = "public class OrderService {\n"
                + "    public OrderDetailResponse createOrder(OrderCreateRequest request, Long tenantId) { }\n}";
        assertThat(declaresMethod(createForward, RETIRED.get("createOrder").declaration()))
                .as("建单转发回来必须被判真（否则删掉之后就没人看管了）").isTrue();
        String agentOnly = "public class OrderService {\n"
                + "    public OrderDetailResponse createOrderForAgent(AgentOrderCreateRequest r, Long t) { }\n}";
        assertThat(declaresMethod(agentOnly, RETIRED.get("createOrder").declaration()))
                .as("仍保留的 createOrderForAgent 不得被判成「扁平化后的 createOrder 回来了」").isFalse();

        // 反形态：方法名出现在**注释**里不算声明（否则别人写一句说明就把判据喂红了）
        String commented = "/** 见 OrderService.resolveShipperName 的沿革 */\npublic class OrderService {\n}";
        assertThat(declaresMethod(commented, RETIRED.get("resolveShipperName").declaration()))
                .as("注释里的同名文本不算声明").isFalse();

        // 第六批：生命周期族回来必须判真；发货两个重载里任一回来也判真
        String lifecycleForward = "public class OrderService {\n"
                + "    public void updateOrderStatus(String id, String status) { }\n}";
        assertThat(declaresMethod(lifecycleForward, RETIRED.get("updateOrderStatus").declaration()))
                .as("状态流转转发回来必须被判真（否则删掉之后就没人看管了）").isTrue();
        String shipOverload = "public class OrderService {\n"
                + "    public OrderShipmentOutcome shipWithLogistics(String orderId, String trackingNo,\n"
                + "                                          String logisticsCompany,\n"
                + "                                          OrderLogisticsWriter.ShippingDetails details) { }\n}";
        assertThat(declaresMethod(shipOverload, RETIRED.get("shipWithLogistics").declaration()))
                .as("发货重载回来必须被判真（锚点不区分重载）").isTrue();
        // 直驱实现点的调用形态不得被判成「转发回来」（返回类型 + 左括号 的锚点不会命中调用串）
        String directDrive = "orderLifecycleService.updateOrderStatus(id, status, orderService.sharedParts());";
        assertThat(declaresMethod(directDrive, RETIRED.get("updateOrderStatus").declaration()))
                .as("直驱实现点的调用串不算声明").isFalse();

        // 第七批：实体实现的声明锚点同样是「返回类型（或 void）+ 方法名 + 左括号」；
        // 实现点的 updatePendingOrderContent 比门面多一个门面实参 ⇒ 整行锚点在两侧不是同一串，
        // 而调用形态（`orderEntityWriteService.xxx(`）不含返回类型 ⇒ 不会被误判成声明。
        String writeForward = "public class OrderService {\n"
                + "    public void deleteOrder(String id) { }\n}";
        assertThat(declaresMethod(writeForward, RETIRED.get("deleteOrder").declaration()))
                .as("删单实现搬回门面必须被判真（否则搬完之后就没人看管了）").isTrue();
        String writeForwardMultiArg = "public class OrderService {\n"
                + "    public OrderDetailResponse updatePendingOrderContent(String id, OrderContentUpdateRequest request) { }\n}";
        assertThat(declaresMethod(writeForwardMultiArg, RETIRED.get("updatePendingOrderContent").declaration()))
                .as("内容编辑实现搬回门面必须被判真（锚点不区分形参个数）").isTrue();
        String writeDirectDrive = "return orderEntityWriteService.updatePendingOrderContent(id, request, orderService.sharedParts());";
        assertThat(declaresMethod(writeDirectDrive, RETIRED.get("updatePendingOrderContent").declaration()))
                .as("直驱实现点（带门面实参）的调用串不算声明").isFalse();

        // 第八批：三个锚点各自正反一次。①「门面声明回来」判真；②「直驱实现点（带门面实参）」判假；
        // ③ 两个同族方法名的前缀差别（createOrderForAgent vs createOrder / restoreStockForReturn vs
        //    orderStockService）不会被互相误判 —— 这两个坑前几批各踩过一次。
        assertThat(declaresMethod("public class OrderService {\n"
                        + "    public Object updateOrderForAgent(String rawId, AgentOrderUpdateRequest r, Long t) { }\n}",
                RETIRED.get("updateOrderForAgent").declaration()))
                .as("改单编排搬回门面必须被判真（否则搬走之后就没人看管了）").isTrue();
        assertThat(declaresMethod("    public OrderDetailResponse createOrderForAgent(AgentOrderCreateRequest r, Long t) { }",
                RETIRED.get("createOrderForAgent").declaration()))
                .as("建单 Agent 转发回来必须被判真").isTrue();
        assertThat(declaresMethod("    public void restoreStockForReturn(String orderId) { stockService().restoreStockForReturn(orderId); }",
                RETIRED.get("restoreStockForReturn").declaration()))
                .as("售后回补转发回来必须被判真").isTrue();
        String agentDirectDrive = "return orderCreationService.createOrderForAgent(request, tenantId, orderService.sharedParts());";
        assertThat(declaresMethod(agentDirectDrive, RETIRED.get("createOrderForAgent").declaration()))
                .as("直驱建单实现点（第三参是门面实例）的调用串不算声明").isFalse();
        String stockDirectDrive = "orderStockService.restoreStockForReturn(ticket.getOrderId());";
        assertThat(declaresMethod(stockDirectDrive, RETIRED.get("restoreStockForReturn").declaration()))
                .as("直驱库存实现点的调用串不算声明").isFalse();
        assertThat(stockDirectDrive.contains("orderService.restoreStockForReturn("))
                .as("`orderStockService.restoreStockForReturn(` 不得被「经门面调用」的谓词误判（前缀差一个 Stock）").isFalse();
        assertThat(agentDirectDrive.contains("orderService.createOrderForAgent("))
                .as("`orderCreationService.createOrderForAgent(` 不得被误判成经门面调用").isFalse();

        String consumerThroughFacade = "String name = orderService.resolveShipperName(provided);";
        assertThat(consumerThroughFacade.contains("orderService.resolveShipperName("))
                .as("消费方绕门面的形态必须被判真（这样上一条「零处」才有判别力）").isTrue();
        String consumerDirect = "String name = orderLifecycleService.resolveShipperName(provided);";
        assertThat(consumerDirect.contains("orderService.resolveShipperName("))
                .as("直连实现点的形态必须被判假").isFalse();

        // 第四批的驱动面：两种「经门面」写法都必须判真，直驱实现点判假
        String driveThroughFacade = "when(orderService.getOrderPage(1L, 20L)).thenReturn(page);";
        String verifyThroughFacade = "verify(orderService).getOrderById(id, scope);";
        String driveDirect = "orderQueryService.getOrderPage(1L, 20L, null, null);";
        assertThat(driveThroughFacade.contains("orderService.getOrderPage("))
                .as("when(...) 形态必须判真").isTrue();
        assertThat(verifyThroughFacade.contains("orderService).getOrderById("))
                .as("verify(orderService). 形态必须判真（否则换个写法就绕过了判据）").isTrue();
        assertThat(driveDirect.contains("orderService.getOrderPage(")
                || driveDirect.contains("orderService).getOrderPage("))
                .as("直驱实现点的形态必须判假").isFalse();
    }

    // ──────────────────────────────────────────── 解析件

    /**
     * 源码里是否有该方法**声明**（不是调用、也不是注释里提一句）。
     *
     * <p>判据 = 逐字声明串出现在**剥掉注释后**的源码里。剥注释是必需的：本仓习惯在 javadoc 里写
     * 「见 {@code OrderService.xxx}」这类引用，不剥就会把**说明**当成**声明**（判据被自己的文案喂红/喂绿，
     * 同 {@code migao-dev-flow} §17.3 的反面形态）。</p>
     */
    static boolean declaresMethod(String source, String declaration) {
        return stripComments(source).contains(declaration);
    }

    /** 剥掉行注释与块注释（保留字符串字面量里的内容 —— 本判据扫的是声明形态，不判字符串）。 */
    static String stripComments(String src) {
        StringBuilder out = new StringBuilder(src.length());
        boolean inBlock = false;
        boolean inLine = false;
        for (int i = 0; i < src.length(); i++) {
            char c = src.charAt(i);
            char next = i + 1 < src.length() ? src.charAt(i + 1) : '\0';
            if (inBlock) {
                if (c == '*' && next == '/') {
                    inBlock = false;
                    i++;
                }
                continue;
            }
            if (inLine) {
                if (c == '\n') {
                    inLine = false;
                    out.append(c);
                }
                continue;
            }
            if (c == '/' && next == '*') {
                inBlock = true;
                i++;
                continue;
            }
            if (c == '/' && next == '/') {
                inLine = true;
                i++;
                continue;
            }
            out.append(c);
        }
        return out.toString();
    }

    /** 读文件（失败即抛 —— 判据的载体读不到不许静默跳过）。 */
    private static String readQuietly(Path path) {
        try {
            return Files.readString(path, StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new UncheckedIOException("判据载体读取失败：" + path, e);
        }
    }

    /** 全 {@code src/main/java} 语料里，命中该字面量（剥注释后）的**仓库相对路径**集合。 */
    private static List<String> filesContaining(String needle) throws IOException {
        Path root = Path.of("src", "main", "java");
        try (Stream<Path> stream = Files.walk(root)) {
            return stream.filter(p -> p.toString().endsWith(".java"))
                    .filter(p -> {
                        try {
                            return stripComments(Files.readString(p, StandardCharsets.UTF_8)).contains(needle);
                        } catch (IOException e) {
                            throw new IllegalStateException("读取失败： " + p, e);
                        }
                    })
                    .map(p -> root.relativize(p).toString())
                    .sorted()
                    .toList();
        }
    }

}
